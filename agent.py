"""Implementation agent runner — launches Claude Code to solve issues."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from execution import get_default_runner
from manifest import load_project_manifest
from memory import load_memory_digest
from models import GitHubIssue, WorkerResult, WorkerStatus
from review_insights import ReviewInsightStore, get_common_feedback_section
from runner_utils import stream_claude_process, terminate_processes
from subprocess_util import CreditExhaustedError

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.agent")


class AgentRunner:
    """Launches a ``claude -p`` process to implement a GitHub issue.

    The agent works inside an isolated git worktree and commits its
    changes but does **not** push or create PRs.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._insights = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        self._runner = runner or get_default_runner()

    async def run(
        self,
        issue: GitHubIssue,
        worktree_path: Path,
        branch: str,
        worker_id: int = 0,
        review_feedback: str = "",
    ) -> WorkerResult:
        """Run the implementation agent for *issue*.

        Returns a :class:`WorkerResult` with success/failure info.
        """
        start = time.monotonic()
        result = WorkerResult(
            issue_number=issue.number,
            branch=branch,
            worktree_path=str(worktree_path),
        )

        await self._emit_status(issue.number, worker_id, WorkerStatus.RUNNING)

        if self._config.dry_run:
            logger.info("[dry-run] Would run agent for issue #%d", issue.number)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            await self._emit_status(issue.number, worker_id, WorkerStatus.DONE)
            return result

        try:
            # Build and run the configured agent command
            cmd = self._build_command(worktree_path)
            prompt = self._build_prompt(issue, review_feedback=review_feedback)
            transcript = await self._execute(cmd, prompt, worktree_path, issue.number)
            result.transcript = transcript

            # Mandatory pre-quality self-review/correction loop
            (
                pre_quality_success,
                pre_quality_msg,
                pre_quality_attempts,
            ) = await self._run_pre_quality_review_loop(
                issue, worktree_path, branch, worker_id
            )
            result.pre_quality_review_attempts = pre_quality_attempts
            if not pre_quality_success:
                result.success = False
                result.error = pre_quality_msg
                result.commits = await self._count_commits(worktree_path, branch)
                await self._emit_status(issue.number, worker_id, WorkerStatus.FAILED)
                result.duration_seconds = time.monotonic() - start
                return result

            # Verify the agent produced valid work
            await self._emit_status(issue.number, worker_id, WorkerStatus.TESTING)
            success, verify_msg = await self._verify_result(worktree_path, branch)

            # If quality failed but commits exist, try the fix loop
            if (
                not success
                and verify_msg != "No commits found on branch"
                and self._config.max_quality_fix_attempts > 0
            ):
                success, verify_msg, attempts = await self._run_quality_fix_loop(
                    issue, worktree_path, branch, verify_msg, worker_id
                )
                result.quality_fix_attempts = attempts

            result.success = success
            if not success:
                result.error = verify_msg

            # Count commits
            result.commits = await self._count_commits(worktree_path, branch)

            status = WorkerStatus.DONE if success else WorkerStatus.FAILED
            await self._emit_status(issue.number, worker_id, status)

        except CreditExhaustedError:
            raise
        except Exception as exc:
            result.success = False
            result.error = str(exc)
            logger.error(
                "Agent failed for issue #%d: %s",
                issue.number,
                exc,
                extra={"issue": issue.number},
            )
            await self._emit_status(issue.number, worker_id, WorkerStatus.FAILED)

        result.duration_seconds = time.monotonic() - start

        # Persist transcript to disk
        try:
            self._save_transcript(result)
        except OSError:
            logger.warning(
                "Failed to save transcript for issue #%d",
                result.issue_number,
                exc_info=True,
            )

        return result

    def _save_transcript(self, result: WorkerResult) -> None:
        """Write the transcript to .hydraflow/logs/ for post-mortem review."""
        log_dir = self._config.repo_root / ".hydraflow" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"issue-{result.issue_number}.txt"
            path.write_text(result.transcript)
            logger.info(
                "Transcript saved to %s",
                path,
                extra={"issue": result.issue_number},
            )
        except OSError:
            logger.warning(
                "Could not save transcript to %s",
                log_dir,
                exc_info=True,
                extra={"issue": result.issue_number},
            )

    def _build_command(self, worktree_path: Path) -> list[str]:
        """Construct the implementation CLI invocation.

        The working directory is set via ``cwd`` in the subprocess call,
        not via a CLI flag.
        """
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
            budget_usd=self._config.max_budget_usd,
        )

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
        plan_path = (
            self._config.repo_root / ".hydraflow" / "plans" / f"issue-{issue_number}.md"
        )
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
            recent = self._insights.load_recent(self._config.review_insight_window)
            return get_common_feedback_section(recent)
        except Exception:  # noqa: BLE001
            return ""

    def _build_prompt(self, issue: GitHubIssue, review_feedback: str = "") -> str:
        """Build the implementation prompt for the agent."""
        plan_comment, other_comments = self._extract_plan_comment(issue.comments)

        # Fallback to saved plan file
        if not plan_comment:
            plan_comment = self._load_plan_fallback(issue.number)
            if not plan_comment:
                logger.error(
                    "No plan found for issue #%d — implementer will proceed without a plan",
                    issue.number,
                    extra={"issue": issue.number},
                )

        plan_section = ""
        if plan_comment:
            plan_section = (
                f"\n\n## Implementation Plan\n\n"
                f"Follow this plan closely. It was created by a planner agent "
                f"that already analyzed the codebase.\n\n"
                f"{plan_comment}"
            )

        review_feedback_section = ""
        if review_feedback:
            review_feedback_section = (
                f"\n\n## Review Feedback\n\n"
                f"A reviewer rejected the previous implementation. "
                f"Address all feedback below:\n\n"
                f"{review_feedback}"
            )

        comments_section = ""
        if other_comments:
            formatted = "\n".join(f"- {c}" for c in other_comments)
            comments_section = f"\n\n## Discussion\n{formatted}"

        feedback_section = self._get_review_feedback_section()

        # Project manifest injection
        manifest_section = ""
        manifest = load_project_manifest(self._config)
        if manifest:
            manifest_section = f"\n\n## Project Context\n\n{manifest}"

        # Memory digest injection
        memory_section = ""
        digest = load_memory_digest(self._config)
        if digest:
            memory_section = f"\n\n## Accumulated Learnings\n\n{digest}"

        # Truncate issue body if too long
        body = issue.body
        max_body = self._config.max_issue_body_chars
        if len(body) > max_body:
            body = (
                body[:max_body]
                + f"\n\n[Body truncated at {max_body:,} chars — see full issue on GitHub]"
            )

        test_cmd = self._config.test_command

        return f"""You are implementing GitHub issue #{issue.number}.

## Issue: {issue.title}

{body}{plan_section}{review_feedback_section}{comments_section}{manifest_section}{memory_section}

## Instructions

1. Read the issue carefully and understand what needs to be done.
2. Explore the codebase to understand the relevant code.
3. Write comprehensive tests FIRST (TDD approach).
4. Implement the solution.
5. Run a **Pre-Quality Review Skill** (self-review and corrections before quality checks):
   - validate correctness, plan adherence, and edge cases,
   - identify missing/weak tests and add them,
   - simplify/refactor obviously risky code paths.
6. Run a **Run-Tool Skill** for executable checks:
   - run `make lint`,
   - run `{test_cmd}`,
   - run `make quality`,
   - fix failures and rerun until green or clearly blocked.
7. Commit your changes with a message: "Fixes #{issue.number}: <concise summary>"
{feedback_section}
## UI Guidelines

- Before creating UI components, search `ui/src/components/` for existing patterns to reuse.
- Import constants, types, and shared styles from centralized modules (e.g. `ui/src/constants.js`, `ui/src/theme.js`) — never duplicate.
- Apply responsive design: set `minWidth` on layout containers, use `flexShrink: 0` on fixed-width panels.
- Match existing spacing (4px grid), colors (CSS variables from `theme.js`), and component conventions.

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- Write tests for all new code — tests are mandatory.
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Ensure `make quality` passes before committing.
- If you encounter issues, commit what works with a descriptive message.

## Optional: Memory Suggestion

If you discover a reusable pattern or insight during this implementation that would help future agent runs, you may output ONE suggestion:

MEMORY_SUGGESTION_START
title: Short descriptive title
type: knowledge | config | instruction | code
learning: What was learned and why it matters
context: How it was discovered (reference issue/PR numbers)
MEMORY_SUGGESTION_END

Types: knowledge (passive insight), config (suggests config change), instruction (new agent instruction), code (suggests code change).
Actionable types (config, instruction, code) will be routed for human approval.
Only suggest genuinely valuable learnings — not trivial observations.
"""

    def terminate(self) -> None:
        """Kill all active agent subprocesses."""
        terminate_processes(self._active_procs)

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        worktree_path: Path,
        issue_number: int,
    ) -> str:
        """Run the claude process and stream its output."""
        return await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=worktree_path,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data={"issue": issue_number},
            logger=logger,
            runner=self._runner,
        )

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
        try:
            result = await self._runner.run_simple(
                ["make", "quality"],
                cwd=str(worktree_path),
                timeout=3600,
            )
        except FileNotFoundError:
            return False, "make not found — cannot run quality checks"
        except TimeoutError:
            return False, "make quality timed out after 3600s"
        if result.returncode != 0:
            output = "\n".join(filter(None, [result.stdout, result.stderr]))
            return False, f"`make quality` failed:\n{output[-3000:]}"

        return True, "OK"

    def _build_quality_fix_prompt(
        self,
        issue: GitHubIssue,
        error_output: str,
        attempt: int,
    ) -> str:
        """Build a focused prompt for fixing quality gate failures."""
        return f"""You are fixing quality gate failures for issue #{issue.number}: {issue.title}

## Quality Gate Failure Output

```
{error_output[-3000:]}
```

## Fix Attempt {attempt}

1. Read the failing output above carefully.
2. Fix ALL lint, type-check, security, and test issues.
3. Do NOT skip or disable tests, type checks, or lint rules.
4. Run `make quality` to verify your fixes pass the full pipeline.
5. Commit your fixes with message: "quality-fix: <description> (#{issue.number})"

Focus on fixing the root causes, not suppressing warnings.
"""

    def _build_pre_quality_review_prompt(self, issue: GitHubIssue, attempt: int) -> str:
        """Build the pre-quality review/correction skill prompt."""
        return f"""You are running the Pre-Quality Review Skill for issue #{issue.number}: {issue.title}.

Attempt: {attempt}

Scope:
- review current branch changes for correctness and plan adherence
- add/fix tests for missing coverage and edge cases
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

    def _build_pre_quality_run_tool_prompt(
        self, issue: GitHubIssue, attempt: int
    ) -> str:
        """Build the run-tool skill prompt for quality/test commands."""
        test_cmd = self._config.test_command
        return f"""You are running the Run-Tool Skill for issue #{issue.number}: {issue.title}.

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
            budget_usd=self._config.review_budget_usd,
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
        issue: GitHubIssue,
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
                issue.number, worker_id, WorkerStatus.PRE_QUALITY_REVIEW
            )

            review_prompt = self._build_pre_quality_review_prompt(issue, attempt)
            review_cmd = self._build_pre_quality_review_command()
            review_transcript = await self._execute(
                review_cmd, review_prompt, worktree_path, issue.number
            )
            review_ok, review_summary = self._parse_skill_result(
                review_transcript, "PRE_QUALITY_REVIEW_RESULT"
            )

            run_tool_prompt = self._build_pre_quality_run_tool_prompt(issue, attempt)
            run_tool_cmd = self._build_command(worktree_path)
            run_tool_transcript = await self._execute(
                run_tool_cmd, run_tool_prompt, worktree_path, issue.number
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
        issue: GitHubIssue,
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
                issue.number,
            )
            await self._emit_status(issue.number, worker_id, WorkerStatus.QUALITY_FIX)

            prompt = self._build_quality_fix_prompt(issue, last_error, attempt)
            cmd = self._build_command(worktree_path)
            await self._execute(cmd, prompt, worktree_path, issue.number)

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
                timeout=30,
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
