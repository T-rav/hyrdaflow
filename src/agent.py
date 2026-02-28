"""Implementation agent runner — launches Claude Code to solve issues."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from events import EventBus, EventType, HydraFlowEvent
from models import Task, WorkerResult, WorkerStatus
from review_insights import ReviewInsightStore, get_common_feedback_section
from runner_constants import MEMORY_SUGGESTION_PROMPT
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.agent")


class AgentRunner(BaseRunner):
    """Launches a ``claude -p`` process to implement a GitHub issue.

    The agent works inside an isolated git worktree and commits its
    changes but does **not** push or create PRs.
    """

    _log = logger
    _MAX_DISCUSSION_COMMENT_CHARS = 500
    _MAX_COMMON_FEEDBACK_CHARS = 2_000
    _MAX_IMPL_PLAN_CHARS = 6_000
    _MAX_REVIEW_FEEDBACK_CHARS = 2_000

    _SELF_CHECK_CHECKLIST = """
## Self-Check Before Committing

Run through this checklist before your final commit:

- [ ] **Tests cover all new/changed code** — every new function, branch, and edge case has a test
- [ ] **No missing imports** — all new symbols are imported; removed code has imports cleaned up
- [ ] **Type hints are correct** — function signatures match actual usage; no `Any` where a concrete type exists
- [ ] **Edge cases handled** — empty inputs, None values, boundary conditions are addressed
- [ ] **No leftover debug code** — no print(), console.log(), or commented-out code
- [ ] **Error messages are clear** — exceptions include context (what failed, what was expected)
- [ ] **Existing tests still pass** — your changes don't break unrelated tests
- [ ] **Commit message matches changes** — "Fixes #N: <summary>" accurately describes what changed
"""

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        super().__init__(config, event_bus, runner)
        self._insights = ReviewInsightStore(config.memory_dir)

    async def run(
        self,
        task: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int = 0,
        review_feedback: str = "",
    ) -> WorkerResult:
        """Run the implementation agent for *task*.

        Returns a :class:`WorkerResult` with success/failure info.
        """
        start = time.monotonic()
        result = WorkerResult(
            issue_number=task.id,
            branch=branch,
            worktree_path=str(worktree_path),
        )

        await self._emit_status(task.id, worker_id, WorkerStatus.RUNNING)

        if self._config.dry_run:
            logger.info("[dry-run] Would run agent for issue #%d", task.id)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            await self._emit_status(task.id, worker_id, WorkerStatus.DONE)
            return result

        try:
            # Build and run the configured agent command
            cmd = self._build_command(worktree_path)
            prompt, prompt_stats = self._build_prompt_with_stats(
                task, review_feedback=review_feedback
            )
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": task.id, "source": "implementer"},
                telemetry_stats=prompt_stats,
            )
            result.transcript = transcript

            # Mandatory pre-quality self-review/correction loop
            (
                pre_quality_success,
                pre_quality_msg,
                pre_quality_attempts,
            ) = await self._run_pre_quality_review_loop(
                task, worktree_path, branch, worker_id
            )
            result.pre_quality_review_attempts = pre_quality_attempts
            if not pre_quality_success:
                result.success = False
                result.error = pre_quality_msg
                result.commits = await self._count_commits(worktree_path, branch)
                await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)
                result.duration_seconds = time.monotonic() - start
                return result

            # Verify the agent produced valid work
            await self._emit_status(task.id, worker_id, WorkerStatus.TESTING)
            success, verify_msg = await self._verify_result(worktree_path, branch)

            # If quality failed but commits exist, try the fix loop
            if (
                not success
                and verify_msg != "No commits found on branch"
                and self._config.max_quality_fix_attempts > 0
            ):
                success, verify_msg, attempts = await self._run_quality_fix_loop(
                    task, worktree_path, branch, verify_msg, worker_id
                )
                result.quality_fix_attempts = attempts

            result.success = success
            if not success:
                result.error = verify_msg

            # Count commits
            result.commits = await self._count_commits(worktree_path, branch)

            status = WorkerStatus.DONE if success else WorkerStatus.FAILED
            await self._emit_status(task.id, worker_id, status)

        except CreditExhaustedError:
            raise
        except Exception as exc:
            result.success = False
            result.error = str(exc)
            logger.error(
                "Agent failed for issue #%d: %s",
                task.id,
                exc,
                extra={"issue": task.id},
            )
            await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)

        result.duration_seconds = time.monotonic() - start

        # Persist transcript to disk
        try:
            self._save_transcript("issue", result.issue_number, result.transcript)
        except OSError:
            logger.warning(
                "Failed to save transcript for issue #%d",
                result.issue_number,
                exc_info=True,
                extra={"issue": result.issue_number},
            )

        return result

    @staticmethod
    def _extract_plan_comment(comments: list[str]) -> tuple[str, list[str]]:
        """Separate the planner's implementation plan from other comments.

        Returns ``(plan_text, remaining_comments)``.  *plan_text* is the
        cleaned body of the first comment that contains
        ``## Implementation Plan``, or an empty string if none is found.
        """
        plan = ""
        remaining: list[str] = []
        for c in comments:
            if not plan and "## Implementation Plan" in c:
                plan = AgentRunner._strip_plan_noise(c)
            else:
                remaining.append(c)
        return plan, remaining

    @staticmethod
    def _strip_plan_noise(raw_comment: str) -> str:
        """Strip boilerplate noise from a planner comment.

        Removes HTML comments, extracts the plan body between
        ``## Implementation Plan`` and the first ``---`` separator
        or end of comment, then drops footer and branch-info lines.
        """
        # Remove HTML comments
        text = re.sub(r"<!--.*?-->", "", raw_comment, flags=re.DOTALL)

        # Extract content after "## Implementation Plan" up to first "---" line or end
        plan_match = re.search(
            r"## Implementation Plan\s*\n(.*?)(?=^---$|\Z)",
            text,
            re.DOTALL | re.MULTILINE,
        )
        if plan_match:
            text = plan_match.group(1)

        # Remove footer and branch-info lines
        lines = text.splitlines()
        cleaned: list[str] = []
        for line in lines:
            stripped = line.strip()
            if "Generated by HydraFlow Planner" in stripped:
                continue
            if stripped.startswith("**Branch:**"):
                continue
            cleaned.append(line)

        return "\n".join(cleaned).strip()

    def _load_plan_fallback(self, issue_number: int) -> str:
        """Attempt to load a saved plan from ``.hydraflow/plans/issue-N.md``.

        Returns the plan text or empty string if not found.
        """
        plan_path = self._config.plans_dir / f"issue-{issue_number}.md"
        if not plan_path.is_file():
            return ""

        logger.warning(
            "No plan comment found for issue #%d — falling back to %s",
            issue_number,
            plan_path,
            extra={"issue": issue_number},
        )
        content = plan_path.read_text()

        # Strip the header/footer added by PlannerRunner._save_plan
        content = re.sub(r"^# Plan for Issue #\d+\s*\n", "", content)
        content = re.sub(r"\n---\n\*\*Summary:\*\*.*$", "", content, flags=re.DOTALL)

        return content.strip()

    def _get_review_feedback_section(self) -> str:
        """Build a common review feedback section from recent review data.

        Returns an empty string if no data is available or on any error.
        """
        try:
            reviews_path = self._config.memory_dir / "reviews.jsonl"

            def _load_feedback(_cfg: HydraFlowConfig) -> str:
                recent = self._insights.load_recent(self._config.review_insight_window)
                return get_common_feedback_section(recent)

            feedback, _hit = self._context_cache.get_or_load(
                key="common_review_feedback",
                source_path=reviews_path,
                loader=_load_feedback,
            )
            return feedback
        except Exception:  # noqa: BLE001
            return ""

    def _summarize_for_prompt(self, text: str, max_chars: int, label: str) -> str:
        """Return text trimmed for prompt efficiency with a traceable note."""
        if len(text) <= max_chars:
            return text

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        cue_lines = [
            ln for ln in lines if re.match(r"^([-*]|\d+\.)\s+", ln) or "## " in ln
        ]
        selected = cue_lines[:10] if cue_lines else lines[:10]
        compact = "\n".join(f"- {ln[:200]}" for ln in selected).strip()
        if not compact:
            compact = text[:max_chars]
        return (
            f"{compact}\n\n"
            f"[{label} summarized from {len(text):,} chars to reduce prompt size]"
        )

    def _truncate_comment_for_prompt(self, text: str) -> str:
        """Return one discussion comment compacted for prompt efficiency."""
        raw = (text or "").strip()
        if len(raw) <= self._MAX_DISCUSSION_COMMENT_CHARS:
            return raw
        return (
            raw[: self._MAX_DISCUSSION_COMMENT_CHARS]
            + f"\n[Comment truncated from {len(raw):,} chars]"
        )

    def _build_prompt(self, issue: Task, review_feedback: str = "") -> str:
        """Build the implementation prompt for the agent."""
        prompt, _stats = self._build_prompt_with_stats(
            issue, review_feedback=review_feedback
        )
        return prompt

    def _build_prompt_with_stats(
        self, issue: Task, review_feedback: str = ""
    ) -> tuple[str, dict[str, object]]:
        """Build the implementation prompt and pruning stats."""
        plan_comment, other_comments = self._extract_plan_comment(issue.comments)
        history_before = len(plan_comment) + sum(len(c) for c in other_comments)
        history_after = 0

        # Fallback to saved plan file
        if not plan_comment:
            plan_comment = self._load_plan_fallback(issue.id)
            history_before += len(plan_comment)
            if not plan_comment:
                logger.error(
                    "No plan found for issue #%d — implementer will proceed without a plan",
                    issue.id,
                    extra={"issue": issue.id},
                )

        plan_section = ""
        if plan_comment:
            plan_comment = self._summarize_for_prompt(
                plan_comment,
                max_chars=self._MAX_IMPL_PLAN_CHARS,
                label="Implementation plan",
            )
            history_after += len(plan_comment)
            plan_section = (
                f"\n\n## Implementation Plan\n\n"
                f"Follow this plan closely. It was created by a planner agent "
                f"that already analyzed the codebase.\n\n"
                f"{plan_comment}"
            )

        review_feedback_section = ""
        if review_feedback:
            history_before += len(review_feedback)
            review_feedback = self._summarize_for_prompt(
                review_feedback,
                max_chars=self._MAX_REVIEW_FEEDBACK_CHARS,
                label="Review feedback",
            )
            history_after += len(review_feedback)
            review_feedback_section = (
                f"\n\n## Review Feedback\n\n"
                f"A reviewer rejected the previous implementation. "
                f"Address all feedback below:\n\n"
                f"{review_feedback}"
            )

        comments_section = ""
        if other_comments:
            max_comments = 6
            selected_comments = other_comments[:max_comments]
            compact_comments = [
                self._truncate_comment_for_prompt(c) for c in selected_comments
            ]
            formatted = "\n".join(f"- {c}" for c in compact_comments)
            history_after += len(formatted)
            comments_section = f"\n\n## Discussion\n{formatted}"
            if len(other_comments) > max_comments:
                comments_section += f"\n- ... ({len(other_comments) - max_comments} more comments omitted)"

        raw_feedback_section = self._get_review_feedback_section()
        feedback_section = ""
        if raw_feedback_section:
            history_before += len(raw_feedback_section)
            compact_feedback = self._summarize_for_prompt(
                raw_feedback_section,
                max_chars=self._MAX_COMMON_FEEDBACK_CHARS,
                label="Common review feedback",
            )
            history_after += len(compact_feedback)
            feedback_section = compact_feedback

        manifest_section, memory_section = self._inject_manifest_and_memory()

        # Runtime log injection (opt-in)
        log_section = ""
        if self._config.inject_runtime_logs:
            from log_context import load_runtime_logs  # noqa: PLC0415

            logs = load_runtime_logs(self._config)
            if logs:
                log_section = f"\n\n## Recent Application Logs\n\n```\n{logs}\n```"

        # Truncate issue body if too long
        body = issue.body
        max_body = self._config.max_issue_body_chars
        body_before = len(body)
        if len(body) > max_body:
            body = (
                body[:max_body]
                + f"\n\n[Body truncated at {max_body:,} chars — see full issue on GitHub]"
            )
        body_after = len(body)

        test_cmd = self._config.test_command

        prompt = f"""You are implementing GitHub issue #{issue.id}.

