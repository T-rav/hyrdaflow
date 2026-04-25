"""Implementation agent runner — launches Claude Code to solve issues."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from agent_cli import build_agent_command
from base_runner import BaseRunner
from events import EventBus, EventType, HydraFlowEvent
from exception_classify import is_likely_bug, reraise_on_credit_or_bug
from models import LoopResult, Task, WorkerResult, WorkerStatus, WorkerUpdatePayload
from plugin_skill_registry import (
    discover_plugin_skills,
    format_plugin_skills_for_prompt,
    skills_for_phase,
)
from prompt_builder import PromptBuilder
from review_insights import (
    ReviewInsightStore,
    get_common_feedback_section,
    get_escalation_data,
)
from runner_constants import MEMORY_SUGGESTION_PROMPT
from skill_registry import (  # noqa: F401
    AgentSkill,
    discover_tools,
    format_skills_for_prompt,
    format_tools_for_prompt,
    get_skills,
)
from task_graph import extract_phases, has_task_graph, topological_sort

if TYPE_CHECKING:
    from config import Credentials, HydraFlowConfig
    from execution import SubprocessRunner
    from repo_wiki import RepoWikiStore
    from tracing_context import TracingContext
    from tribal_wiki import TribalWikiStore

logger = logging.getLogger("hydraflow.agent")


class AgentRunner(BaseRunner):
    """Launches a ``claude -p`` process to implement a GitHub issue.

    The agent works inside an isolated git worktree and commits its
    changes but does **not** push or create PRs.
    """

    _log = logger
    _phase_name: ClassVar[str] = "implement"

    _SELF_CHECK_CHECKLIST = """
## Self-Check Before Committing

Run through this checklist before your final commit:

