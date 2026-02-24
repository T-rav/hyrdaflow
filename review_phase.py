"""Review processing for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acceptance_criteria import AcceptanceCriteriaGenerator
from agent import AgentRunner
from config import HydraFlowConfig
from epic import EpicCompletionChecker
from events import EventBus, EventType, HydraFlowEvent
from harness_insights import FailureCategory, FailureRecord, HarnessInsightStore
from issue_store import IssueStore
from merge_conflict_resolver import MergeConflictResolver
from models import (
    JudgeResult,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
)
from phase_utils import run_concurrent_batch, store_lifecycle
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager, SelfReviewError
from retrospective import RetrospectiveCollector
from review_insights import (
    CATEGORY_DESCRIPTIONS,
    ReviewInsightStore,
    ReviewRecord,
    analyze_patterns,
    build_insight_issue_body,
    extract_categories,
)
from reviewer import ReviewRunner
from state import StateTracker
from transcript_summarizer import TranscriptSummarizer
from verification_judge import VerificationJudge
from worktree import WorktreeManager

logger = logging.getLogger("hydraflow.review_phase")


class ReviewPhase:
    """Runs reviewer agents on PRs, merging approved ones inline."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        worktrees: WorktreeManager,
        reviewers: ReviewRunner,
        prs: PRManager,
        stop_event: asyncio.Event,
        store: IssueStore,
        agents: AgentRunner | None = None,
        event_bus: EventBus | None = None,
        retrospective: RetrospectiveCollector | None = None,
        ac_generator: AcceptanceCriteriaGenerator | None = None,
        verification_judge: VerificationJudge | None = None,
        transcript_summarizer: TranscriptSummarizer | None = None,
        epic_checker: EpicCompletionChecker | None = None,
        harness_insights: HarnessInsightStore | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._worktrees = worktrees
        self._reviewers = reviewers
        self._prs = prs
        self._stop_event = stop_event
        self._store = store
        self._agents = agents
        self._bus = event_bus or EventBus()
        self._retrospective = retrospective
        self._ac_generator = ac_generator
        self._verification_judge = verification_judge
        self._summarizer = transcript_summarizer
        self._epic_checker = epic_checker
        self._harness_insights = harness_insights
        self._insights = ReviewInsightStore(config.memory_dir)
        self._active_issues: set[int] = set()
        self._conflict_resolver = MergeConflictResolver(
            config=config,
            worktrees=worktrees,
            agents=agents,
            prs=prs,
            event_bus=self._bus,
            state=state,
            summarizer=transcript_summarizer,
        )
        self._post_merge = PostMergeHandler(
            config=config,
            state=state,
            prs=prs,
            event_bus=self._bus,
            ac_generator=ac_generator,
            retrospective=retrospective,
            verification_judge=verification_judge,
            epic_checker=epic_checker,
        )

    async def review_prs(
        self,
        prs: list[PRInfo],
        issues: list[Task],
    ) -> list[ReviewResult]:
        """Run reviewer agents on non-draft PRs, merging approved ones inline."""
        if not prs:
            return []

        issue_map = {i.id: i for i in issues}
        semaphore = asyncio.Semaphore(self._config.max_reviewers)

        async def _review_one(idx: int, pr: PRInfo) -> ReviewResult:
            if self._stop_event.is_set():
                return ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    summary="stopped",
                )
            async with semaphore:
                if self._stop_event.is_set():
                    return ReviewResult(
                        pr_number=pr.number,
                        issue_number=pr.issue_number,
                        summary="stopped",
                    )
                self._active_issues.add(pr.issue_number)
                self._state.set_active_issue_numbers(list(self._active_issues))
                async with store_lifecycle(self._store, pr.issue_number, "review"):
                    try:
                        return await self._review_one_inner(idx, pr, issue_map)
                    except Exception:
                        logger.exception(
                            "Review failed for PR #%d (issue #%d)",
                            pr.number,
                            pr.issue_number,
                        )
                        return ReviewResult(
                            pr_number=pr.number,
                            issue_number=pr.issue_number,
                            summary="Review failed due to unexpected error",
                        )
                    finally:
                        await self._publish_review_status(pr, idx, "done")
                        self._active_issues.discard(pr.issue_number)
                        self._state.set_active_issue_numbers(list(self._active_issues))

        return await run_concurrent_batch(prs, _review_one, self._stop_event)

    async def _review_one_inner(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
    ) -> ReviewResult:
        """Core review logic for a single PR — called inside the semaphore."""
        await self._publish_review_status(pr, idx, "start")

        task = issue_map.get(pr.issue_number)
        if task is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Issue not found",
            )

        # Skip guard: avoid re-reviewing when no new commits since last review
        current_sha = await self._prs.get_pr_head_sha(pr.number)
        if current_sha:
            stored_sha = self._state.get_last_reviewed_sha(pr.issue_number)
            if stored_sha and stored_sha == current_sha:
                logger.info(
                    "PR #%d (issue #%d): skipping review — no new commits since "
                    "last review (SHA %s)",
                    pr.number,
                    pr.issue_number,
                    current_sha[:12],
                )
                return ReviewResult(
                    pr_number=pr.number,
                    issue_number=pr.issue_number,
                    summary="Skipped — no new commits since last review",
                )

        wt_path = self._config.worktree_base / f"issue-{pr.issue_number}"
        if not wt_path.exists():
            wt_path = await self._worktrees.create(pr.issue_number, pr.branch)

        # Merge main and push — returns False on unresolvable conflicts
        merged = await self._merge_with_main(pr, task, wt_path, idx)
        if not merged:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Merge conflicts with main — escalated to HITL",
            )

        diff = await self._prs.get_pr_diff(pr.number)

        # Delta verification: compare planned vs actual files
        await self._run_delta_verification(pr, diff)

        result = await self._run_and_post_review(pr, task, wt_path, diff, idx)

        # If reviewer fixed its own findings, re-review the updated code
        if result.fixes_made and result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            result, diff = await self._handle_self_fix_re_review(
                pr, task, wt_path, result, diff, idx
            )

        self._state.mark_pr(pr.number, result.verdict.value)
        self._state.mark_issue(pr.issue_number, "reviewed")
        self._state.record_review_verdict(result.verdict.value, result.fixes_made)

        # Record the current remote HEAD SHA so the skip guard works next cycle
        post_review_sha = await self._prs.get_pr_head_sha(pr.number)
        if post_review_sha:
            self._state.set_last_reviewed_sha(pr.issue_number, post_review_sha)

        if result.duration_seconds > 0:
            self._state.record_review_duration(result.duration_seconds)
        await self._record_review_insight(result)
        if result.verdict != ReviewVerdict.APPROVE:
            self._record_harness_failure(
                pr.issue_number,
                FailureCategory.REVIEW_REJECTION,
                f"Review verdict: {result.verdict.value}. {result.summary[:200]}",
                pr_number=pr.number,
            )

        # Verdict-specific handling
        skip_worktree_cleanup = False
        if result.verdict == ReviewVerdict.APPROVE and pr.number > 0:
            await self._handle_approved_merge(pr, task, result, diff, idx)
        elif result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            skip_worktree_cleanup = await self._handle_rejected_review(pr, result, idx)

        # Preserve worktrees for interrupted reviews so work can be resumed.
        # If the PR was already merged, the worktree is no longer needed.
        if self._stop_event.is_set() and not result.merged:
            skip_worktree_cleanup = True

        if not skip_worktree_cleanup:
            try:
                await self._worktrees.destroy(pr.issue_number)
                self._state.remove_worktree(pr.issue_number)
            except RuntimeError as exc:
                logger.warning(
                    "Could not destroy worktree for issue #%d: %s",
                    pr.issue_number,
                    exc,
                )

        return result

    async def _merge_with_main(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        worker_id: int,
    ) -> bool:
        """Merge main into the PR branch, resolving conflicts if needed.

        Returns True on success, False on failure (escalates to HITL).
        """
        return await self._conflict_resolver.merge_with_main(
            pr,
            issue,
            wt_path,
            worker_id,
            escalate_fn=self._escalate_to_hitl,
            publish_fn=self._publish_review_status,
        )

    async def _run_and_post_review(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        diff: str,
        worker_id: int,
    ) -> ReviewResult:
        """Run the reviewer, push fixes, post summary, submit formal review."""
        result = await self._reviewers.review(
            pr, issue, wt_path, diff, worker_id=worker_id
        )

        if result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        if result.summary and pr.number > 0:
            await self._prs.post_pr_comment(pr.number, result.summary)

        if pr.number > 0 and result.verdict != ReviewVerdict.APPROVE:
            try:
                await self._prs.submit_review(pr.number, result.verdict, result.summary)
            except SelfReviewError:
                logger.info(
                    "Skipping formal %s review on own PR #%d"
                    " — already posted as comment",
                    result.verdict.value,
                    pr.number,
                )

        if result.verdict == ReviewVerdict.APPROVE:
            result = await self._check_adversarial_threshold(
                pr, issue, wt_path, diff, result, worker_id
            )

        return result

    async def _handle_self_fix_re_review(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
    ) -> tuple[ReviewResult, str]:
        """Re-review a PR after the reviewer self-fixed findings.

        Returns ``(updated_result, updated_diff)``.  If the re-review
        approves, the upgraded result and refreshed diff are returned.
        On failure or continued rejection the original result is preserved.
        """
        logger.info(
            "PR #%d: reviewer self-fixed with %s verdict — re-reviewing updated code",
            pr.number,
            result.verdict.value,
        )
        try:
            await self._publish_review_status(pr, worker_id, "re_reviewing")
            updated_diff = await self._prs.get_pr_diff(pr.number)
            re_result = await self._reviewers.review(
                pr, issue, wt_path, updated_diff, worker_id=worker_id
            )
            if re_result.fixes_made:
                await self._prs.push_branch(wt_path, pr.branch)
            if re_result.verdict == ReviewVerdict.APPROVE:
                logger.info(
                    "PR #%d: self-fix re-review passed — upgrading verdict to APPROVE",
                    pr.number,
                )
                return re_result, updated_diff
            logger.info(
                "PR #%d: self-fix re-review still returned %s — proceeding with rejection",
                pr.number,
                re_result.verdict.value,
            )
            return result, updated_diff
        except Exception:
            logger.warning(
                "PR #%d: self-fix re-review failed — falling back to original rejection",
                pr.number,
                exc_info=True,
            )
            return result, diff

    async def _run_delta_verification(self, pr: PRInfo, diff: str) -> str:
        """Run delta verification comparing plan's File Delta section to actual diff.

        Returns a summary string (empty if no plan or no delta section).
        """
        from delta_verifier import parse_file_delta, verify_delta

        plan_path = self._config.plans_dir / f"issue-{pr.issue_number}.md"
        if not plan_path.exists():
            return ""

        try:
            plan_text = plan_path.read_text()
        except OSError:
            return ""

        planned_files = parse_file_delta(plan_text)
        if not planned_files:
            return ""

        # Extract actual changed files from the diff
        actual_files = await self._prs.get_pr_diff_names(pr.number)
        report = verify_delta(planned_files, actual_files)

        if report.has_drift:
            summary = report.format_summary()
            logger.warning(
                "Delta drift for PR #%d (issue #%d): %d missing, %d unexpected",
                pr.number,
                pr.issue_number,
                len(report.missing),
                len(report.unexpected),
            )
            return summary
        return ""

    async def _handle_approved_merge(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        diff: str,
        worker_id: int,
    ) -> None:
        """Attempt merge for an approved PR (with optional CI gate)."""
        await self._post_merge.handle_approved(
            pr,
            issue,
            result,
            diff,
            worker_id,
            ci_gate_fn=self.wait_and_fix_ci,
            escalate_fn=self._escalate_to_hitl,
            publish_fn=self._publish_review_status,
        )

    async def wait_and_fix_ci(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Wait for CI and attempt fixes if it fails.

        Returns *True* if CI passed and the PR should be merged.
        Mutates *result* to set ``ci_passed`` and ``ci_fix_attempts``.
        """
        max_attempts = self._config.max_ci_fix_attempts
        summary = ""

        for attempt in range(max_attempts + 1):
            await self._publish_review_status(pr, worker_id, "ci_wait")
            passed, summary = await self._prs.wait_for_ci(
                pr.number,
                self._config.ci_check_timeout,
                self._config.ci_poll_interval,
                self._stop_event,
            )
            if passed:
                result.ci_passed = True
                return True

            # Last attempt — no more retries
            if attempt >= max_attempts:
                break

            # Fetch full CI logs when observability injection is enabled
            ci_logs = ""
            if self._config.inject_runtime_logs:
                try:
                    raw = await self._prs.fetch_ci_failure_logs(pr.number)
                    if raw:
                        from log_context import truncate_log  # noqa: PLC0415

                        ci_logs = truncate_log(raw, self._config.max_ci_log_chars)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Could not fetch CI failure logs for PR #%d",
                        pr.number,
                        exc_info=True,
                    )

            # Run the CI fix agent
            await self._publish_review_status(pr, worker_id, "ci_fix")
            fix_result = await self._reviewers.fix_ci(
                pr,
                issue,
                wt_path,
                summary,
                attempt=attempt + 1,
                worker_id=worker_id,
                ci_logs=ci_logs,
            )
            result.ci_fix_attempts += 1

            if not fix_result.fixes_made:
                logger.info(
                    "CI fix agent made no changes for PR #%d — stopping retries",
                    pr.number,
                )
                break

            # Push fixes and loop back to wait_for_ci
            await self._prs.push_branch(wt_path, pr.branch)

        # CI failed after all attempts — escalate to human
        result.ci_passed = False
        self._state.record_ci_fix_rounds(result.ci_fix_attempts)
        self._record_harness_failure(
            issue.id,
            FailureCategory.CI_FAILURE,
            f"CI failed after {result.ci_fix_attempts} fix attempt(s): {summary[:200]}",
            pr_number=pr.number,
        )
        await self._publish_review_status(pr, worker_id, "escalating")
        cause = f"CI failed after {result.ci_fix_attempts} fix attempt(s)"
        await self._escalate_to_hitl(
            issue.id,
            pr.number,
            cause=cause,
            origin_label=self._config.review_label[0],
            comment=(
                f"**CI failed** after {result.ci_fix_attempts} fix attempt(s).\n\n"
                f"Last failure: {summary}\n\n"
                f"PR not merged — escalating to human review."
            ),
            event_cause="ci_failed",
            extra_event_data={"ci_fix_attempts": result.ci_fix_attempts},
        )
        return False

    async def _record_review_insight(self, result: ReviewResult) -> None:
        """Record a review result and file improvement proposals if patterns emerge.

        Wrapped in try/except so insight failures never interrupt the review flow.
        """
        try:
            record = ReviewRecord(
                pr_number=result.pr_number,
                issue_number=result.issue_number,
                timestamp=datetime.now(UTC).isoformat(),
                verdict=result.verdict.value,
                summary=result.summary,
                fixes_made=result.fixes_made,
                categories=extract_categories(result.summary),
            )
            self._insights.append_review(record)

            recent = self._insights.load_recent(self._config.review_insight_window)
            patterns = analyze_patterns(recent, self._config.review_pattern_threshold)
            proposed = self._insights.get_proposed_categories()

            for category, count, evidence in patterns:
                if category in proposed:
                    continue
                body = build_insight_issue_body(category, count, len(recent), evidence)
                desc = CATEGORY_DESCRIPTIONS.get(category, category)
                title = f"[Review Insight] Recurring feedback: {desc}"
                labels = self._config.improve_label[:1] + self._config.hitl_label[:1]
                issue_num = await self._prs.create_issue(title, body, labels)
                if issue_num:
                    self._state.set_hitl_origin(
                        issue_num, self._config.improve_label[0]
                    )
                    self._state.set_hitl_cause(
                        issue_num, f"Recurring review pattern: {desc}"
                    )
                self._insights.mark_category_proposed(category)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Review insight recording failed for PR #%d",
                result.pr_number,
                exc_info=True,
            )

    async def _publish_review_status(
        self, pr: PRInfo, worker_id: int, status: str
    ) -> None:
        """Emit a REVIEW_UPDATE event with the given status."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.REVIEW_UPDATE,
                data={
                    "pr": pr.number,
                    "issue": pr.issue_number,
                    "worker": worker_id,
                    "status": status,
                    "role": "reviewer",
                },
            )
        )

    async def _escalate_to_hitl(
        self,
        issue_number: int,
        pr_number: int,
        cause: str,
        origin_label: str,
        *,
        comment: str,
        post_on_pr: bool = True,
        event_cause: str = "",
        extra_event_data: dict[str, object] | None = None,
    ) -> None:
        """Record HITL escalation state, swap labels, post comment, publish event."""
        self._state.set_hitl_origin(issue_number, origin_label)
        self._state.set_hitl_cause(issue_number, cause)
        self._state.record_hitl_escalation()

        await self._prs.swap_pipeline_labels(
            issue_number,
            self._config.hitl_label[0],
            pr_number=pr_number,
        )

        if post_on_pr:
            await self._prs.post_pr_comment(pr_number, comment)
        else:
            await self._prs.post_comment(issue_number, comment)

        event_data: dict[str, object] = {
            "issue": issue_number,
            "pr": pr_number,
            "status": "escalated",
            "role": "reviewer",
            "cause": event_cause or cause,
        }
        if extra_event_data:
            event_data.update(extra_event_data)
        await self._bus.publish(
            HydraFlowEvent(type=EventType.HITL_ESCALATION, data=event_data)
        )

    @staticmethod
    def _count_review_findings(summary: str) -> int:
        """Count the number of findings in a review summary.

        Counts bullet points (``-`` or ``*``) and numbered items (``1.``)
        as individual findings.
        """
        lines = summary.strip().splitlines()
        count = 0
        for line in lines:
            stripped = line.strip()
            # Bullet points ("- text", "* text") or numbered items ("1. text")
            if re.match(r"^[-*]\s+\S", stripped) or re.match(r"^\d+\.\s+\S", stripped):
                count += 1
        return count

    async def _check_adversarial_threshold(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        diff: str,
        result: ReviewResult,
        worker_id: int,
    ) -> ReviewResult:
        """Re-review if APPROVE has too few findings and no justification.

        Returns the (possibly updated) review result.
        """
        min_findings = self._config.min_review_findings
        if min_findings <= 0:
            return result

        findings_count = self._count_review_findings(result.summary)
        has_justification = "THOROUGH_REVIEW_COMPLETE" in result.transcript

        if findings_count >= min_findings or has_justification:
            return result

        # Under threshold with no justification — re-review once
        logger.info(
            "PR #%d: APPROVE with only %d findings (min %d) and no "
            "THOROUGH_REVIEW_COMPLETE — re-reviewing",
            pr.number,
            findings_count,
            min_findings,
        )
        await self._publish_review_status(pr, worker_id, "re_reviewing")

        re_result = await self._reviewers.review(
            pr, issue, wt_path, diff, worker_id=worker_id
        )

        # If re-review still under threshold without justification, accept
        # but log a warning (don't loop forever)
        re_count = self._count_review_findings(re_result.summary)
        re_justified = "THOROUGH_REVIEW_COMPLETE" in re_result.transcript
        if re_count < min_findings and not re_justified:
            logger.warning(
                "PR #%d: re-review still under threshold (%d/%d) "
                "with no justification — accepting anyway",
                pr.number,
                re_count,
                min_findings,
            )

        # If reviewer made fixes during re-review, push them
        if re_result.fixes_made:
            await self._prs.push_branch(wt_path, pr.branch)

        return re_result

    async def _handle_rejected_review(
        self,
        pr: PRInfo,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Handle REQUEST_CHANGES or COMMENT verdict with retry logic.

        Returns *True* if the worktree should be preserved (retry case),
        *False* if the worktree should be destroyed (HITL escalation).
        """
        max_attempts = self._config.max_review_fix_attempts
        attempts = self._state.get_review_attempts(pr.issue_number)

        if attempts < max_attempts:
            # Under cap: re-queue for implementation with feedback
            new_count = self._state.increment_review_attempts(pr.issue_number)
            self._state.set_review_feedback(pr.issue_number, result.summary)

            # Swap labels: review → ready (issue and PR)
            await self._prs.swap_pipeline_labels(
                pr.issue_number,
                self._config.ready_label[0],
                pr_number=pr.number,
            )

            await self._prs.post_comment(
                pr.issue_number,
                f"**Review requested changes** (attempt {new_count}/{max_attempts}). "
                f"Re-queuing for implementation with feedback.",
            )

            logger.info(
                "PR #%d: %s verdict — retry %d/%d, re-queuing issue #%d",
                pr.number,
                result.verdict.value,
                new_count,
                max_attempts,
                pr.issue_number,
            )
            return True  # Preserve worktree
        else:
            # Cap exceeded: escalate to HITL
            logger.warning(
                "PR #%d: review fix cap (%d) exceeded — escalating issue #%d to HITL",
                pr.number,
                max_attempts,
                pr.issue_number,
            )
            self._record_harness_failure(
                pr.issue_number,
                FailureCategory.HITL_ESCALATION,
                f"Review fix cap exceeded after {max_attempts} attempt(s)",
                pr_number=pr.number,
            )
            await self._publish_review_status(pr, worker_id, "escalating")
            await self._escalate_to_hitl(
                pr.issue_number,
                pr.number,
                cause=f"Review fix cap exceeded after {max_attempts} attempt(s)",
                origin_label=self._config.review_label[0],
                comment=(
                    f"**Review fix cap exceeded** — {max_attempts} review fix "
                    f"attempt(s) exhausted. Escalating to human review."
                ),
                post_on_pr=False,
                event_cause="review_fix_cap_exceeded",
            )
            return False  # Destroy worktree

    def _record_harness_failure(
        self,
        issue_number: int,
        category: FailureCategory,
        details: str,
        *,
        pr_number: int = 0,
    ) -> None:
        """Record a failure to the harness insight store (non-blocking)."""
        if self._harness_insights is None:
            return
        try:
            from harness_insights import extract_subcategories

            record = FailureRecord(
                issue_number=issue_number,
                pr_number=pr_number,
                category=category,
                subcategories=extract_subcategories(details),
                details=details,
                stage="review",
            )
            self._harness_insights.append_failure(record)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to record harness failure for issue #%d",
                issue_number,
                exc_info=True,
            )

    # Delegate properties for backward compatibility in tests
    @property
    def _resolve_merge_conflicts(
        self,
    ) -> Callable[..., Coroutine[Any, Any, tuple[bool, bool]]]:
        """Backward-compatible access to conflict resolver."""
        return self._conflict_resolver.resolve_merge_conflicts

    @property
    def _get_judge_result(self) -> Callable[..., JudgeResult | None]:
        """Backward-compatible access to judge result helper."""
        return self._post_merge._get_judge_result

    @property
    def _create_verification_issue(self) -> Callable[..., Coroutine[Any, Any, int]]:
        """Backward-compatible access to verification issue creation."""
        return self._post_merge._create_verification_issue

    @property
    def _run_post_merge_hooks(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to post-merge hooks."""
        return self._post_merge._run_post_merge_hooks

    @property
    def _save_conflict_transcript(self) -> Callable[..., None]:
        """Backward-compatible access to conflict transcript saving."""
        return self._conflict_resolver._save_conflict_transcript

    @property
    def _maybe_summarize_conflict(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to conflict summary."""
        return self._conflict_resolver._maybe_summarize_conflict
