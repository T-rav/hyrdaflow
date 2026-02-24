"""Post-merge handling for the HydraFlow review pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, TypeVar

from acceptance_criteria import AcceptanceCriteriaGenerator
from config import HydraFlowConfig
from epic import EpicCompletionChecker
from events import EventBus, EventType, HydraFlowEvent
from models import (
    CriterionVerdict,
    GitHubIssue,
    JudgeResult,
    JudgeVerdict,
    PRInfo,
    ReviewResult,
    VerificationCriterion,
)
from pr_manager import PRManager
from retrospective import RetrospectiveCollector
from state import StateTracker
from verification import format_verification_issue_body
from verification_judge import VerificationJudge

logger = logging.getLogger("hydraflow.post_merge_handler")

_T = TypeVar("_T")


class PostMergeHandler:
    """Handles post-merge operations: AC generation, retrospective, judge, epic checks."""

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
        event_bus: EventBus,
        ac_generator: AcceptanceCriteriaGenerator | None,
        retrospective: RetrospectiveCollector | None,
        verification_judge: VerificationJudge | None,
        epic_checker: EpicCompletionChecker | None,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._bus = event_bus
        self._ac_generator = ac_generator
        self._retrospective = retrospective
        self._verification_judge = verification_judge
        self._epic_checker = epic_checker

    async def handle_approved(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        ci_gate_fn: Callable[..., Coroutine[Any, Any, bool]],
        escalate_fn: Callable[..., Coroutine[Any, Any, None]],
        publish_fn: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Attempt merge for an approved PR (with optional CI gate)."""
        should_merge = True
        if self._config.max_ci_fix_attempts > 0:
            should_merge = await ci_gate_fn(
                pr,
                issue,
                self._config.worktree_base / f"issue-{pr.issue_number}",
                result,
                worker_id,
            )
        if not should_merge:
            return

        await publish_fn(pr, worker_id, "merging")
        success = await self._prs.merge_pr(pr.number)
        if success:
            result.merged = True
            self._state.mark_issue(pr.issue_number, "merged")
            self._state.record_pr_merged()
            self._state.record_issue_completed()
            if result.ci_fix_attempts > 0:
                self._state.record_ci_fix_rounds(result.ci_fix_attempts)
                for _ in range(result.ci_fix_attempts):
                    self._state.record_stage_retry(pr.issue_number, "ci_fix")
            # Track time-to-merge
            if issue.created_at:
                try:
                    created = datetime.fromisoformat(issue.created_at)
                    merge_seconds = (datetime.now(UTC) - created).total_seconds()
                    self._state.record_merge_duration(merge_seconds)
                except (ValueError, TypeError):
                    pass
            # Check thresholds and publish alerts
            proposals = self._state.check_thresholds(
                self._config.quality_fix_rate_threshold,
                self._config.approval_rate_threshold,
                self._config.hitl_rate_threshold,
            )
            for proposal in proposals:
                self._state.mark_threshold_fired(proposal["name"])
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data={
                            "message": (
                                f"Threshold breached: {proposal['metric']} "
                                f"({proposal['value']:.2f} vs {proposal['threshold']:.2f}). "
                                f"{proposal['action']}"
                            ),
                            "source": "threshold_check",
                            "threshold": proposal,
                        },
                    )
                )
            self._state.reset_review_attempts(pr.issue_number)
            self._state.reset_issue_attempts(pr.issue_number)
            self._state.clear_review_feedback(pr.issue_number)
            await self._prs.swap_pipeline_labels(
                pr.issue_number, self._config.fixed_label[0]
            )
            await self._run_post_merge_hooks(pr, issue, result, diff)
        else:
            logger.warning("PR #%d merge failed — escalating to HITL", pr.number)
            await publish_fn(pr, worker_id, "escalating")
            await escalate_fn(
                pr.issue_number,
                pr.number,
                cause="PR merge failed on GitHub",
                origin_label=self._config.review_label[0],
                comment=(
                    "**Merge failed** — PR could not be merged. "
                    "Escalating to human review."
                ),
                event_cause="merge_failed",
            )

    @staticmethod
    async def _safe_hook(
        name: str,
        coro: Coroutine[Any, Any, _T],
        issue_number: int,
    ) -> _T | None:
        """Await a post-merge hook, logging and swallowing any exception."""
        try:
            return await coro
        except Exception:  # noqa: BLE001
            logger.warning(
                "%s failed for issue #%d",
                name,
                issue_number,
                exc_info=True,
            )
            return None

    async def _run_post_merge_hooks(
        self,
        pr: PRInfo,
        issue: GitHubIssue,
        result: ReviewResult,
        diff: str,
    ) -> None:
        """Run non-blocking post-merge hooks (AC, retrospective, judge, epic)."""
        if self._ac_generator:
            await self._safe_hook(
                "AC generation",
                self._ac_generator.generate(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    issue=issue,
                    diff=diff,
                ),
                pr.issue_number,
            )
        if self._retrospective:
            await self._safe_hook(
                "retrospective",
                self._retrospective.record(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    review_result=result,
                ),
                pr.issue_number,
            )

        verdict: JudgeVerdict | None = None
        if self._verification_judge:
            verdict = await self._safe_hook(
                "verification judge",
                self._verification_judge.judge(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    diff=diff,
                ),
                pr.issue_number,
            )

        judge_result = self._get_judge_result(issue, pr, verdict)
        if judge_result is not None:
            await self._safe_hook(
                "verification issue creation",
                self._create_verification_issue(issue, pr, judge_result),
                pr.issue_number,
            )

        # Check if any parent epics can be closed
        if self._epic_checker:
            await self._safe_hook(
                "epic completion check",
                self._epic_checker.check_and_close_epics(pr.issue_number),
                pr.issue_number,
            )

    def _get_judge_result(
        self,
        issue: GitHubIssue,
        pr: PRInfo,
        verdict: JudgeVerdict | None,
    ) -> JudgeResult | None:
        """Convert a JudgeVerdict into a JudgeResult for verification issue creation."""
        if verdict is None:
            return None

        criteria = [
            VerificationCriterion(
                description=cr.criterion,
                passed=cr.verdict == CriterionVerdict.PASS,
                details=cr.reasoning,
            )
            for cr in verdict.criteria_results
        ]

        return JudgeResult(
            issue_number=issue.number,
            pr_number=pr.number,
            criteria=criteria,
            verification_instructions=verdict.verification_instructions,
            summary=verdict.summary,
        )

    async def _create_verification_issue(
        self,
        issue: GitHubIssue,
        pr: PRInfo,
        judge_result: JudgeResult,
    ) -> int:
        """Create a linked verification issue for human review.

        Returns the created issue number (0 on failure).
        """
        title = f"Verify: {issue.title}"
        if len(title) > 256:
            title = title[:253] + "..."

        body = format_verification_issue_body(judge_result, issue, pr)
        label = self._config.hitl_label[0]
        issue_number = await self._prs.create_issue(title, body, [label])

        if issue_number > 0:
            self._state.set_verification_issue(issue.number, issue_number)
            logger.info(
                "Created verification issue #%d for issue #%d (PR #%d)",
                issue_number,
                issue.number,
                pr.number,
            )

        return issue_number