- [ ] **Tests cover all new/changed code** — every new function, branch, and edge case has a test
- [ ] **New code is reachable** — every new function/method is actually called from production code; no dead code
- [ ] **Tests verify issue requirements** — tests validate the specific behavior the issue asks for, not just helper code
- [ ] **Failure paths are tested** — error cases, rejected inputs, and unhappy paths have explicit tests
- [ ] **No missing imports** — all new symbols are imported; removed code has imports cleaned up
- [ ] **Type hints are correct** — function signatures match actual usage; no `Any` where a concrete type exists
- [ ] **Edge cases handled** — empty inputs, None values, boundary conditions are addressed
- [ ] **No leftover debug code** — no print(), console.log(), or commented-out code
- [ ] **Error messages are clear** — exceptions include context (what failed, what was expected)
- [ ] **Existing tests still pass** — your changes don't break unrelated tests
- [ ] **Commit message matches changes** — "Fixes #N: <summary>" accurately describes what changed
"""

    @staticmethod
    def _build_self_check_checklist(
        escalations: list[dict[str, str | int | list[str]]],
    ) -> str:
        """Build the self-check checklist, dynamically extending with escalation items."""
        base = AgentRunner._SELF_CHECK_CHECKLIST
        if not escalations:
            return base

        extra_items: list[str] = []
        for esc in escalations:
            items = esc.get("checklist_items", [])
            if isinstance(items, list):
                extra_items.extend(str(item) for item in items)

        if not extra_items:
            return base

        escalated = "\n### Escalated Checks (from recurring review feedback)\n"
        escalated += "\n".join(extra_items) + "\n"
        return base.rstrip() + "\n" + escalated

    @staticmethod
    def _build_spec_match_check(issue: Task) -> str:
        """Build spec-match check guidance for pre-quality review."""
        has_spec = any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (issue.comments or [])
        )
        if not has_spec:
            return ""
        from spec_match import build_spec_context  # noqa: PLC0415

        spec = build_spec_context(issue)
        # Truncate to avoid prompt bloat
        if len(spec) > 3000:
            spec = spec[:3000] + "\n... [truncated]"
        return (
            "\nSpec-match check (CRITICAL for product-track issues):\n"
            "- Compare your implementation against the original product direction below\n"
            "- Every requirement in the spec must be addressed in the code\n"
            "- If anything is missing, implement it now before proceeding\n"
            f"\n<details><summary>Original Spec</summary>\n\n{spec}\n\n</details>\n"
        )

    @staticmethod
    def _build_requirements_gap_section(issue: Task) -> str:
        """Build requirements gap detection section if issue has spec context."""
        has_spec = any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (issue.comments or [])
        )
        if not has_spec:
            return ""
        from spec_match import build_requirements_gap_prompt  # noqa: PLC0415

        return build_requirements_gap_prompt(issue)

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
        *,
        credentials: Credentials | None = None,
        wiki_store: RepoWikiStore | None = None,
        tribal_wiki_store: TribalWikiStore | None = None,
    ) -> None:
        super().__init__(
            config,
            event_bus,
            runner,
            credentials=credentials,
            wiki_store=wiki_store,
            tribal_wiki_store=tribal_wiki_store,
        )
        self._insights = ReviewInsightStore(config.memory_dir)
        from context_cache import ContextSectionCache

        self._context_cache = ContextSectionCache(config)

    async def run(
        self,
        task: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
    ) -> WorkerResult:
        """Run the implementation agent for *task*.

        Returns a :class:`WorkerResult` with success/failure info.
        """
        start = time.monotonic()
        result = WorkerResult(
            issue_number=task.id,
            branch=branch,
            workspace_path=str(worktree_path),
        )

        await self._emit_status(task.id, worker_id, WorkerStatus.RUNNING)

        if self._config.dry_run:
            logger.info("[dry-run] Would run agent for issue #%d", task.id)
            result.success = True
            result.duration_seconds = time.monotonic() - start
            await self._emit_status(task.id, worker_id, WorkerStatus.DONE)
            return result

        try:
            # Snapshot CLAUDE.md before agent runs for integrity check
            claude_md_snapshot = self._snapshot_claude_md(worktree_path)

            # Build and run the configured agent command
            cmd = self._build_command(worktree_path)
            prompt, prompt_stats = await self._build_prompt_with_stats(
                task,
                review_feedback=review_feedback,
                prior_failure=prior_failure,
                bead_mapping=bead_mapping,
            )
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": task.id, "source": "implementer"},
                telemetry_stats=prompt_stats,
            )
            result.transcript = transcript

            # Guard: restore CLAUDE.md if the agent removed content
            self._guard_claude_md(worktree_path, claude_md_snapshot, task.id)

            # Force-commit any uncommitted work the agent left behind
            await self._force_commit_uncommitted(task, worktree_path)

            # Load plan text for skills that need it (e.g. plan-compliance)
            skill_plan_text, _ = self._extract_plan_comment(task.comments)
            if not skill_plan_text:
                skill_plan_text = self._load_plan_fallback(task.id)

            # Run registered post-implementation skills (diff-sanity, test-adequacy, etc.)
            for skill in get_skills():
                skill_result = await self._run_skill(
                    skill,
                    task,
                    worktree_path,
                    branch,
                    worker_id,
                    plan_text=skill_plan_text,
                )
                if not skill_result.passed and skill.blocking:
                    logger.warning(
                        "%s flagged issues for #%d: %s",
                        skill.name,
                        task.id,
                        skill_result.summary,
                    )
                    result.success = False
                    result.error = f"{skill.name} failed: {skill_result.summary}"
                    result.commits = await self._count_commits(worktree_path, branch)
                    await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)
                    result.duration_seconds = time.monotonic() - start
                    return result
                if not skill_result.passed:
                    logger.warning(
                        "%s flagged gaps for #%d: %s (non-blocking)",
                        skill.name,
                        task.id,
                        skill_result.summary,
                    )

            # Mandatory pre-quality self-review/correction loop
            pre_quality = await self._run_pre_quality_review_loop(
                task, worktree_path, branch, worker_id
            )
            result.pre_quality_review_attempts = pre_quality.attempts
            if not pre_quality.passed:
                result.success = False
                result.error = pre_quality.summary
                result.commits = await self._count_commits(worktree_path, branch)
                await self._emit_status(task.id, worker_id, WorkerStatus.FAILED)
                result.duration_seconds = time.monotonic() - start
                return result

            # Verify the agent produced valid work
            await self._emit_status(task.id, worker_id, WorkerStatus.TESTING)
            verify = await self._verify_result(worktree_path, branch)

            # If quality failed but commits exist, try the fix loop
            success = verify.passed
            last_msg = verify.summary
            if (
                not success
                and last_msg != "No commits found on branch"
                and self._config.max_quality_fix_attempts > 0
            ):
                fix = await self._run_quality_fix_loop(
                    task, worktree_path, branch, last_msg, worker_id
                )
                success = fix.passed
                last_msg = fix.summary
                result.quality_fix_attempts = fix.attempts

            result.success = success
            if not success:
                result.error = last_msg

            # Count commits
            result.commits = await self._count_commits(worktree_path, branch)

            status = WorkerStatus.DONE if success else WorkerStatus.FAILED
            await self._emit_status(task.id, worker_id, status)

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            result.success = False
            result.error = repr(exc)
            logger.exception(
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
        except Exception as exc:  # noqa: BLE001
            if is_likely_bug(exc):
                raise
            return ""

    def _get_escalation_data(self) -> list[dict[str, str | int | list[str]]]:
        """Return escalation data for recurring feedback categories.

        Uses the context cache with a separate key. The cache stores
        JSON-serialized data since the cache interface is typed for strings.
        Returns an empty list on any error.
        """
        try:
            reviews_path = self._config.memory_dir / "reviews.jsonl"

            def _load_escalations(_cfg: HydraFlowConfig) -> str:
                recent = self._insights.load_recent(self._config.review_insight_window)
                data = get_escalation_data(
                    recent,
                    threshold=self._config.review_pattern_threshold,
                )
                return json.dumps(data)

            raw, _hit = self._context_cache.get_or_load(
                key="review_escalations",
                source_path=reviews_path,
                loader=_load_escalations,
            )
            if not raw:
                return []
            return json.loads(raw)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return []
        except Exception as exc:  # noqa: BLE001
            if is_likely_bug(exc):
                raise
            return []

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
        limit = self._config.max_discussion_comment_chars
        if len(raw) <= limit:
            return raw
        return raw[:limit] + f"\n[Comment truncated from {len(raw):,} chars]"

    def _build_tdd_subagent_plan(
        self,
        plan_comment: str,
        bead_mapping: dict[str, str] | None = None,
    ) -> str:
        """Build a Task Graph plan that instructs the agent to use sub-agents.

        Parses phases from the plan, topologically sorts them, and builds
        concrete per-phase RED/GREEN/REFACTOR sub-agent instructions with
        the actual files, tests, and dependency info from each phase.

        When *bead_mapping* is provided, injects ``bd`` claim/close
        lifecycle commands into each phase.
        """
        phases = topological_sort(extract_phases(plan_comment))
        max_fix = self._config.tdd_max_remediation_loops

        header = (
            "\n\n## Implementation Plan — TDD Sub-Agent Isolation\n\n"
            "This plan uses a **Task Graph**. For each phase below, launch "
            "**three sub-agents** using the **Agent tool** in strict sequence.\n\n"
        )

        rules = (
            "### Rules\n\n"
            "- Complete each phase fully (RED \u2192 GREEN \u2192 REFACTOR) before "
            "starting the next\n"
            "- Each sub-agent runs in the same worktree and sees prior commits\n"
            "- If a sub-agent fails, report the failure with details \u2014 do NOT "
            "retry silently\n"
            f"- REFACTOR sub-agent may attempt up to **{max_fix}** fix cycles "
            "before reporting failure\n\n"
        )

        phase_sections: list[str] = []
        for i, phase in enumerate(phases, 1):
            files_str = ", ".join(f"`{f}`" for f in phase.files) or "(none listed)"
            tests_str = (
                "\n".join(f"  - {t}" for t in phase.tests) or "  - (none listed)"
            )
            deps_str = ", ".join(phase.depends_on) or "none"

            # Bead lifecycle instructions
            bead_id = (bead_mapping or {}).get(phase.id)
            bead_header = ""
            bead_claim = ""
            bead_close = ""
            if bead_id:
                bead_header = f"**Bead:** #{bead_id}\n"
                bead_claim = f"\n> First run: `bd update {bead_id} --claim`\n"
                bead_close = (
                    f"\n> After all tests pass, run: "
                    f'`bd close {bead_id} --reason "Phase complete"`\n'
                )

            phase_sections.append(
                f"### Phase {i}: {phase.name}\n\n"
                f"{bead_header}"
                f"**Files:** {files_str}  \n"
                f"**Depends on:** {deps_str}\n\n"
                f"**1. RED sub-agent** \u2014 Launch with prompt:\n"
                f"{bead_claim}"
                f'> "Write FAILING tests for {phase.name}. '
                f"Test these behavioral specs:\n{tests_str}\n"
                f"ONLY create/modify files in `tests/`. Do NOT touch source files. "
                f'Commit when done."\n\n'
                f"**2. GREEN sub-agent** \u2014 Launch with prompt:\n"
                f'> "Implement the MINIMUM code to make all failing tests pass '
                f"for {phase.name}. Modify these files: {files_str}. "
                f"ONLY change source/implementation files (NOT test files). "
                f'Commit when done."\n\n'
                f"**3. REFACTOR sub-agent** \u2014 Launch with prompt:\n"
                f'> "Run `make test`. If tests fail, fix implementation code '
                f"(not tests). Repeat until the full suite passes (max "
                f'{max_fix} attempts). Commit fixes."\n'
                f"{bead_close}\n"
            )

        # If parsing found no phases, include the raw plan as fallback
        if not phase_sections:
            return (
                "\n\n## Implementation Plan\n\n"
                "Follow this plan closely. It uses a **Task Graph** with "
                "ordered phases.\n"
                "Execute phases in order (P1 before P2, etc.). For each phase:\n"
                "1. Write tests that encode the behavioral specs listed.\n"
                "2. Run tests \u2014 they should FAIL.\n"
                "3. Implement the minimum code to make tests pass.\n"
                "4. Run the full test suite before moving to the next phase.\n\n"
                f"{plan_comment}"
            )

        return header + rules + "\n".join(phase_sections)

    async def _build_prompt_with_stats(
        self,
        issue: Task,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Build the implementation prompt and pruning stats."""
        builder = PromptBuilder()
        plan_comment, other_comments = self._extract_plan_comment(issue.comments)
        raw_plan = plan_comment

        # Fallback to saved plan file
        if not plan_comment:
            plan_comment = self._load_plan_fallback(issue.id)
            raw_plan = plan_comment
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
                max_chars=self._config.max_impl_plan_chars,
                label="Implementation plan",
            )
            builder.record_history("Implementation plan", raw_plan, plan_comment)
            # Detect whether the plan uses Task Graph format
            if has_task_graph(plan_comment):
                plan_section = self._build_tdd_subagent_plan(
                    plan_comment, bead_mapping=bead_mapping
                )
            else:
                plan_section = (
                    f"\n\n## Implementation Plan\n\n"
                    f"Follow this plan closely. It was created by a planner agent "
                    f"that already analyzed the codebase.\n\n"
                    f"{plan_comment}"
                )

        review_feedback_section = ""
        if review_feedback:
            raw_review_feedback = review_feedback
            review_feedback = self._summarize_for_prompt(
                review_feedback,
                max_chars=self._config.max_review_feedback_chars,
                label="Review feedback",
            )
            builder.record_history(
                "Review feedback", raw_review_feedback, review_feedback
            )
            review_feedback_section = (
                f"\n\n## Review Feedback\n\n"
                f"A reviewer rejected the previous implementation. "
                f"Address all feedback below:\n\n"
                f"{review_feedback}"
            )

        prior_failure_section = ""
        if prior_failure:
            raw_prior_failure = prior_failure
            prior_failure = self._summarize_for_prompt(
                prior_failure,
                max_chars=self._config.error_output_max_chars,
                label="Prior failure",
            )
            builder.record_history("Prior failure", raw_prior_failure, prior_failure)
            prior_failure_section = (
                f"\n\n## Prior Attempt Failure\n\n"
                f"Your previous implementation attempt failed with the following error. "
                f"Avoid repeating the same mistake:\n\n"
                f"```\n{prior_failure}\n```"
            )

        comments_section = ""
        if other_comments:
            max_comments = 6
            selected_comments = other_comments[:max_comments]
            compact_comments = [
                self._truncate_comment_for_prompt(c) for c in selected_comments
            ]
            formatted = "\n".join(f"- {c}" for c in compact_comments)
            builder.record_history("Discussion", "".join(other_comments), formatted)
            comments_section = f"\n\n## Discussion\n{formatted}"
            if len(other_comments) > max_comments:
                comments_section += f"\n- ... ({len(other_comments) - max_comments} more comments omitted)"

        raw_feedback_section = self._get_review_feedback_section()
        feedback_section = ""
        if raw_feedback_section:
            compact_feedback = self._summarize_for_prompt(
                raw_feedback_section,
                max_chars=self._config.max_common_feedback_chars,
                label="Common review feedback",
            )
            builder.record_history(
                "Common review feedback", raw_feedback_section, compact_feedback
            )
            feedback_section = compact_feedback

        escalations = self._get_escalation_data()
        escalation_section = ""
        if escalations:
            blocks = [str(e["mandatory_block"]) for e in escalations]
            escalation_section = "\n\n" + "\n\n".join(blocks)
            builder.record_history(
                "Escalations", escalation_section, escalation_section
            )

        memory_section = await self._inject_memory(
            query_context=f"{issue.title}\n{(issue.body or '')[:200]}",
        )

        # Runtime log injection
        log_section = ""
        from log_context import load_runtime_logs  # noqa: PLC0415

        logs = load_runtime_logs(self._config)
        if logs:
            log_section = f"\n\n## Recent Application Logs\n\n```\n{logs}\n```"

        # Truncate issue body if too long
        body = issue.body
        max_body = self._config.max_issue_body_chars
        if len(body) > max_body:
            body = (
                body[:max_body]
                + f"\n\n[Body truncated at {max_body:,} chars — see full issue on GitHub]"
            )
        builder.record_context("Issue body", issue.body, body)

        # --- Cross-section paragraph dedup ---
        from prompt_dedup import PromptDeduplicator  # noqa: PLC0415

        section_deduper = PromptDeduplicator()
        deduped, section_chars_saved = section_deduper.dedup_sections(
            ("Issue body", body),
            ("Implementation plan", plan_section),
            ("Review feedback", review_feedback_section),
            ("Prior failure", prior_failure_section),
            ("Discussion", comments_section),
            ("Memory", memory_section),
        )
        dedup_map = dict(deduped)
        body = dedup_map["Issue body"]
        plan_section = dedup_map["Implementation plan"]
        review_feedback_section = dedup_map["Review feedback"]
        prior_failure_section = dedup_map["Prior failure"]
        comments_section = dedup_map["Discussion"]
        memory_section = dedup_map["Memory"]

        if section_chars_saved:
            self._last_context_stats["section_dedup_chars_saved"] = section_chars_saved

        test_cmd = self._config.test_command  # noqa: F841 — used in f-string prompt
        tools_section = format_tools_for_prompt(discover_tools(self._config.repo_root))
        skills_section = format_skills_for_prompt(get_skills())
        plugin_skills_section = format_plugin_skills_for_prompt(
            skills_for_phase(
                "agent",
                discover_plugin_skills(self._config.required_plugins),
                self._config.phase_skills,
            )
        )

        prompt = f"""You are implementing GitHub issue #{issue.id}.

## Issue: {issue.title}

{body}{plan_section}{review_feedback_section}{prior_failure_section}{comments_section}{memory_section}{log_section}

## Instructions — Test-Driven Development

Follow TDD discipline: **tests first, then implementation**.

1. Understand the issue and relevant code paths.
2. **Plan tests** — list the tests you will write covering zero/empty, one, many,
   boundary, interface, and exception cases (ZOMBIES heuristic).
3. **RED** — Write one failing test. Predict the failure, run the test suite, confirm it fails.
4. **GREEN** — Write the minimal code to make the test pass. No more.
5. **Simplify** — For each line you added, ask: "Does a failing test require this?"
   Remove anything not demanded by a test. Re-run tests after each removal.
6. **Refactor** — Improve expressiveness and clarity while keeping tests green.
7. Repeat steps 3-6 for each planned test.
8. Run the available tools at their checkpoints (see below).
9. Fix any issues found before proceeding.
10. Commit with: "Fixes #{issue.id}: <concise summary>"

Key rules:
- Write only one test at a time. See it fail before writing implementation.
- Run **all** tests every cycle, not just the new one.
- Never write implementation code that no test requires.

{tools_section}

{skills_section}
{feedback_section}{escalation_section}
{self._build_self_check_checklist(escalations)}
{self._build_requirements_gap_section(issue)}
## UI Guidelines

- Before creating UI components, search `src/ui/src/components/` for existing patterns to reuse.
- Import constants, types, and shared styles from centralized modules (e.g. `src/ui/src/constants.js`, `src/ui/src/theme.js`) — never duplicate.
- Apply responsive design: set `minWidth` on layout containers, use `flexShrink: 0` on fixed-width panels.
- Match existing spacing (4px grid), colors (CSS variables from `theme.js`), and component conventions.

## Rules

- Follow the project's CLAUDE.md guidelines strictly.
- NEVER delete or overwrite existing CLAUDE.md content. You may append new sections or
  modify existing sections, but you must preserve all information already present.
- Tests are mandatory — follow the TDD process above. Run tests with: `{test_cmd}`
- Do NOT push to remote. Do NOT create pull requests.
- Do NOT run `git push` or `gh pr create`.
- Run `make quality-lite` (lint + typecheck + security, no tests) as a sense check.
  CI runs the full test suite — you do not need to run `make quality` or `make test`.
- ALWAYS commit your work with `git add <file>` and `git commit`.
  The system runs its own quality gate after you finish — your job is to produce commits.
- NEVER use interactive git commands (`git add -i`, `git add -p`, `git rebase -i`).
  There is no TTY — interactive commands will hang. Use `git add <file>` or `git add -A`.
- NEVER conclude that the issue is "already satisfied" or that no work is needed.
  The planner already verified this issue requires implementation. Your job is to
  write the code, not to second-guess the plan. Always produce commits.
- Do NOT bundle unrelated refactoring with the assigned fix. For example, do not
  migrate raw model constructors to factories, rename variables, or reformat code
  in files you are not otherwise changing for the issue. Each concern is a separate PR.

{MEMORY_SUGGESTION_PROMPT.format(context="implementation")}"""
        if plugin_skills_section:
            prompt = f"{prompt}\n\n{plugin_skills_section}"
        return prompt, builder.build_stats()

    # ------------------------------------------------------------------
    # CLAUDE.md integrity guard
    # ------------------------------------------------------------------

    @staticmethod
    def _snapshot_claude_md(worktree_path: Path) -> str | None:
        """Return the full text of CLAUDE.md before the agent runs, or None if absent."""
        claude_md = worktree_path / "CLAUDE.md"
        if claude_md.is_file():
            try:
                return claude_md.read_text()
            except OSError:
                return None
        return None

    @staticmethod
    def _guard_claude_md(
        worktree_path: Path,
        snapshot: str | None,
        issue_id: int,
    ) -> None:
        """Restore CLAUDE.md if the agent deleted it or removed content.

        Compares the current file against the pre-agent *snapshot*.
        If content was lost (file deleted, or line count shrank), the
        original is restored and a warning is logged.
        """
        if snapshot is None:
            return  # no CLAUDE.md existed before — nothing to protect

        claude_md = worktree_path / "CLAUDE.md"

        # Case 1: file was deleted entirely
        if not claude_md.is_file():
            logger.warning(
                "Issue #%d: agent deleted CLAUDE.md — restoring original",
                issue_id,
            )
            claude_md.write_text(snapshot)
            return

        # Case 2: content was shrunk (overwrite / truncation)
        try:
            current = claude_md.read_text()
        except OSError:
            claude_md.write_text(snapshot)
            return

        original_lines = snapshot.count("\n")
        current_lines = current.count("\n")
        if original_lines > 0 and current_lines < original_lines:
            logger.warning(
                "Issue #%d: agent shrank CLAUDE.md from %d to %d lines — restoring original",
                issue_id,
                original_lines,
                current_lines,
            )
            claude_md.write_text(snapshot)

    async def _verify_result(self, worktree_path: Path, branch: str) -> LoopResult:
        """Check that the agent produced commits and ``make quality`` passes.

        Returns a :class:`LoopResult`.  On failure the summary contains
        the last 3000 characters of combined stdout/stderr.
        """
        # Check for commits on the branch
        commit_count = await self._count_commits(worktree_path, branch)
        if commit_count == 0:
            return LoopResult(passed=False, summary="No commits found on branch")

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
4. Run `make quality-lite` to verify your fixes pass lint, typecheck, and security.
5. Commit your fixes with message: "quality-fix: <description> (#{issue.id})"