## Issue: {issue.title}

{body}{plan_section}{review_feedback_section}{comments_section}{manifest_section}{memory_section}{log_section}

## Instructions

1. Understand the issue and relevant code paths.
2. Write/adjust tests first, then implement.
3. Run Pre-Quality Review Skill for correctness, plan adherence, and missing tests.
4. Run Run-Tool Skill: `make lint` → `{test_cmd}` → `make quality`; fix and rerun.
5. Commit with: "Fixes #{issue.id}: <concise summary>"
{feedback_section}
{self._SELF_CHECK_CHECKLIST}
## UI Guidelines

- Before creating UI components, search `src/ui/src/components/` for existing patterns to reuse.
- Import constants, types, and shared styles from centralized modules (e.g. `src/ui/src/constants.js`, `src/ui/src/theme.js`) — never duplicate.
- Apply responsive design: set `minWidth` on layout containers, use `flexShrink: 0` on fixed-width panels.
- Match existing spacing (4px grid), colors (CSS variables from `theme.js`), and component conventions.

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
- If you encounter issues, commit what works with a descriptive message.

{MEMORY_SUGGESTION_PROMPT.format(context="implementation")}"""
        stats = {
            "history_chars_before": history_before,
            "history_chars_after": history_after,
            "context_chars_before": body_before,
            "context_chars_after": body_after,
            "pruned_chars_total": max(0, history_before - history_after)
            + max(0, body_before - body_after),
            "section_chars": {
                "issue_body_before": body_before,
                "issue_body_after": body_after,
                "history_before": history_before,
                "history_after": history_after,
            },
        }
        return prompt, stats

    async def _verify_result(
        self, worktree_path: Path, branch: str
    ) -> tuple[bool, str]:
        """Check that the agent produced commits and ``make quality`` passes.

        Returns ``(success, error_output)``.  On failure the error output
        contains the last 3000 characters of combined stdout/stderr.
        """
        # Check for commits on the branch
        commit_count = await self._count_commits(worktree_path, branch)
        if commit_count == 0:
            return False, "No commits found on branch"

        # Run the full quality gate
        return await self._verify_quality(worktree_path)

    def _build_quality_fix_prompt(
        self,
        issue: Task,
        error_output: str,
        attempt: int,
    ) -> str:
        """Build a focused prompt for fixing quality gate failures."""
        return f"""You are fixing quality gate failures for issue #{issue.id}: {issue.title}

