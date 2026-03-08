"""Review processing for the HydraFlow orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from visual_validator import VisualValidator

from baseline_policy import BaselinePolicy
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from harness_insights import FailureCategory, HarnessInsightStore
from issue_store import IssueStore
from merge_conflict_resolver import MergeConflictResolver
from models import (
    BaselineApprovalResult,
    ConflictResolutionResult,
    JudgeResult,
    PipelineStage,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    StatusCallback,
    Task,
    VisualEvidence,
    VisualScreenResult,
    VisualValidationDecision,
    VisualValidationReport,
)
from phase_utils import (
    adr_validation_reasons,
    is_adr_issue_title,
    load_existing_adr_topics,
    normalize_adr_topic,
    publish_review_status,
    record_harness_failure,
    release_batch_in_flight,
    run_concurrent_batch,
    safe_file_memory_suggestion,
    store_lifecycle,
)
from post_merge_handler import PostMergeHandler
from pr_manager import PRManager, SelfReviewError
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
from subprocess_util import AuthenticationError, CreditExhaustedError
from task_source import TaskTransitioner
from workspace import WorkspaceManager

logger = logging.getLogger("hydraflow.review_phase")


@dataclass(slots=True)
class ReviewGuardContext:
    """Successful result from _run_initial_guards."""

    task: Task
    worktree_path: Path


@dataclass(slots=True)
class PreReviewContext:
    """Artifacts captured before running the reviewer."""

    diff: str
    visual_decision: VisualValidationDecision | None
    code_scanning_alerts: list[dict[str, Any]] | None


class ReviewPhase:
    """Runs reviewer agents on PRs, merging approved ones inline."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        worktrees: WorkspaceManager,
        reviewers: ReviewRunner,
        prs: PRManager,
        stop_event: asyncio.Event,
        store: IssueStore,
        event_bus: EventBus | None = None,
        harness_insights: HarnessInsightStore | None = None,
        conflict_resolver: MergeConflictResolver | None = None,
        post_merge: PostMergeHandler | None = None,
        update_bg_worker_status: StatusCallback | None = None,
        baseline_policy: BaselinePolicy | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._worktrees = worktrees
        self._reviewers = reviewers
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._stop_event = stop_event
        self._store = store
        self._bus = event_bus or EventBus()
        self._update_bg_worker_status = update_bg_worker_status
        self._harness_insights = harness_insights
        self._insights = ReviewInsightStore(config.memory_dir)
        self._active_issues: set[int] = set()
        self._active_issues_lock = asyncio.Lock()
        self._conflict_resolver = conflict_resolver or MergeConflictResolver(
            config=config,
            worktrees=worktrees,
            agents=None,
            prs=prs,
            event_bus=self._bus,
            state=state,
            summarizer=None,
        )
        self._post_merge = post_merge or PostMergeHandler(
            config=config,
            state=state,
            prs=prs,
            event_bus=self._bus,
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )
        self._baseline_policy = baseline_policy
        self._visual_validator: VisualValidator | None = None
        if config.visual_validation_enabled:
            from visual_validator import VisualValidator  # noqa: PLC0415

            self._visual_validator = VisualValidator(config)

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
                async with self._active_issues_lock:
                    self._active_issues.add(pr.issue_number)
                    self._state.set_active_issue_numbers(list(self._active_issues))
                async with store_lifecycle(self._store, pr.issue_number, "review"):
                    try:
                        return await self._review_one_inner(idx, pr, issue_map)
                    except (AuthenticationError, CreditExhaustedError, MemoryError):
                        raise
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
                        async with self._active_issues_lock:
                            self._active_issues.discard(pr.issue_number)
                            self._state.set_active_issue_numbers(
                                list(self._active_issues)
                            )

        try:
            return await run_concurrent_batch(prs, _review_one, self._stop_event)
        finally:
            release_batch_in_flight(self._store, {pr.issue_number for pr in prs})

    async def review_adrs(self, issues: list[Task]) -> list[ReviewResult]:
        """Review ADR issues that intentionally have no PR."""
        adr_issues = [issue for issue in issues if is_adr_issue_title(issue.title)]
        if not adr_issues:
            return []

        results: list[ReviewResult] = []
        for issue in adr_issues:
            if self._stop_event.is_set():
                break
            async with store_lifecycle(self._store, issue.id, "review"):
                results.append(await self._review_single_adr(issue))
        return results

    async def _review_single_adr(self, issue: Task) -> ReviewResult:
        """Validate ADR quality and either finalize or escalate to HITL."""
        topic_key = normalize_adr_topic(issue.title)
        existing = load_existing_adr_topics(self._config.repo_root)
        if topic_key and topic_key in existing:
            await self._transitioner.post_comment(
                issue.id,
                f"## Closing as Duplicate\n\n"
                f"An ADR already exists for this topic in `docs/adr/`. "
                f"Normalized topic: *{topic_key}*",
            )
            await self._transitioner.close_task(issue.id)
            self._state.mark_issue(issue.id, "completed")
            logger.info(
                "ADR issue #%d closed as duplicate — topic %r exists in docs/adr/",
                issue.id,
                topic_key,
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                verdict=ReviewVerdict.APPROVE,
                summary="Closed as duplicate ADR",
                merged=True,
            )
        reasons = adr_validation_reasons(issue.body)
        decision_detail = self._extract_adr_section(issue.body, "decision")
        if len(decision_detail.strip()) < 60:
            reasons.append(
                "Decision section lacks actionable detail (minimum 60 chars)"
            )

        if reasons:
            await self._escalate_to_hitl(
                issue.id,
                None,
                cause="ADR review failed validation",
                origin_label=self._config.review_label[0],
                comment=(
                    "## ADR Review Failed\n\n"
                    "The ADR draft is not ready for finalization.\n\n"
                    "**Required fixes:**\n"
                    + "\n".join(f"- {reason}" for reason in reasons)
                ),
                post_on_pr=False,
                event_cause="adr_review_failed",
                task=issue,
            )
            return ReviewResult(
                pr_number=0,
                issue_number=issue.id,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                summary="ADR review failed validation",
            )

        await self._transitioner.post_comment(
            issue.id,
            "## ADR Review Approved\n\n"
            "ADR draft validated and finalized by the review phase.\n\n"
            "Closing issue as complete.",
        )
        await self._prs.swap_pipeline_labels(issue.id, self._config.fixed_label[0])
        await self._transitioner.close_task(issue.id)
        self._state.mark_issue(issue.id, "completed")
        self._state.record_issue_completed()
        self._state.increment_session_counter("reviewed")
        return ReviewResult(
            pr_number=0,
            issue_number=issue.id,
            verdict=ReviewVerdict.APPROVE,
            summary="ADR review approved",
            merged=True,
        )

    @staticmethod
    def _extract_adr_section(body: str, heading: str) -> str:
        """Extract a markdown section body by heading name (case-insensitive)."""
        pattern = (
            r"(?ims)^##\s+" + re.escape(heading) + r"\s*\n(?P<section>.*?)(?=^##\s+|\Z)"
        )
        match = re.search(pattern, body)
        return match.group("section").strip() if match else ""

    async def _prepare_review_worktree(
        self, pr: PRInfo, task: Task, idx: int
    ) -> Path | None:
        """Ensure worktree exists and main is merged. Returns path or None on conflict."""
        wt_path = self._config.worktree_path_for_issue(pr.issue_number)
        if not wt_path.exists():
            wt_path = await self._worktrees.create(pr.issue_number, pr.branch)
        merged = await self._merge_with_main(pr, task, wt_path, idx)
        if not merged:
            return None
        return wt_path

    async def _fetch_code_scanning_alerts(self, pr: PRInfo) -> list[dict] | None:
        """Fetch code scanning alerts if the feature is enabled.

        Returns the alert list or ``None`` when disabled / on error.
        """
        if not self._config.code_scanning_enabled:
            return None
        try:
            alerts = await self._prs.fetch_code_scanning_alerts(pr.branch)
            if alerts:
                logger.info(
                    "PR #%d: fetched %d code scanning alert(s)",
                    pr.number,
                    len(alerts),
                )
            return alerts or None
        except Exception:  # noqa: BLE001
            logger.debug(
                "Could not fetch code scanning alerts for PR #%d",
                pr.number,
                exc_info=True,
            )
            return None

    async def _check_baseline_policy(
        self, pr: PRInfo, task: Task
    ) -> BaselineApprovalResult | None:
        """Run baseline policy check if a policy is configured.

        Returns the approval result or ``None`` when no policy is active.
        """
        if self._baseline_policy is None:
            return None
        try:
            changed_files = await self._prs.get_pr_diff_names(pr.number)
            if not changed_files:
                return None
            pr_approvers = await self._prs.get_pr_approvers(pr.number)
            commit_sha = await self._prs.get_pr_head_sha(pr.number)
            return await self._baseline_policy.check_approval(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                changed_files=changed_files,
                pr_approvers=pr_approvers,
                commit_sha=commit_sha,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Baseline policy check failed for PR #%d — failing closed to protect baseline integrity",
                pr.number,
                exc_info=True,
            )
            return BaselineApprovalResult(
                approved=False,
                requires_approval=True,
                reason="Baseline policy check failed — manual review required",
            )

    async def _review_one_inner(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
    ) -> ReviewResult:
        """Core review logic for a single PR — called inside the semaphore."""
        await self._publish_review_status(pr, idx, "start")

        guards = await self._run_initial_guards(idx, pr, issue_map)
        if isinstance(guards, ReviewResult):
            return guards

        pre_review = await self._run_pre_review_checks(pr, guards.task)
        if isinstance(pre_review, ReviewResult):
            return pre_review

        result = await self._run_and_post_review(
            pr,
            guards.task,
            guards.worktree_path,
            pre_review.diff,
            idx,
            code_scanning_alerts=pre_review.code_scanning_alerts,
        )

        return await self._run_post_review_actions(
            pr,
            guards.task,
            guards.worktree_path,
            result,
            pre_review,
            idx,
        )

    async def _run_initial_guards(
        self,
        idx: int,
        pr: PRInfo,
        issue_map: dict[int, Task],
    ) -> ReviewResult | ReviewGuardContext:
        """Handle prerequisite guards before running a review."""
        task = issue_map.get(pr.issue_number)
        if task is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Issue not found",
            )

        wt_path = await self._prepare_review_worktree(pr, task, idx)
        if wt_path is None:
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Merge conflicts with main — escalated to HITL",
            )

        return ReviewGuardContext(task=task, worktree_path=wt_path)

    async def _run_pre_review_checks(
        self,
        pr: PRInfo,
        task: Task,
    ) -> ReviewResult | PreReviewContext:
        """Run baseline, visual, and delta checks before invoking reviewer."""
        diff = await self._prs.get_pr_diff(pr.number)

        baseline_result = await self._check_baseline_policy(pr, task)
        if (
            baseline_result
            and baseline_result.requires_approval
            and not baseline_result.approved
        ):
            await self._escalate_to_hitl(
                pr.issue_number,
                pr.number,
                cause="Baseline changes require approval",
                origin_label=self._config.review_label[0],
                comment=(
                    "## Baseline Policy Violation\n\n"
                    "This PR modifies visual baseline files that require "
                    "explicit approval from a designated owner before merging.\n\n"
                    "**Changed baseline files:**\n"
                    + "\n".join(f"- `{f}`" for f in baseline_result.changed_files)
                    + "\n\nPlease request a review from an authorized baseline approver."
                ),
                event_cause="baseline_approval_required",
                task=task,
            )
            return ReviewResult(
                pr_number=pr.number,
                issue_number=pr.issue_number,
                summary="Baseline changes require approval — escalated to HITL",
            )

        visual_decision = self._compute_visual_validation(diff, task)
        if visual_decision is not None and pr.number > 0:
            from visual_validation import (  # noqa: PLC0415
                format_visual_validation_comment,
            )

            await self._prs.post_pr_comment(
                pr.number,
                format_visual_validation_comment(visual_decision),
            )

        code_scanning_alerts = await self._fetch_code_scanning_alerts(pr)
        await self._run_delta_verification(pr, diff)

        return PreReviewContext(
            diff=diff,
            visual_decision=visual_decision,
            code_scanning_alerts=code_scanning_alerts,
        )

    async def _run_post_review_actions(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        pre_review: PreReviewContext,
        worker_id: int,
    ) -> ReviewResult:
        """Handle re-review, visual validation, verdict flow, and cleanup."""
        diff = pre_review.diff
        code_scanning_alerts = pre_review.code_scanning_alerts

        if result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            if result.fixes_made:
                result, diff = await self._handle_self_fix_re_review(
                    pr,
                    task,
                    wt_path,
                    result,
                    diff,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )
            else:
                result, diff = await self._attempt_review_fix(
                    pr,
                    task,
                    wt_path,
                    result,
                    diff,
                    worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )

        visual_report = await self._run_visual_validation(pr, wt_path, worker_id)
        if visual_report and visual_report.has_failures:
            result = await self._handle_visual_failure(
                pr,
                task,
                result,
                visual_report,
                worker_id,
            )

        await self._record_review_outcome(pr, result)

        skip_worktree_cleanup = False
        if result.verdict == ReviewVerdict.APPROVE and pr.number > 0:
            await self._handle_approved_merge(
                pr,
                task,
                result,
                diff,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
                visual_decision=pre_review.visual_decision,
            )
        elif result.verdict in (
            ReviewVerdict.REQUEST_CHANGES,
            ReviewVerdict.COMMENT,
        ):
            skip_worktree_cleanup = await self._handle_rejected_review(
                pr,
                task,
                result,
                worker_id,
            )

        await self._cleanup_worktree(pr, result, skip_worktree_cleanup)
        return result

    def _compute_visual_validation(
        self, diff: str, task: Task
    ) -> VisualValidationDecision | None:
        """Compute the visual validation decision for a PR diff."""
        if not self._config.visual_validation_enabled:
            return None
        from visual_validation import compute_visual_validation  # noqa: PLC0415

        return compute_visual_validation(
            self._config,
            diff,
            issue_labels=task.tags,
            issue_comments=task.comments,
        )

    async def _check_sha_skip_guard(self, pr: PRInfo) -> ReviewResult | None:
        """Return a skip result if no new commits since last review, else None."""
        current_sha = await self._prs.get_pr_head_sha(pr.number)
        if isinstance(current_sha, str) and current_sha:
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
        return None

    async def _run_visual_validation(
        self, pr: PRInfo, wt_path: Path, worker_id: int
    ) -> VisualValidationReport | None:
        """Run visual validation if enabled. Returns None when disabled or on error."""
        if self._visual_validator is None:
            return None
        try:
            await self._publish_review_status(pr, worker_id, "visual_check")
            # The check_fn is a placeholder — real implementations would inject
            # an actual screenshot capture + diffing callable.  For now the
            # validator infrastructure is wired up but produces an empty report
            # unless a check function is supplied externally.
            report = await self._visual_validator.validate_screens(
                [], self._noop_visual_check
            )
            if report.screens:
                logger.info(
                    "PR #%d: visual validation %s (%d screens, %d retries)",
                    pr.number,
                    report.overall_verdict.value,
                    len(report.screens),
                    report.total_retries,
                )
            return report
        except Exception:  # noqa: BLE001
            logger.warning(
                "Visual validation failed for PR #%d — skipping",
                pr.number,
                exc_info=True,
            )
            return None

    @staticmethod
    async def _noop_visual_check(screen_name: str) -> VisualScreenResult:
        """Default no-op visual check (placeholder for real implementation)."""
        return VisualScreenResult(screen_name=screen_name, diff_ratio=0.0)

    async def _handle_visual_failure(
        self,
        pr: PRInfo,
        task: Task,
        result: ReviewResult,
        report: VisualValidationReport,
        worker_id: int,
    ) -> ReviewResult:
        """Handle a visual validation failure — escalate to HITL with report details."""
        summary_text = report.format_summary()

        if report.infra_failures > 0 and report.visual_diffs == 0:
            cause = "Visual validation infrastructure failure (not a visual diff)"
        else:
            cause = "Visual validation detected failures"

        await self._publish_review_status(pr, worker_id, "escalating")
        await self._escalate_to_hitl(
            task.id,
            pr.number,
            cause=cause,
            origin_label=self._config.review_label[0],
            comment=(
                f"**Visual validation failed** — escalating to human review.\n\n"
                f"{summary_text}"
            ),
            event_cause="visual_validation_failed",
            extra_event_data={
                "visual_verdict": report.overall_verdict.value,
                "visual_retries": report.total_retries,
                "infra_failures": report.infra_failures,
                "visual_diffs": report.visual_diffs,
            },
            task=task,
        )
        result.verdict = ReviewVerdict.REQUEST_CHANGES
        result.summary = f"Visual validation failed: {cause}"
        return result

    async def _record_review_outcome(self, pr: PRInfo, result: ReviewResult) -> None:
        """Record all post-review state: verdicts, SHA, duration, insights.

        Also records a harness failure for any non-APPROVE verdict.
        """
        self._state.mark_pr(pr.number, result.verdict.value)
        self._state.mark_issue(pr.issue_number, "reviewed")
        self._state.record_review_verdict(result.verdict.value, result.fixes_made)
        if result.verdict == ReviewVerdict.APPROVE:
            self._state.increment_session_counter("reviewed")

        post_review_sha = await self._prs.get_pr_head_sha(pr.number)
        if isinstance(post_review_sha, str) and post_review_sha:
            self._state.set_last_reviewed_sha(pr.issue_number, post_review_sha)

        if result.duration_seconds > 0:
            self._state.record_review_duration(result.duration_seconds)
        await self._record_review_insight(result)
        if result.verdict != ReviewVerdict.APPROVE:
            record_harness_failure(
                self._harness_insights,
                pr.issue_number,
                FailureCategory.REVIEW_REJECTION,
                f"Review verdict: {result.verdict.value}. {result.summary[:200]}",
                stage=PipelineStage.REVIEW,
                pr_number=pr.number,
            )

    async def _cleanup_worktree(
        self, pr: PRInfo, result: ReviewResult, skip: bool
    ) -> None:
        """Destroy the worktree unless it should be preserved."""
        # Preserve worktrees for interrupted reviews so work can be resumed.
        # If the PR was already merged, the worktree is no longer needed.
        if self._stop_event.is_set() and not result.merged:
            skip = True

        if not skip:
            try:
                await self._worktrees.post_work_cleanup(pr.issue_number)
                self._state.remove_worktree(pr.issue_number)
            except RuntimeError as exc:
                logger.warning(
                    "Could not clean up worktree for issue #%d: %s",
                    pr.issue_number,
                    exc,
                )

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
        code_scanning_alerts: list[dict] | None = None,
    ) -> ReviewResult:
        """Run the reviewer, push fixes, post summary, submit formal review."""
        result = await self._reviewers.review(
            pr,
            issue,
            wt_path,
            diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
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
                pr,
                issue,
                wt_path,
                diff,
                result,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
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
        code_scanning_alerts: list[dict] | None = None,
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
                pr,
                issue,
                wt_path,
                updated_diff,
                worker_id=worker_id,
                code_scanning_alerts=code_scanning_alerts,
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
        except (AuthenticationError, CreditExhaustedError, MemoryError):
            raise
        except Exception:
            logger.warning(
                "PR #%d: self-fix re-review failed — falling back to original rejection",
                pr.number,
                exc_info=True,
            )
            return result, diff

    async def _attempt_review_fix(
        self,
        pr: PRInfo,
        task: Task,
        wt_path: Path,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        code_scanning_alerts: list[dict] | None = None,
    ) -> tuple[ReviewResult, str]:
        """Spin up a sub-agent to fix review findings, then re-review.

        Tries up to 2 fix-then-review cycles. If the fix agent makes
        changes and the re-review approves, returns the upgraded result.
        Otherwise falls through to the normal rejection path.
        """
        max_fix_attempts = 2

        for attempt in range(1, max_fix_attempts + 1):
            logger.info(
                "PR #%d: attempting review fix %d/%d",
                pr.number,
                attempt,
                max_fix_attempts,
            )
            try:
                await self._publish_review_status(pr, worker_id, "fixing_review")

                fix_result = await self._reviewers.fix_review_findings(
                    pr,
                    task,
                    wt_path,
                    result.summary,
                    worker_id=worker_id,
                )

                if not fix_result.fixes_made:
                    logger.info(
                        "PR #%d: fix agent made no changes on attempt %d — giving up",
                        pr.number,
                        attempt,
                    )
                    break

                # Push the fixes
                await self._prs.push_branch(wt_path, pr.branch)

                # Re-review
                await self._publish_review_status(pr, worker_id, "re_reviewing")
                updated_diff = await self._prs.get_pr_diff(pr.number)
                re_result = await self._reviewers.review(
                    pr,
                    task,
                    wt_path,
                    updated_diff,
                    worker_id=worker_id,
                    code_scanning_alerts=code_scanning_alerts,
                )

                if re_result.fixes_made:
                    await self._prs.push_branch(wt_path, pr.branch)

                if re_result.verdict == ReviewVerdict.APPROVE:
                    logger.info(
                        "PR #%d: review fix attempt %d succeeded — upgrading to APPROVE",
                        pr.number,
                        attempt,
                    )
                    return re_result, updated_diff

                # Still rejected — use the new feedback for the next attempt
                logger.info(
                    "PR #%d: review fix attempt %d still %s — %s",
                    pr.number,
                    attempt,
                    re_result.verdict.value,
                    "retrying" if attempt < max_fix_attempts else "falling through",
                )
                result = re_result
                diff = updated_diff

            except (AuthenticationError, CreditExhaustedError, MemoryError):
                raise
            except Exception:
                logger.warning(
                    "PR #%d: review fix attempt %d failed — falling back to rejection",
                    pr.number,
                    attempt,
                    exc_info=True,
                )
                break

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
        code_scanning_alerts: list[dict] | None = None,
        visual_decision: VisualValidationDecision | None = None,
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
            code_scanning_alerts=code_scanning_alerts,
            visual_gate_fn=self.check_visual_gate,
            visual_decision=visual_decision,
            merge_conflict_fix_fn=self._attempt_post_merge_conflict_fix,
        )

    async def _attempt_post_merge_conflict_fix(
        self,
        pr: PRInfo,
        issue: Task,
        worker_id: int,
    ) -> bool:
        """Attempt conflict resolution after a failed GitHub merge.

        This keeps the standard review path aligned with unsticker behavior:
        resolve merge conflicts on the branch, push updates, then retry merge.
        """
        wt_path = self._config.worktree_path_for_issue(pr.issue_number)
        if not wt_path.exists():
            wt_path = await self._worktrees.create(pr.issue_number, pr.branch)

        resolution = await self._conflict_resolver.resolve_merge_conflicts(
            pr,
            issue,
            wt_path,
            worker_id=worker_id,
            source="post_merge",
        )
        if not resolution.success:
            return False

        if resolution.used_rebuild:
            await self._prs.push_branch(
                self._config.worktree_path_for_issue(pr.issue_number),
                pr.branch,
                force=True,
            )
        else:
            await self._prs.push_branch(wt_path, pr.branch)
        return True

    async def check_visual_gate(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        worker_id: int,
    ) -> bool:
        """Run visual validation gate before merge finalization.

        Returns True if merge may proceed, False to block.
        When the gate is bypassed an audit event is emitted.
        """
        start = time.monotonic()

        if not self._config.visual_gate_enabled:
            return True

        # Emergency bypass — allow merge but log an audit event
        if self._config.visual_gate_bypass:
            logger.warning(
                "PR #%d: visual gate BYPASSED (emergency kill-switch)",
                pr.number,
            )
            if self._bus:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.VISUAL_GATE,
                        data={
                            "pr": pr.number,
                            "issue": issue.id,
                            "worker": worker_id,
                            "verdict": "bypass",
                            "reason": "emergency kill-switch active",
                            "runtime_seconds": round(time.monotonic() - start, 3),
                        },
                    )
                )
            result.visual_passed = True
            return True

        verdict, artifacts, reason = await self._invoke_visual_pipeline(
            pr, issue, worker_id
        )

        runtime = round(time.monotonic() - start, 3)

        # Emit gate telemetry
        if self._bus:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.VISUAL_GATE,
                    data={
                        "pr": pr.number,
                        "issue": issue.id,
                        "worker": worker_id,
                        "verdict": verdict,
                        "reason": reason,
                        "runtime_seconds": runtime,
                        "retries": 0,
                        "artifact_count": len(artifacts),
                        "artifacts": artifacts,
                    },
                )
            )

        if verdict == "pass":
            result.visual_passed = True
            # Post sign-off comment with evidence links
            sign_off = (
                f"**Visual Gate: PASSED**\n\n"
                f"Visual validation completed successfully.\n"
                f"Verdict: `{verdict}` | Runtime: {runtime}s"
            )
            if artifacts:
                sign_off += "\n\n**Artifacts:**\n"
                for name, link in artifacts.items():
                    sign_off += f"- [{name}]({link})\n"
            try:
                await self._prs.post_pr_comment(pr.number, sign_off)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "PR #%d: could not post visual gate sign-off comment",
                    pr.number,
                    exc_info=True,
                )
            return True

        # Warn/fail blocks merge and escalates to HITL
        result.visual_passed = False
        logger.warning(
            "PR #%d: visual gate BLOCKED (verdict=%s) — blocking merge",
            pr.number,
            verdict,
        )
        try:
            await self._prs.post_pr_comment(
                pr.number,
                f"**Visual Gate: BLOCKED**\n\n"
                f"Verdict: `{verdict}` — {reason}\n"
                f"Escalating to human review.",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "PR #%d: could not post visual gate block comment",
                pr.number,
                exc_info=True,
            )
        await self._escalate_to_hitl(
            pr.issue_number,
            pr.number,
            cause=f"Visual gate {verdict}",
            origin_label=self._config.review_label[0],
            comment=f"Visual gate verdict: {verdict} — {reason}",
            event_cause="visual_gate_failed",
            task=issue,
        )
        return False

    async def _invoke_visual_pipeline(
        self,
        pr: PRInfo,
        issue: Task,  # noqa: ARG002
        worker_id: int,  # noqa: ARG002
    ) -> tuple[str, dict[str, str], str]:
        """Invoke the external visual validation service.

        Returns (verdict, artifacts, reason).
        Override or mock this method in tests to exercise fail paths.
        In production this will call an external visual validation service.

        WARNING: This is a placeholder stub. With visual_gate_enabled=True the
        gate will always pass until this method is connected to a real service.
        """
        logger.warning(
            "PR #%d: _invoke_visual_pipeline is a stub — visual gate is not connected "
            "to a real validation service; verdict will always be 'pass'",
            pr.number,
        )
        return "pass", {}, "visual validation passed"

    async def _run_ci_wait_attempt(
        self, pr: PRInfo, attempt: int, worker_id: int
    ) -> tuple[bool, str]:
        """Poll CI once. Return (passed, message)."""
        await self._publish_review_status(pr, worker_id, "ci_wait")
        return await self._prs.wait_for_ci(
            pr.number,
            self._config.ci_check_timeout,
            self._config.ci_poll_interval,
            self._stop_event,
        )

    async def _run_ci_fix_attempt(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        summary: str,
        worker_id: int,
        attempt: int,
        *,
        ci_logs: str = "",
        code_scanning_alerts: list[dict] | None = None,
    ) -> bool:
        """Run the CI fix agent. Return True if changes were made and pushed."""
        await self._publish_review_status(pr, worker_id, "ci_fix")
        fix_result = await self._reviewers.fix_ci(
            pr,
            issue,
            wt_path,
            summary,
            attempt=attempt,
            worker_id=worker_id,
            ci_logs=ci_logs,
            code_scanning_alerts=code_scanning_alerts,
        )
        if not fix_result.fixes_made:
            logger.info(
                "CI fix agent made no changes for PR #%d — stopping retries",
                pr.number,
            )
            return False
        await self._prs.push_branch(wt_path, pr.branch)
        return True

    async def _escalate_ci_failure(
        self,
        pr: PRInfo,
        issue: Task,
        logs: str,
        ci_fix_attempts: int,
    ) -> None:
        """Record state, record harness failure, escalate to HITL."""
        self._state.record_ci_fix_rounds(ci_fix_attempts)
        record_harness_failure(
            self._harness_insights,
            issue.id,
            FailureCategory.CI_FAILURE,
            f"CI failed after {ci_fix_attempts} fix attempt(s): {logs[:200]}",
            pr_number=pr.number,
            stage=PipelineStage.REVIEW,
        )
        cause = f"CI failed after {ci_fix_attempts} fix attempt(s): {logs[:200]}"
        await self._escalate_to_hitl(
            issue.id,
            pr.number,
            cause=cause,
            origin_label=self._config.review_label[0],
            comment=(
                f"**CI failed** after {ci_fix_attempts} fix attempt(s).\n\n"
                f"Last failure: {logs}\n\n"
                f"PR not merged — escalating to human review."
            ),
            event_cause="ci_failed",
            extra_event_data={"ci_fix_attempts": ci_fix_attempts},
            task=issue,
        )

    async def wait_and_fix_ci(
        self,
        pr: PRInfo,
        issue: Task,
        wt_path: Path,
        result: ReviewResult,
        worker_id: int,
        code_scanning_alerts: list[dict] | None = None,
    ) -> bool:
        """Wait for CI and attempt fixes if it fails.

        Returns *True* if CI passed and the PR should be merged.
        Mutates *result* to set ``ci_passed`` and ``ci_fix_attempts``.
        """
        max_attempts = self._config.max_ci_fix_attempts
        summary = ""

        for attempt in range(max_attempts + 1):
            passed, summary = await self._run_ci_wait_attempt(pr, attempt, worker_id)
            if passed:
                result.ci_passed = True
                return True

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

            made_changes = await self._run_ci_fix_attempt(
                pr,
                issue,
                wt_path,
                summary,
                worker_id,
                attempt + 1,
                ci_logs=ci_logs,
                code_scanning_alerts=code_scanning_alerts,
            )
            result.ci_fix_attempts += 1
            if not made_changes:
                break

        result.ci_passed = False
        if result.transcript:
            await safe_file_memory_suggestion(
                result.transcript,
                "ci_fix_failure",
                f"PR #{pr.number}",
                self._config,
                self._prs,
                self._state,
            )
        await self._publish_review_status(pr, worker_id, "escalating")
        await self._escalate_ci_failure(pr, issue, summary, result.ci_fix_attempts)
        return False

    async def _record_review_insight(self, result: ReviewResult) -> None:
        """Record a review result and file improvement proposals if patterns emerge.

        Wrapped in try/except so insight failures never interrupt the review flow.
        """
        status = "ok"
        details: dict[str, object] = {
            "issue_number": result.issue_number,
            "pr_number": result.pr_number,
        }
        try:
            record = ReviewRecord(
                pr_number=result.pr_number,
                issue_number=result.issue_number,
                timestamp=datetime.now(UTC).isoformat(),
                verdict=result.verdict,
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
                labels = self._config.improve_label[:1]
                await self._transitioner.create_task(title, body, labels)
                self._insights.mark_category_proposed(category)
        except Exception:  # noqa: BLE001
            status = "error"
            details["error"] = "review insight recording failed"
            logger.warning(
                "Review insight recording failed for PR #%d",
                result.pr_number,
                exc_info=True,
            )
        finally:
            if self._update_bg_worker_status:
                try:
                    self._update_bg_worker_status("review_insights", status, details)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "review_insights status callback failed for PR #%d",
                        result.pr_number,
                        exc_info=True,
                    )

    async def _publish_review_status(
        self, pr: PRInfo, worker_id: int, status: str
    ) -> None:
        """Emit a REVIEW_UPDATE event with the given status."""
        await publish_review_status(self._bus, pr, worker_id, status)

    async def _escalate_to_hitl(
        self,
        issue_number: int,
        pr_number: int | None,
        cause: str,
        origin_label: str,
        *,
        comment: str,
        post_on_pr: bool = True,
        event_cause: str = "",
        extra_event_data: dict[str, object] | None = None,
        task: Task | None = None,
        visual_evidence: VisualEvidence | None = None,
    ) -> None:
        """Record HITL escalation state, swap labels, post comment, publish event."""
        self._state.set_hitl_origin(issue_number, origin_label)
        self._state.set_hitl_cause(issue_number, cause)
        self._state.record_hitl_escalation()
        if visual_evidence is not None:
            self._state.set_hitl_visual_evidence(issue_number, visual_evidence)

        await self._transitioner.transition(issue_number, "hitl", pr_number=pr_number)
        if task is not None:
            self._store.enqueue_transition(task, "hitl")

        if post_on_pr and pr_number and pr_number > 0:
            await self._prs.post_pr_comment(pr_number, comment)
        else:
            await self._prs.post_comment(issue_number, comment)

        event_data: dict[str, object] = {
            "issue": issue_number,
            "status": "escalated",
            "role": "reviewer",
            "cause": event_cause or cause,
        }
        if pr_number and pr_number > 0:
            event_data["pr"] = pr_number
        if visual_evidence is not None:
            event_data["visual_evidence"] = visual_evidence.model_dump()
        if extra_event_data:
            event_data.update(extra_event_data)
        await self._bus.publish(
            HydraFlowEvent(type=EventType.HITL_ESCALATION, data=event_data)
        )

    async def escalate_visual_failure(
        self,
        issue_number: int,
        pr_number: int | None,
        evidence: VisualEvidence,
        *,
        task: Task | None = None,
    ) -> None:
        """Escalate a visual validation failure to HITL with evidence.

        Convenience wrapper around ``_escalate_to_hitl`` that records the
        visual evidence, picks the appropriate failure category, and
        builds a descriptive comment.
        """
        fail_items = [i for i in evidence.items if i.status == "fail"]
        warn_items = [i for i in evidence.items if i.status == "warn"]

        category = (
            FailureCategory.VISUAL_FAIL if fail_items else FailureCategory.VISUAL_WARN
        )
        record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            evidence.summary or f"{len(fail_items)} fail(s), {len(warn_items)} warn(s)",
            pr_number=pr_number or 0,
            stage=PipelineStage.REVIEW,
        )

        screen_lines = []
        for item in evidence.items:
            if item.status in ("fail", "warn"):
                label = "FAIL" if item.status == "fail" else "WARN"
                screen_lines.append(
                    f"- **{item.screen_name}** — {item.diff_percent:.1f}% diff [{label}]"
                )

        comment = (
            "## Visual Validation Failed\n\n"
            + (evidence.summary + "\n\n" if evidence.summary else "")
            + (
                "**Affected screens:**\n" + "\n".join(screen_lines) + "\n\n"
                if screen_lines
                else ""
            )
            + (f"[View run]({evidence.run_url})\n\n" if evidence.run_url else "")
            + "Escalating to human review."
        )

        cause = (
            f"Visual validation failed: {evidence.summary}"
            if evidence.summary
            else "Visual validation failed"
        )

        await self._escalate_to_hitl(
            issue_number,
            pr_number,
            cause=cause,
            origin_label=self._config.review_label[0],
            comment=comment,
            event_cause="visual_validation_failed",
            task=task,
            visual_evidence=evidence,
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
        code_scanning_alerts: list[dict] | None = None,
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
            pr,
            issue,
            wt_path,
            diff,
            worker_id=worker_id,
            code_scanning_alerts=code_scanning_alerts,
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
        task: Task,
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
            await self._transitioner.transition(
                pr.issue_number, "ready", pr_number=pr.number
            )
            self._store.enqueue_transition(task, "ready")

            await self._transitioner.post_comment(
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
            record_harness_failure(
                self._harness_insights,
                pr.issue_number,
                FailureCategory.HITL_ESCALATION,
                f"Review fix cap exceeded after {max_attempts} attempt(s)",
                stage=PipelineStage.REVIEW,
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
                task=task,
            )
            if result.transcript:
                await safe_file_memory_suggestion(
                    result.transcript,
                    "review_fix_cap_exceeded",
                    f"PR #{pr.number}",
                    self._config,
                    self._prs,
                    self._state,
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
        """Delegate to :func:`phase_utils.record_harness_failure` (backward compat)."""
        record_harness_failure(
            self._harness_insights,
            issue_number,
            category,
            details,
            pr_number=pr_number,
            stage=PipelineStage.REVIEW,
        )

    # Delegate properties for backward compatibility in tests
    @property
    def _resolve_merge_conflicts(
        self,
    ) -> Callable[..., Coroutine[Any, Any, ConflictResolutionResult]]:
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
        return self._conflict_resolver.save_conflict_transcript

    @property
    def _maybe_summarize_conflict(self) -> Callable[..., Coroutine[Any, Any, None]]:
        """Backward-compatible access to conflict summary."""
        return self._conflict_resolver._maybe_summarize_conflict
