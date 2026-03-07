"""Implementation batch processing for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from agent import AgentRunner
from config import HydraFlowConfig
from harness_insights import FailureCategory, HarnessInsightStore
from issue_store import IssueStore
from models import GitHubIssue, PipelineStage, Task, WorkerResult, WorkerResultMeta
from phase_utils import (
    escalate_to_hitl,
    is_adr_issue_title,
    record_harness_failure,
    release_batch_in_flight,
    run_refilling_pool,
    safe_file_memory_suggestion,
    store_lifecycle,
)
from pr_manager import PRManager
from run_recorder import RunRecorder
from state import StateTracker
from subprocess_util import AuthenticationError, CreditExhaustedError
from task_source import TaskTransitioner
from worktree import WorktreeManager

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementPhase:
    """Fetches ready issues and runs implementation agents concurrently."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        worktrees: WorktreeManager,
        agents: AgentRunner,
        prs: PRManager,
        store: IssueStore,
        stop_event: asyncio.Event,
        run_recorder: RunRecorder | None = None,
        harness_insights: HarnessInsightStore | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._worktrees = worktrees
        self._agents = agents
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._store = store
        self._stop_event = stop_event
        self._run_recorder = run_recorder
        self._harness_insights = harness_insights
        self._active_issues: set[int] = set()
        self._active_issues_lock = asyncio.Lock()

    def _hitl_cause(self, issue: Task, reason: str) -> str:
        """Build a HITL cause string, prefixing with epic context if applicable."""
        epic_child_labels = {lbl.lower() for lbl in self._config.epic_child_label}
        issue_labels = {t.lower() for t in issue.tags}
        if not (epic_child_labels & issue_labels):
            return reason
        # Try to find parent epic number from issue body
        match = re.search(r"[Pp]arent\s+[Ee]pic[:\s#]*(\d+)", issue.body)
        if match:
            return f"Epic child (#{match.group(1)}): {reason}"
        return f"Epic child: {reason}"

    async def run_batch(
        self,
        issues: list[Task] | None = None,
    ) -> tuple[list[WorkerResult], list[Task]]:
        """Run implementation agents concurrently using a slot-filling pool.

        If *issues* is ``None``, pulls from the ``IssueStore`` ready queue
        continuously as slots free up.  If a fixed list is provided,
        processes those items then returns.
        """
        if issues is not None:
            # Fixed list mode — process exactly these issues
            items_iter = iter(issues)
            exhausted = False

            def _supply_fixed() -> list[Task]:
                nonlocal exhausted
                if exhausted:
                    return []
                item = next(items_iter, None)
                if item is None:
                    exhausted = True
                    return []
                return [item]
        else:
            issues = []

            def _supply_fixed() -> list[Task]:
                batch = self._store.get_implementable(1)
                issues.extend(batch)
                return batch

        async def _worker(idx: int, issue: Task) -> WorkerResult:
            if self._stop_event.is_set():
                return WorkerResult(
                    issue_number=issue.id,
                    branch=f"agent/issue-{issue.id}",
                    error="stopped",
                )

            branch = f"agent/issue-{issue.id}"
            async with self._active_issues_lock:
                self._active_issues.add(issue.id)
                self._state.set_active_issue_numbers(list(self._active_issues))
            async with store_lifecycle(self._store, issue.id, "implement"):
                self._state.mark_issue(issue.id, "in_progress")
                self._state.set_branch(issue.id, branch)

                try:
                    return await self._worker_inner(idx, issue, branch)
                except (AuthenticationError, CreditExhaustedError, MemoryError):
                    raise
                except Exception:
                    logger.exception("Worker failed for issue #%d", issue.id)
                    self._state.mark_issue(issue.id, "failed")
                    record_harness_failure(
                        self._harness_insights,
                        issue.id,
                        FailureCategory.IMPLEMENTATION_ERROR,
                        f"Worker exception for issue #{issue.id}",
                        stage=PipelineStage.IMPLEMENT,
                    )
                    return WorkerResult(
                        issue_number=issue.id,
                        branch=branch,
                        error=f"Worker exception for issue #{issue.id}",
                    )
                finally:
                    async with self._active_issues_lock:
                        self._active_issues.discard(issue.id)
                        self._state.set_active_issue_numbers(list(self._active_issues))
                    release_batch_in_flight(self._store, {issue.id})

        all_results = await run_refilling_pool(
            supply_fn=_supply_fixed,
            worker_fn=_worker,
            max_concurrent=self._config.max_workers,
            stop_event=self._stop_event,
        )
        return all_results, issues

    async def _worker_inner(self, idx: int, issue: Task, branch: str) -> WorkerResult:
        """Core implementation logic — called inside the semaphore."""
        self._prepare_adr_plan(issue)
        cap_result = await self._check_attempt_cap(issue, branch)
        if cap_result is not None:
            return cap_result

        # Start recording if a run recorder is available
        ctx = None
        if self._run_recorder is not None:
            try:
                ctx = self._run_recorder.start(issue.id)
                plan_text = self._read_plan_for_recording(issue.id)
                if plan_text:
                    ctx.save_plan(plan_text)
                ctx.save_config(self._config.model_dump(mode="json"))
            except Exception:
                logger.debug("Run recording setup failed", exc_info=True)
                ctx = None

        review_feedback = self._state.get_review_feedback(issue.id) or ""
        result = await self._run_implementation(issue, branch, idx, review_feedback)

        # Finalize the recording
        if ctx is not None:
            try:
                if result.transcript:
                    for line in result.transcript.splitlines():
                        ctx.append_transcript(line)
                outcome = "success" if result.success else "failed"
                ctx.finalize(outcome, error=result.error)
            except Exception:
                logger.debug("Run recording finalize failed", exc_info=True)

        is_retry = bool(review_feedback)
        return await self._handle_implementation_result(issue, result, is_retry)

    def _read_plan_for_recording(self, issue_number: int) -> str:
        """Read the plan file for *issue_number*, returning empty string on failure."""
        plan_path = self._config.plans_dir / f"issue-{issue_number}.md"
        try:
            return plan_path.read_text()
        except OSError:
            return ""

    def _build_cap_exceeded_comment(self, attempts: int, last_error: str) -> str:
        """Build the human-readable comment explaining why the cap was exceeded."""
        return (
            f"**Implementation attempt cap exceeded** — "
            f"{attempts - 1} attempt(s) exhausted "
            f"(max {self._config.max_issue_attempts}).\n\n"
            f"Last error: {last_error}\n\n"
            f"Escalating to human review."
        )

    async def _escalate_capped_issue(
        self, issue: Task, attempts: int, last_error: str
    ) -> None:
        """Post the cap comment, escalate to HITL, record harness failure."""
        comment = self._build_cap_exceeded_comment(attempts, last_error)
        await self._transitioner.post_comment(issue.id, comment)
        await escalate_to_hitl(
            self._state,
            self._prs,
            issue.id,
            cause=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s)",
            origin_label=self._config.ready_label[0],
            hitl_label=self._config.hitl_label[0],
        )
        self._store.enqueue_transition(issue, "hitl")
        record_harness_failure(
            self._harness_insights,
            issue.id,
            FailureCategory.HITL_ESCALATION,
            f"Implementation attempt cap exceeded after {attempts - 1} attempt(s): {last_error}",
            stage=PipelineStage.IMPLEMENT,
        )

    async def _check_attempt_cap(self, issue: Task, branch: str) -> WorkerResult | None:
        """Check per-issue attempt cap.  Returns a WorkerResult on cap exceeded, else None."""
        attempts = self._state.increment_issue_attempts(issue.id)
        if attempts <= self._config.max_issue_attempts:
            return None

        last_meta = self._state.get_worker_result_meta(issue.id)
        last_error = (
            last_meta.get("error", "No error details available")
            or "No error details available"
        )
        await self._escalate_capped_issue(issue, attempts, last_error)
        self._state.mark_issue(issue.id, "failed")
        return WorkerResult(
            issue_number=issue.id,
            branch=branch,
            error=f"Implementation attempt cap exceeded ({attempts - 1} attempts)",
        )

    async def _setup_worktree_and_branch(self, issue: Task, branch: str) -> Path:
        """Ensure worktree exists/resumed and branch is pushed."""
        wt_path = self._config.worktree_path_for_issue(issue.id)
        if wt_path.is_dir():
            logger.info("Resuming existing worktree for issue #%d", issue.id)
        else:
            wt_path = await self._worktrees.create(issue.id, branch)
        self._state.set_worktree(issue.id, str(wt_path))
        await self._prs.push_branch(wt_path, branch)
        await self._transitioner.post_comment(
            issue.id,
            f"**Branch:** [`{branch}`](https://github.com/"
            f"{self._config.repo}/tree/{branch})\n\n"
            f"Implementation in progress.",
        )
        return wt_path

    async def _record_impl_metrics(
        self, issue: Task, result: WorkerResult, review_feedback: str
    ) -> None:
        """Record quality-fix-attempt, duration, harness metrics to state/store."""
        if review_feedback:
            self._state.clear_review_feedback(issue.id)
        if result.duration_seconds > 0:
            self._state.record_implementation_duration(result.duration_seconds)
        if result.quality_fix_attempts > 0:
            self._state.record_quality_fix_rounds(result.quality_fix_attempts)
            for _ in range(result.quality_fix_attempts):
                self._state.record_stage_retry(issue.id, "quality_fix")
            record_harness_failure(
                self._harness_insights,
                issue.id,
                FailureCategory.QUALITY_GATE,
                f"Quality fix needed: {result.quality_fix_attempts} round(s). "
                f"Error: {result.error or 'none'}",
                stage=PipelineStage.IMPLEMENT,
            )
        meta: WorkerResultMeta = {
            "quality_fix_attempts": result.quality_fix_attempts,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
            "commits": result.commits,
        }
        self._state.set_worker_result_meta(issue.id, meta)

    async def _run_implementation(
        self,
        issue: Task,
        branch: str,
        worker_id: int,
        review_feedback: str,
    ) -> WorkerResult:
        """Set up worktree, push branch, run agent, record metrics."""
        wt_path = await self._setup_worktree_and_branch(issue, branch)

        result = await self._agents.run(
            issue,
            wt_path,
            branch,
            worker_id=worker_id,
            review_feedback=review_feedback,
        )

        await self._record_impl_metrics(issue, result, review_feedback)

        return result

    async def _handle_implementation_result(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> WorkerResult:
        """Handle the result of an agent run: close, create PR, swap labels."""
        # Zero-commit: treat as implementation failure, not "already satisfied".
        # The agent may have failed to understand the issue or hallucinated
        # that no work was needed — escalate for human review.
        if (
            not result.success
            and result.error == "No commits found on branch"
            and result.commits == 0
        ):
            logger.warning(
                "Issue #%d: zero commits after implementation — escalating as failure",
                issue.id,
            )
            await self._transitioner.post_comment(
                issue.id,
                "## Implementation Failed — Zero Commits\n\n"
                "The implementation agent ran but produced no commits. "
                "This likely means the agent incorrectly concluded no work "
                "was needed, or encountered an error preventing commits.\n\n"
                "Escalating for human review.\n\n"
                "---\n"
                "*Generated by HydraFlow Implementer*",
            )
            self._state.mark_issue(issue.id, "failed")
            await escalate_to_hitl(
                self._state,
                self._prs,
                issue.id,
                cause=self._hitl_cause(issue, "implementation produced zero commits"),
                origin_label=self._config.ready_label[0],
                hitl_label=self._config.hitl_label[0],
            )
            self._store.enqueue_transition(issue, "hitl")
            if result.transcript:
                await safe_file_memory_suggestion(
                    result.transcript,
                    "implement_zero_commits",
                    f"issue #{issue.id}",
                    self._config,
                    self._prs,
                    self._state,
                )
            return result

        # Push final commits and create PR
        if result.worktree_path:
            pushed = await self._prs.push_branch(
                Path(result.worktree_path), result.branch
            )
            if pushed:
                pr = None
                if not is_retry:
                    draft = not result.success
                    gh_issue = GitHubIssue.from_task(issue)
                    pr = await self._prs.create_pr(gh_issue, result.branch, draft=draft)
                    result.pr_info = pr
                else:
                    pr = await self._prs.find_open_pr_for_branch(
                        result.branch, issue_number=issue.id
                    )
                    result.pr_info = pr

                if result.success and (pr is None or pr.number <= 0):
                    has_diff = await self._prs.branch_has_diff_from_main(result.branch)
                    if not has_diff:
                        logger.warning(
                            "Issue #%d: agent claimed success but branch has no diff — escalating as failure",
                            issue.id,
                        )
                        await self._transitioner.post_comment(
                            issue.id,
                            "## Implementation Failed — No Changes Detected\n\n"
                            "The implementation agent reported success but the branch "
                            "has no diff from main. The agent likely concluded no work "
                            "was needed incorrectly.\n\n"
                            "Escalating for human review.\n\n"
                            "---\n"
                            "*Generated by HydraFlow Implementer*",
                        )
                        self._state.mark_issue(issue.id, "failed")
                        await escalate_to_hitl(
                            self._state,
                            self._prs,
                            issue.id,
                            cause=self._hitl_cause(
                                issue, "implementation produced no changes (zero diff)"
                            ),
                            origin_label=self._config.ready_label[0],
                            hitl_label=self._config.hitl_label[0],
                        )
                        self._store.enqueue_transition(issue, "hitl")
                        if result.transcript:
                            await safe_file_memory_suggestion(
                                result.transcript,
                                "implement_zero_diff",
                                f"issue #{issue.id}",
                                self._config,
                                self._prs,
                                self._state,
                            )
                        return result
                    logger.warning(
                        "Implementation succeeded for issue #%d but no open PR exists for branch %s",
                        issue.id,
                        result.branch,
                    )
                    await self._transitioner.post_comment(
                        issue.id,
                        "PR creation/recovery failed after successful implementation. "
                        "Keeping issue in ready queue for retry.",
                    )
                    self._state.mark_issue(issue.id, "failed")
                    result.success = False
                    if not result.error:
                        result.error = "PR creation failed"
                    return result

                if result.success:
                    await self._transitioner.transition(
                        issue.id,
                        "review",
                        pr_number=pr.number if pr and pr.number > 0 else None,
                    )
                    self._store.enqueue_transition(issue, "review")
                    self._state.increment_session_counter("implemented")

        status = "success" if result.success else "failed"
        self._state.mark_issue(issue.id, status)
        return result

    def _record_harness_failure(
        self,
        issue_number: int,
        category: FailureCategory,
        details: str,
    ) -> None:
        """Delegate to :func:`phase_utils.record_harness_failure` (backward compat)."""
        record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            details,
            stage=PipelineStage.IMPLEMENT,
        )

    def _prepare_adr_plan(self, issue: Task) -> None:
        """Seed a deterministic ADR execution plan when an ADR issue lacks one."""
        if not is_adr_issue_title(issue.title):
            return

        plan_path = self._config.plans_dir / f"issue-{issue.id}.md"
        if plan_path.exists():
            return

        body = issue.body.strip() or "No ADR draft body provided."
        plan_text = (
            "## Implementation Plan\n\n"
            "1. Create or update a single ADR markdown file under `docs/adr/` "
            "for this issue.\n"
            "2. Preserve and refine the ADR sections (`Context`, `Decision`, "
            "`Consequences`) using the issue draft as source material.\n"
            "3. Ensure the ADR content is actionable and concrete enough for "
            "review (explicit decision, tradeoffs, and impact).\n"
            "4. Add/update references so the ADR links back to this issue.\n"
            "5. **Do NOT create tests for ADR markdown content.** ADRs are "
            "documentation — never add `test_adr_*.py` files that assert on "
            "headings, status, or prose.\n\n"
            "## ADR Draft From Issue\n\n"
            f"{body}\n"
        )
        try:
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(plan_text)
            logger.info(
                "Prepared ADR implementation plan fallback for issue #%d at %s",
                issue.id,
                plan_path,
            )
        except OSError:
            logger.warning(
                "Failed to prepare ADR plan fallback for issue #%d",
                issue.id,
                exc_info=True,
            )