## Quality Gate Failure Output

```
{error_output[-self._config.error_output_max_chars :]}
```

## Fix Attempt {attempt}

1. Read the failing output above carefully.
2. Fix ALL lint, type-check, security, and test issues.
3. Do NOT skip or disable tests, type checks, or lint rules.
4. Run `make quality` to verify your fixes pass the full pipeline.
5. Commit your fixes with message: "quality-fix: <description> (#{issue.id})"

Focus on fixing the root causes, not suppressing warnings.
"""

    def _build_pre_quality_review_prompt(self, issue: Task, attempt: int) -> str:
        """Build the pre-quality review/correction skill prompt."""
        return f"""You are running the Pre-Quality Review Skill for issue #{issue.id}: {issue.title}.

Attempt: {attempt}

Scope:
- review current branch changes for correctness and plan adherence
- add/fix tests for missing coverage and edge cases
- verify all new functions have type hints and all imports are correct
- check edge cases: empty inputs, None values, missing keys, boundary conditions
- apply code fixes directly in this working tree

Constraints:
- Do not push or open PRs
- Prefer minimal safe changes
- Keep edits scoped to issue intent

Required output:
PRE_QUALITY_REVIEW_RESULT: OK
or
PRE_QUALITY_REVIEW_RESULT: RETRY
SUMMARY: <one-line summary>
"""

    def _build_pre_quality_run_tool_prompt(self, issue: Task, attempt: int) -> str:
        """Build the run-tool skill prompt for quality/test commands."""
        test_cmd = self._config.test_command
        return f"""You are running the Run-Tool Skill for issue #{issue.id}: {issue.title}.