Focus on fixing the root causes, not suppressing warnings.
"""

    def _build_pre_quality_review_prompt(self, issue: Task, attempt: int) -> str:
        """Build the pre-quality review/correction skill prompt."""
        escalations = self._get_escalation_data()
        escalation_guidance = ""
        if escalations:
            guidance_parts = [str(e["pre_quality_guidance"]) for e in escalations]
            escalation_guidance = (
                "\n\nEscalated Requirements (from recurring review feedback):\n"
                + "\n".join(f"- {g}" for g in guidance_parts)
            )

        return f"""You are running the Pre-Quality Review Skill for issue #{issue.id}: {issue.title}.

Attempt: {attempt}

Review the current branch changes thoroughly for bugs, gaps, and test coverage.

Bug check:
- look for logic errors, off-by-one mistakes, wrong comparisons, swapped arguments
- check None/null handling: are optional values dereferenced without guards?
- verify error paths: do exceptions propagate correctly? are resources cleaned up?
- check concurrency issues: race conditions, missing awaits, unprotected shared state

Gap check:
- compare implementation against the plan/issue description — is anything missing?
- check edge cases: empty inputs, None values, missing keys, boundary conditions
- verify all new functions have type hints and all imports are correct
- ensure no debug code, print statements, or hardcoded test values remain
{self._build_spec_match_check(issue)}

