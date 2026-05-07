"""Implementation batch processing for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from adr_utils import is_adr_issue_title, next_adr_number
from agent import AgentRunner
from beads_manager import BeadsManager
from config import HydraFlowConfig
from harness_insights import FailureCategory, HarnessInsightStore
from models import (
    GitHubIssue,
    PipelineStage,
    PRInfo,
    Task,
    WorkerResult,
    WorkerResultMeta,
)
from phase_utils import (
    MemorySuggester,
    PipelineEscalator,
    _sentry_transaction,
    log_exception_with_bug_classification,
    record_harness_failure,
    release_batch_in_flight,
    run_refilling_pool,
    run_with_fatal_guard,
    store_lifecycle,
)
from run_recorder import RunRecorder
from state import StateTracker
from task_source import TaskTransitioner
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from ports import IssueStorePort, PRPort, WorkspacePort
    from precondition_gate import PreconditionGate

logger = logging.getLogger("hydraflow.implement_phase")


class ImplementPhase:
    """Fetches ready issues and runs implementation agents concurrently."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        workspaces: WorkspacePort,
        agents: AgentRunner,
        prs: PRPort,
        store: IssueStorePort,
        stop_event: asyncio.Event,
        run_recorder: RunRecorder | None = None,
        harness_insights: HarnessInsightStore | None = None,
        beads_manager: BeadsManager | None = None,
        active_issues_cb: Callable[[], None] | None = None,
        transcript_summarizer: TranscriptSummarizer | None = None,
        precondition_gate: PreconditionGate | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._workspaces = workspaces
        self._agents = agents
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._store = store
        self._stop_event = stop_event
        self._run_recorder = run_recorder
        self._harness_insights = harness_insights
        self._beads_manager = beads_manager
        self._active_issues_cb = active_issues_cb
        self._summarizer = transcript_summarizer
        self._active_issues: set[int] = set()
        self._active_issues_lock = asyncio.Lock()
        self._suggest_memory = MemorySuggester(config)
        self._zero_diff_memory_filed: set[int] = set()
        self._precondition_gate = precondition_gate
        self._escalator = PipelineEscalator(
            state,
            prs,
            store,
            harness_insights,
            origin_label=config.ready_label[0],
            hitl_label=config.hitl_label[0],
            diagnose_label=config.diagnose_label[0],
            stage=PipelineStage.IMPLEMENT,
        )

    @property
    def active_issues(self) -> set[int]:
        return self._active_issues

    async def _post_impl_transcript(self, result: WorkerResult, *, status: str) -> None:
        """File memory suggestion and post transcript summary for a single result."""
        if result.transcript:
            await self._suggest_memory(
                result.transcript, "implementer", f"issue #{result.issue_number}"
            )
        if self._summarizer and result.transcript and result.issue_number > 0:
            try:
                await self._summarizer.summarize_and_comment(
                    transcript=result.transcript,
                    issue_number=result.issue_number,
                    phase="implement",
                    status=status,
                    duration_seconds=result.duration_seconds,
                    log_file=self._impl_log_reference(result.issue_number),
                )
            except Exception as exc:
                log_exception_with_bug_classification(
                    logger,
                    exc,
                    f"Failed to post transcript summary for issue #{result.issue_number}",
                )

    async def post_impl_transcript_hooks(self, results: list[WorkerResult]) -> None:
        """File memory suggestions and post transcript summaries for completed runs.

        Called by the orchestrator after :meth:`run_batch` returns.  Skips
        memory filing for issues where the zero-diff escalation handler has
        already filed a suggestion with a more specific source tag.
        """
        for result in results:
            already_filed = result.issue_number in self._zero_diff_memory_filed
            self._zero_diff_memory_filed.discard(result.issue_number)
            if already_filed:
                # Zero-diff handler filed memory with a specific source; skip
                # memory filing here but still post the transcript summary.
                if self._summarizer and result.transcript and result.issue_number > 0:
                    try:
                        await self._summarizer.summarize_and_comment(
                            transcript=result.transcript,
                            issue_number=result.issue_number,
                            phase="implement",
                            status="success" if result.success else "failed",
                            duration_seconds=result.duration_seconds,
                            log_file=self._impl_log_reference(result.issue_number),
                        )
                    except Exception as exc:
                        log_exception_with_bug_classification(
                            logger,
                            exc,
                            f"Failed to post transcript summary for issue #{result.issue_number}",
                        )
            else:
                await self._post_impl_transcript(
                    result, status="success" if result.success else "failed"
                )

    def _impl_log_reference(self, issue_number: int) -> str:
        """Return a display-friendly log path for implementer transcripts."""
        log_path = self._config.log_dir / f"issue-{issue_number}.txt"
        return self._config.format_path_for_display(log_path)

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

        If *issues* is ``None``, drains the ``IssueStore`` ready queue
        once, runs the precondition gate (#6423) if configured, then
        feeds the gated batch into the slot-fill pool. If a fixed list
        is provided, processes those items directly without gating —
        callers that pass an explicit list are assumed to have done
        their own gating.
        """
        if issues is None and self._precondition_gate is not None:
            # Drain + gate at the start of the cycle. Issues that fail
            # the gate are routed back via the coordinator inside
            # filter_and_route — they do not appear in the gated list.
            from stage_preconditions import Stage  # noqa: PLC0415

            drained: list[Task] = []
            while True:
                batch = self._store.get_implementable(8)
                if not batch:
                    break
                drained.extend(batch)
            issues = await self._precondition_gate.filter_and_route(
                drained, Stage.READY
            )

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
                if self._active_issues_cb:
                    self._active_issues_cb()
            with _sentry_transaction("pipeline.implement", f"implement:#{issue.id}"):
                async with store_lifecycle(self._store, issue.id, "implement"):
                    self._state.mark_issue(issue.id, "in_progress")
                    self._state.set_branch(issue.id, branch)

                    def _on_worker_failure(exc_name: str) -> WorkerResult:
                        self._state.mark_issue(issue.id, "failed")
                        record_harness_failure(
                            self._harness_insights,
                            issue.id,
                            FailureCategory.IMPLEMENTATION_ERROR,
                            f"Worker {exc_name} for issue #{issue.id}",
                            stage=PipelineStage.IMPLEMENT,
                        )
                        return WorkerResult(
                            issue_number=issue.id,
                            branch=branch,
                            error=f"Worker {exc_name} for issue #{issue.id}",
                        )

                    try:
                        return await run_with_fatal_guard(
                            self._worker_inner(idx, issue, branch),
                            on_failure=_on_worker_failure,
                            context=f"Worker failed for issue #{issue.id}",
                            log=logger,
                        )
                    finally:
                        async with self._active_issues_lock:
                            self._active_issues.discard(issue.id)
                            if self._active_issues_cb:
                                self._active_issues_cb()
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

        # If a non-draft PR already exists and this is NOT a review-feedback
        # retry, skip implementation and transition directly to review.
        # This handles issues requeued to hydraflow-ready that already have
        # completed PRs from a prior run.
        review_feedback = self._state.get_review_feedback(issue.id) or ""
        if not review_feedback:
            existing_pr = await self._prs.find_open_pr_for_branch(
                branch, issue_number=issue.id
            )
            if existing_pr and existing_pr.number > 0 and not existing_pr.draft:
                logger.info(
                    "Issue #%d already has open PR #%d — skipping to review",
                    issue.id,
                    existing_pr.number,
                )
                self._store.enqueue_transition(issue, "review")
                await self._transitioner.transition(
                    issue.id,
                    "review",
                    pr_number=existing_pr.number,
                )
                self._state.increment_session_counter("implemented")
                self._state.mark_issue(issue.id, "success")
                return WorkerResult(
                    issue_number=issue.id,
                    branch=branch,
                    success=True,
                    pr_info=existing_pr,
                )

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
                ctx.save_config(
                    self._config.model_dump(
                        mode="json",
                        exclude={
                            "gh_token",
                            "sentry_auth_token",
                            "whatsapp_token",
                            "whatsapp_phone_id",
                            "whatsapp_recipient",
                            "whatsapp_verify_token",
                        },
                    )
                )
            except (RuntimeError, OSError):
                logger.debug("Run recording setup failed", exc_info=True)
                ctx = None

        # Inject prior reflections into the issue context so the agent
        # benefits from learnings accumulated in previous cycles.
        from reflections import append_reflection, read_reflections  # noqa: PLC0415

        prior_reflections = read_reflections(self._config, issue.id)
        if prior_reflections:
            issue.body = (issue.body or "") + (
                f"\n\n## Prior Reflections\n\n{prior_reflections}"
            )

        result = await self._run_implementation(issue, branch, idx, review_feedback)

        # Record a reflection for future cycles
        if result.error:
            append_reflection(
                self._config,
                issue.id,
                "implement",
                f"Attempt {idx} failed: {result.error[:200]}",
            )
        elif result.success:
            append_reflection(
                self._config,
                issue.id,
                "implement",
                f"Attempt {idx} succeeded on branch {branch}.",
            )

        # Finalize the recording
        if ctx is not None:
            try:
                if result.transcript:
                    for line in result.transcript.splitlines():
                        ctx.append_transcript(line)
                outcome = "success" if result.success else "failed"
                ctx.finalize(outcome, error=result.error)
            except (RuntimeError, OSError):
                logger.debug("Run recording finalize failed", exc_info=True)

        is_retry = bool(review_feedback)
        final_result = await self._handle_implementation_result(issue, result, is_retry)
        return final_result

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
        await self._escalator(
            issue,
            cause=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s)",
            details=f"Implementation attempt cap exceeded after {attempts - 1} attempt(s): {last_error}",
            category=FailureCategory.HITL_ESCALATION,
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

    async def _setup_worktree_and_branch(
        self, issue: Task, branch: str, *, reset_for_retry: bool = False
    ) -> Path:
        """Ensure worktree exists/resumed and branch is pushed.

        When *reset_for_retry* is True, resets an existing worktree to
        ``origin/main`` to discard stale state from a prior failed attempt.
        """
        wt_path = self._config.workspace_path_for_issue(issue.id)
        if wt_path.is_dir():
            if reset_for_retry:
                logger.info(
                    "Resetting worktree to clean state for issue #%d retry",
                    issue.id,
                )
                try:
                    await self._workspaces.reset_to_main(wt_path)
                except (RuntimeError, OSError):
                    logger.warning(
                        "Worktree reset failed for issue #%d — continuing with existing state",
                        issue.id,
                        exc_info=True,
                    )
            else:
                logger.info("Resuming existing worktree for issue #%d", issue.id)
        else:
            wt_path = await self._workspaces.create(issue.id, branch)
        self._state.set_workspace(issue.id, str(wt_path))
        await self._prs.push_branch(wt_path, branch, force=reset_for_retry)
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
            "pre_quality_review_attempts": result.pre_quality_review_attempts,
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
        # Retrieve prior failure context for retry feedback
        last_meta = self._state.get_worker_result_meta(issue.id)
        prior_failure = ""
        reset_for_retry = bool(review_feedback)  # review-feedback retries always reset
        # Only inject prior failure context for cycling retries (no active review feedback).
        # During review-feedback retries the prior error is stale — the agent should
        # focus on reviewer comments, not a potentially-resolved quality gate error.
        if last_meta and not review_feedback:
            prior_error = last_meta.get("error") or ""
            if prior_error:
                prior_failure = prior_error
                reset_for_retry = True

        wt_path = await self._setup_worktree_and_branch(
            issue, branch, reset_for_retry=reset_for_retry
        )

        # Capture items.jsonl hash before agent runs (for outcome tracking)
        import hashlib  # noqa: PLC0415

        items_path = self._config.memory_dir / "items.jsonl"
        digest_hash = ""
        if items_path.exists():
            with contextlib.suppress(OSError):
                digest_hash = hashlib.sha256(items_path.read_bytes()).hexdigest()[:16]
        self._state.set_digest_hash(issue.id, digest_hash)

        # Copy architecture diagrams from /tmp into the worktree so the
        # implementer agent has full architectural context on disk.
        from planner import PlannerRunner  # noqa: PLC0415

        n_diagrams = PlannerRunner.copy_diagrams_to_workspace(issue.id, wt_path)
        if n_diagrams:
            logger.info(
                "Copied %d diagram file(s) into workspace for #%d",
                n_diagrams,
                issue.id,
            )
            PlannerRunner.cleanup_diagrams(issue.id)

        # Enrich the task with comments so the agent can find the plan
        # comment posted by the planner.  The IssueStore bulk fetch
        # does not include comment bodies.
        issue = await self._store.enrich_with_comments(issue)

        # Load bead mapping for the issue
        bead_mapping: dict[str, str] | None = None
        if self._beads_manager:
            bead_mapping = self._state.get_bead_mapping(issue.id) or None
            if bead_mapping:
                await self._beads_manager.init(wt_path)

        run_kwargs: dict[str, object] = {
            "worker_id": worker_id,
            "review_feedback": review_feedback,
            "prior_failure": prior_failure,
        }
        if bead_mapping:
            run_kwargs["bead_mapping"] = bead_mapping

        # Allocate a trace run id and set the tracing context on the agent
        # runner so its _execute calls build a TraceCollector.
        from trace_rollup import write_phase_rollup  # noqa: PLC0415
        from tracing_context import TracingContext, source_to_phase  # noqa: PLC0415

        phase = source_to_phase("implementer")
        run_id = self._state.begin_trace_run(issue.id, phase)
        self._agents.set_tracing_context(
            TracingContext(
                issue_number=issue.id,
                phase=phase,
                source="implementer",
                run_id=run_id,
            )
        )

        try:
            result = await self._agents.run(
                issue,
                wt_path,
                branch,
                **run_kwargs,  # type: ignore[arg-type]
            )
        finally:
            self._agents.clear_tracing_context()
            # Roll up the subprocess traces whether the run succeeded or failed.
            try:
                write_phase_rollup(
                    config=self._config,
                    issue_number=issue.id,
                    phase=phase,
                    run_id=run_id,
                )
            except Exception:
                logger.warning(
                    "Phase rollup failed for issue #%d", issue.id, exc_info=True
                )
            self._state.end_trace_run(issue.id, phase)

        await self._record_impl_metrics(issue, result, review_feedback)

        return result

    async def _handle_implementation_result(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> WorkerResult:
        """Handle the result of an agent run: close, create PR, swap labels."""
        if self._is_zero_commit_failure(result):
            return await self._handle_zero_commits(issue, result)

        if result.workspace_path:
            pushed = await self._prs.push_branch(
                Path(result.workspace_path), result.branch
            )
            if pushed:
                early_return = await self._handle_successful_push(
                    issue, result, is_retry
                )
                if early_return is not None:
                    return early_return

        # Post-implementation: flag any requirements gaps discovered
        if result.success and result.transcript:
            await self._flag_requirements_gaps(issue, result.transcript)

        status = "success" if result.success else "failed"
        self._state.mark_issue(issue.id, status)
        return result

    @staticmethod
    def _is_zero_commit_failure(result: WorkerResult) -> bool:
        """Check whether *result* represents a zero-commit implementation failure."""
        return (
            not result.success
            and result.error == "No commits found on branch"
            and result.commits == 0
        )

    async def _flag_requirements_gaps(self, issue: Task, transcript: str) -> None:
        """Detect and post requirements gaps discovered during implementation."""
        from spec_match import extract_requirements_gaps  # noqa: PLC0415

        gaps = extract_requirements_gaps(transcript)
        if not gaps:
            return
        lines = ["## Requirements Gaps Discovered During Implementation\n"]
        for gap in gaps:
            lines.append(f"- **Gap:** {gap.get('gap', 'Unknown')}")
            if gap.get("impact"):
                lines.append(f"  - Impact: {gap['impact']}")
            if gap.get("assumption"):
                lines.append(f"  - Assumption made: {gap['assumption']}")
        lines.append(
            "\n*These gaps were flagged by the implementation agent. "
            "Review whether the spec needs updating.*"
        )
        await self._prs.post_comment(issue.id, "\n".join(lines))
        logger.info(
            "Issue #%d: %d requirements gaps flagged during implementation",
            issue.id,
            len(gaps),
        )

    async def _handle_zero_commits(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Handle a zero-commit implementation failure.

        Marks as failed so the attempt-cap mechanism can retry with corrective
        context (prior_failure feedback) instead of escalating immediately.
        """
        attempts = self._state.get_issue_attempts(issue.id)
        logger.warning(
            "Issue #%d: zero commits after implementation (attempt %d/%d)",
            issue.id,
            attempts,
            self._config.max_issue_attempts,
        )
        await self._transitioner.post_comment(
            issue.id,
            "## Implementation Failed — Zero Commits\n\n"
            "The implementation agent ran but produced no commits. "
            f"Attempt {attempts}/{self._config.max_issue_attempts}.\n\n"
            "---\n"
            "*Generated by HydraFlow Implementer*",
        )
        self._state.mark_issue(issue.id, "failed")
        return result

    async def _resolve_pr(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> PRInfo | None:
        """Create a new PR or recover an existing one, updating result.pr_info."""
        if not is_retry:
            gh_issue = GitHubIssue.from_task(issue)
            pr = await self._prs.create_pr(gh_issue, result.branch)
        else:
            pr = await self._prs.find_open_pr_for_branch(
                result.branch, issue_number=issue.id
            )
            if pr is not None and pr.number > 0:
                from pr_manager import PRManager as _PRManager  # noqa: PLC0415

                expected_title = _PRManager.expected_pr_title(issue.id, issue.title)
                await self._prs.update_pr_title(pr.number, expected_title)
        result.pr_info = pr
        return pr

    async def _handle_successful_push(
        self, issue: Task, result: WorkerResult, is_retry: bool
    ) -> WorkerResult | None:
        """Create/find PR after a successful push.

        Returns a ``WorkerResult`` to short-circuit the caller when the
        outcome is fully resolved (PR-less failure or zero-diff escalation).
        Returns ``None`` when the caller should continue to the final
        status-marking step.
        """
        pr = await self._resolve_pr(issue, result, is_retry)

        if result.success and (pr is None or pr.number <= 0):
            return await self._handle_no_pr_fallback(issue, result)

        if result.success:
            self._store.enqueue_transition(issue, "review")
            await self._transitioner.transition(
                issue.id,
                "review",
                pr_number=pr.number if pr and pr.number > 0 else None,
            )
            self._state.increment_session_counter("implemented")

        return None

    async def _escalate_no_changes_to_hitl(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Escalate to HITL when the branch has no diff from main."""
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
        from models import EscalationContext  # noqa: PLC0415

        context = EscalationContext(
            cause=self._hitl_cause(
                issue, "implementation produced no changes (zero diff)"
            ),
            origin_phase="implement",
            agent_transcript=result.transcript if result.transcript else None,
        )
        await self._escalator(
            issue,
            cause=context.cause,
            details="Implementation produced no changes (zero diff)",
            category=FailureCategory.HITL_ESCALATION,
            context=context,
        )
        if result.transcript:
            await self._suggest_memory(
                result.transcript,
                "implement_zero_diff",
                f"issue #{issue.id}",
            )
            self._zero_diff_memory_filed.add(issue.id)
        return result

    async def _handle_no_pr_fallback(
        self, issue: Task, result: WorkerResult
    ) -> WorkerResult:
        """Handle the case where implementation succeeded but no PR exists.

        If the branch has no diff from main, escalates to HITL.  Otherwise
        marks as failed for retry.
        """
        has_diff = await self._prs.branch_has_diff_from_main(result.branch)
        if not has_diff:
            return await self._escalate_no_changes_to_hitl(issue, result)

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

    def _prepare_adr_plan(self, issue: Task) -> None:
        """Seed a deterministic ADR execution plan when an ADR issue lacks one."""
        if not is_adr_issue_title(issue.title):
            return

        plan_path = self._config.plans_dir / f"issue-{issue.id}.md"
        if plan_path.exists():
            return

        # Reserve a unique ADR number by scanning the primary repo (not the
        # worktree copy) and the in-process assignment set.
        primary_adr_dir = self._config.repo_root / "docs" / "adr"
        adr_number = next_adr_number(primary_adr_dir)
        adr_number_str = f"{adr_number:04d}"

        body = issue.body.strip() or "No ADR draft body provided."
        plan_text = (
            "## Implementation Plan\n\n"
            f"1. Create a single ADR markdown file named "
            f"`docs/adr/{adr_number_str}-<slug>.md` (ADR number "
            f"**{adr_number_str}** is pre-assigned — do NOT pick a different "
            f"number).\n"
            "2. Preserve and refine the ADR sections (`Context`, `Decision`, "
            "`Consequences`) using the issue draft as source material.\n"
            "3. Ensure the ADR content is actionable and concrete enough for "
            "review (explicit decision, tradeoffs, and impact).\n"
            "4. Add/update references so the ADR links back to this issue.\n"
            "   - Anywhere in the ADR (Related, Context, Decision, Consequences), "
            "cite source files by function/class name only "
            "(e.g. `src/config.py:_resolve_base_paths`). Do NOT include line numbers — "
            "they become stale as source files change.\n"
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