Attempt: {attempt}

Run these commands in order and fix failures:
1. `make lint`
2. `{test_cmd}`
3. `make quality`

Rules:
- If a command fails, fix root causes and rerun from command 1
- Do not skip tests or reduce quality gates
- Keep changes scoped to this issue

Required output:
RUN_TOOL_RESULT: OK
or
RUN_TOOL_RESULT: RETRY
SUMMARY: <one-line summary>
"""

    def _build_pre_quality_review_command(self) -> list[str]:
        """Build the command used for pre-quality review skill."""
        return build_agent_command(
            tool=self._config.review_tool,
            model=self._config.review_model,
        )

    @staticmethod
    def _parse_skill_result(transcript: str, marker: str) -> tuple[bool, str]:
        """Parse a skill result marker line from transcript text.

        Returns ``(ok, summary)``. Missing marker defaults to OK to preserve
        backward compatibility with older prompts/tools.
        """
        pattern = rf"{re.escape(marker)}:\s*(OK|RETRY)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if not match:
            return True, "No explicit result marker"
        status = match.group(1).upper()
        summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else ""
        return status == "OK", summary

    async def _run_pre_quality_review_loop(
        self,
        issue: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int,
    ) -> tuple[bool, str, int]:
        """Run mandatory pre-quality review + run-tool skills before verification."""
        commits = await self._count_commits(worktree_path, branch)
        max_attempts = self._config.max_pre_quality_review_attempts
        if commits == 0 or max_attempts <= 0:
            return True, "Skipped pre-quality review", 0

        for attempt in range(1, max_attempts + 1):
            await self._emit_status(
                issue.id, worker_id, WorkerStatus.PRE_QUALITY_REVIEW
            )

            review_prompt = self._build_pre_quality_review_prompt(issue, attempt)
            review_cmd = self._build_pre_quality_review_command()
            review_transcript = await self._execute(
                review_cmd,
                review_prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
            )
            review_ok, review_summary = self._parse_skill_result(
                review_transcript, "PRE_QUALITY_REVIEW_RESULT"
            )

            run_tool_prompt = self._build_pre_quality_run_tool_prompt(issue, attempt)
            run_tool_cmd = self._build_command(worktree_path)
            run_tool_transcript = await self._execute(
                run_tool_cmd,
                run_tool_prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
            )
            run_tool_ok, run_tool_summary = self._parse_skill_result(
                run_tool_transcript, "RUN_TOOL_RESULT"
            )

            if review_ok and run_tool_ok:
                return True, "OK", attempt

            last_summary = "; ".join(
                s for s in [review_summary, run_tool_summary] if s
            ).strip()
            if attempt == max_attempts:
                return (
                    False,
                    "Pre-quality review loop exhausted"
                    + (f": {last_summary}" if last_summary else ""),
                    attempt,
                )

        return False, "Pre-quality review loop failed", max_attempts

    async def _run_quality_fix_loop(
        self,
        issue: Task,
        worktree_path: Path,
        branch: str,
        error_output: str,
        worker_id: int,
    ) -> tuple[bool, str, int]:
        """Retry loop: invoke Claude to fix quality failures.

        Returns ``(success, last_error, attempts_made)``.
        """
        max_attempts = self._config.max_quality_fix_attempts
        last_error = error_output

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Quality fix attempt %d/%d for issue #%d",
                attempt,
                max_attempts,
                issue.id,
            )
            await self._emit_status(issue.id, worker_id, WorkerStatus.QUALITY_FIX)

            prompt = self._build_quality_fix_prompt(issue, last_error, attempt)
            cmd = self._build_command(worktree_path)
            await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
            )

            success, verify_msg = await self._verify_result(worktree_path, branch)
            if success:
                return True, "OK", attempt

            last_error = verify_msg

        return False, last_error, max_attempts

    async def _count_commits(self, worktree_path: Path, branch: str) -> int:
        """Count commits on *branch* ahead of main."""
        try:
            result = await self._runner.run_simple(
                [
                    "git",
                    "rev-list",
                    "--count",
                    f"origin/{self._config.main_branch}..{branch}",
                ],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            return int(result.stdout)
        except (TimeoutError, ValueError, FileNotFoundError):
            return 0

    async def _emit_status(
        self, issue_number: int, worker_id: int, status: WorkerStatus
    ) -> None:
        """Publish a worker status event."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                data={
                    "issue": issue_number,
                    "worker": worker_id,
                    "status": status.value,
                    "role": "implementer",
                },
            )
        )