Test coverage check:
- every new public function/method must have at least one test
- verify tests cover both success and failure/error paths
- check that edge cases (empty, None, boundary) have dedicated tests
- ensure tests actually assert on behavior, not just that code runs without error
- add missing tests directly in this working tree

Apply fixes:
- fix any bugs, gaps, or missing tests found above directly in this working tree
- keep edits scoped to issue intent{escalation_guidance}

Constraints:
- Do not push or open PRs
- Prefer minimal safe changes
- Keep edits scoped to issue intent — do not refactor, migrate, or rename code that is unrelated to the fix

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
3. `make quality-lite`

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
    def _parse_skill_result(transcript: str, marker: str) -> LoopResult:
        """Parse a skill result marker line from transcript text.

        Returns a :class:`LoopResult`. Missing marker defaults to OK to preserve
        backward compatibility with older prompts/tools.
        """
        pattern = rf"{re.escape(marker)}:\s*(OK|RETRY)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if not match:
            return LoopResult(passed=True, summary="No explicit result marker")
        status = match.group(1).upper()
        summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else ""
        return LoopResult(passed=status == "OK", summary=summary)

    async def _run_pre_quality_review_loop(
        self,
        issue: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int,
    ) -> LoopResult:
        """Run mandatory pre-quality review + run-tool skills before verification."""
        commits = await self._count_commits(worktree_path, branch)
        max_attempts = self._config.max_pre_quality_review_attempts
        if commits == 0 or max_attempts <= 0:
            return LoopResult(
                passed=True, summary="Skipped pre-quality review", attempts=0
            )

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
            await self._force_commit_uncommitted(issue, worktree_path)
            review_result = self._parse_skill_result(
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
            await self._force_commit_uncommitted(issue, worktree_path)
            run_tool_result = self._parse_skill_result(
                run_tool_transcript, "RUN_TOOL_RESULT"
            )

            if review_result.passed and run_tool_result.passed:
                return LoopResult(passed=True, summary="OK", attempts=attempt)

            last_summary = "; ".join(
                s for s in [review_result.summary, run_tool_result.summary] if s
            ).strip()
            if attempt == max_attempts:
                return LoopResult(
                    passed=False,
                    summary="Pre-quality review loop exhausted"
                    + (f": {last_summary}" if last_summary else ""),
                    attempts=attempt,
                )

        return LoopResult(
            passed=False,
            summary="Pre-quality review loop failed",
            attempts=max_attempts,
        )

    async def _get_branch_diff(self, worktree_path: Path, branch: str) -> str:
        """Return the combined diff of *branch* against the base branch."""
        try:
            result = await self._runner.run_simple(
                [
                    "git",
                    "diff",
                    f"origin/{self._config.base_branch()}...{branch}",
                ],
                cwd=str(worktree_path),
                timeout=self._config.git_command_timeout,
            )
            return result.stdout or ""
        except (TimeoutError, FileNotFoundError):
            return ""

    async def _run_skill(
        self,
        skill: AgentSkill,
        issue: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int,
        plan_text: str = "",
    ) -> LoopResult:
        """Run a registered post-implementation skill via the skill registry.

        Gets max_attempts from config via ``skill.config_key``.
        Returns a :class:`LoopResult`.
        """
        max_attempts = getattr(self._config, skill.config_key, 0)
        if max_attempts <= 0:
            return LoopResult(passed=True, summary=f"{skill.name} disabled")

        commits = await self._count_commits(worktree_path, branch)
        if commits == 0:
            return LoopResult(passed=True, summary="No commits to check")

        diff = await self._get_branch_diff(worktree_path, branch)
        if not diff.strip():
            return LoopResult(passed=True, summary="Empty diff")

        max_diff = self._config.max_review_diff_chars
        if len(diff) > max_diff:
            diff = diff[:max_diff] + f"\n[Diff truncated at {max_diff:,} chars]"

        prompt = skill.prompt_builder(
            issue_number=issue.id,
            issue_title=issue.title,
            diff=diff,
            plan_text=plan_text,
        )
        if not prompt.strip():
            return LoopResult(passed=True, summary=f"{skill.name}: no input data")

        cmd = self._build_pre_quality_review_command()
        summary = ""
        skill_started = time.monotonic()

        # Each iteration's _execute call allocates its own subprocess_idx
        # from BaseRunner's monotonic counter, so retries and back-to-back
        # skills never overwrite each other's subprocess-N.json files.
        for attempt in range(1, max_attempts + 1):
            transcript = await self._execute(
                cmd,
                prompt,
                worktree_path,
                {"issue": issue.id, "source": "implementer"},
            )
            passed, summary, findings = skill.result_parser(transcript)
            if passed:
                result = LoopResult(passed=True, summary=summary, attempts=attempt)
                break
            if findings:
                logger.info(
                    "%s findings for #%d: %s",
                    skill.name,
                    issue.id,
                    "; ".join(findings[:5]),
                )
        else:
            result = LoopResult(passed=False, summary=summary, attempts=max_attempts)

        # Append the skill result to run-N/skill_results.json alongside
        # the parent run. This is the source of truth for skill-effectiveness
        # scoring in trace_rollup.
        ctx = self._tracing_ctx
        if ctx is not None:
            self._append_skill_result(
                ctx,
                skill_name=skill.name,
                passed=result.passed,
                attempts=result.attempts,
                duration_seconds=time.monotonic() - skill_started,
                blocking=skill.blocking,
            )

        return result

    def _append_skill_result(
        self,
        ctx: TracingContext,
        *,
        skill_name: str,
        passed: bool,
        attempts: int,
        duration_seconds: float,
        blocking: bool,
    ) -> None:
        """Append a skill result to <run-N>/skill_results.json.

        Never raises — tracing must not crash the agent run.
        """
        try:
            import json as _json  # noqa: PLC0415

            from file_util import atomic_write  # noqa: PLC0415

            run_dir = (
                self._config.data_root
                / "traces"
                / str(ctx.issue_number)
                / ctx.phase
                / f"run-{ctx.run_id}"
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            results_path = run_dir / "skill_results.json"
            existing: list[dict[str, Any]] = []
            if results_path.exists():
                try:
                    existing = _json.loads(results_path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    existing = []
            existing.append(
                {
                    "skill_name": skill_name,
                    "passed": passed,
                    "attempts": attempts,
                    "duration_seconds": round(duration_seconds, 3),
                    "blocking": blocking,
                }
            )
            atomic_write(results_path, _json.dumps(existing, indent=2))
        except Exception:
            logger.warning(
                "Failed to append skill result for %s", skill_name, exc_info=True
            )

    async def _run_quality_fix_loop(
        self,
        issue: Task,
        worktree_path: Path,
        branch: str,
        error_output: str,
        worker_id: int,
    ) -> LoopResult:
        """Retry loop: invoke Claude to fix quality failures.

        Returns a :class:`LoopResult` with ``attempts`` set to the number
        of fix iterations performed.
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
            await self._force_commit_uncommitted(issue, worktree_path)

            verify = await self._verify_result(worktree_path, branch)
            if verify.passed:
                return LoopResult(passed=True, summary="OK", attempts=attempt)

            last_error = verify.summary

        return LoopResult(passed=False, summary=last_error, attempts=max_attempts)

    async def _force_commit_uncommitted(self, task: Task, worktree_path: Path) -> bool:
        """Stage and commit any uncommitted changes the agent left behind.

        Always runs on the **host** (not inside Docker) since the workspace
        is bind-mounted — file edits from the container are already on disk.

        Returns ``True`` if a salvage commit was created, ``False`` otherwise.
        """
        from execution import get_default_runner

        host = get_default_runner()
        timeout = self._config.git_command_timeout
        cwd = str(worktree_path)

        try:
            status = await host.run_simple(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                timeout=timeout,
            )
            if not status.stdout.strip():
                return False

            logger.warning(
                "Issue #%d: agent left uncommitted changes — force-committing",
                task.id,
            )
            add_result = await host.run_simple(
                ["git", "add", "-A"],
                cwd=cwd,
                timeout=timeout,
            )
            if add_result.returncode != 0:
                logger.warning(
                    "Issue #%d: git add failed (rc=%d): %s",
                    task.id,
                    add_result.returncode,
                    add_result.stderr,
                )
                return False
            commit_result = await host.run_simple(
                [
                    "git",
                    "commit",
                    "-m",
                    f"Fixes #{task.id}: {task.title}\n\n"
                    "Auto-committed by HydraFlow (agent did not commit)",
                ],
                cwd=cwd,
                timeout=timeout,
            )
            if commit_result.returncode != 0:
                logger.warning(
                    "Issue #%d: git commit failed (rc=%d): %s",
                    task.id,
                    commit_result.returncode,
                    commit_result.stderr,
                )
                return False
            logger.info(
                "Issue #%d: salvage commit created for uncommitted work",
                task.id,
            )
            return True
        except (TimeoutError, FileNotFoundError, OSError) as exc:
            logger.warning(
                "Issue #%d: force-commit failed: %s",
                task.id,
                exc,
            )
            return False

    async def _count_commits(self, worktree_path: Path, branch: str) -> int:
        """Count commits on *branch* ahead of the base branch."""
        try:
            result = await self._runner.run_simple(
                [
                    "git",
                    "rev-list",
                    "--count",
                    f"origin/{self._config.base_branch()}..{branch}",
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
        payload: WorkerUpdatePayload = {
            "issue": issue_number,
            "worker": worker_id,
            "status": status.value,
            "role": "implementer",
        }
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                data=payload,
            )
        )
