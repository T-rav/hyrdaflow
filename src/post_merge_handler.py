"""Post-merge handling for the HydraFlow review pipeline."""

from __future__ import annotations

import logging
import re
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from acceptance_criteria import AcceptanceCriteriaGenerator
from config import HydraFlowConfig
from epic import EpicCompletionChecker
from events import EventBus, EventType, HydraFlowEvent

if TYPE_CHECKING:
    from epic import EpicManager
from models import (
    CiGateFn,
    CriterionVerdict,
    EscalateFn,
    GitHubIssue,
    IssueOutcomeType,
    JudgeResult,
    JudgeVerdict,
    PRInfo,
    PublishFn,
    ReviewResult,
    StatusCallback,
    Task,
    VerificationCriterion,
    VisualValidationDecision,
    VisualValidationPolicy,
)
from pr_manager import PRManager
from prompt_telemetry import PromptTelemetry
from retrospective import RetrospectiveCollector
from state import StateTracker
from verification import format_verification_issue_body
from verification_judge import VerificationJudge

logger = logging.getLogger("hydraflow.post_merge_handler")

_T = TypeVar("_T")
_MANUAL_VERIFY_KEYWORDS = (
    "ui",
    "ux",
    "visual",
    "screen",
    "page",
    "button",
    "browser",
    "click",
    "manual",
    "frontend",
    "form",
)
_NON_MANUAL_WORK_KEYWORDS = (
    "refactor",
    "cleanup",
    "chore",
    "lint",
    "type",
    "typing",
    "test",
    "coverage",
    "docs",
    "documentation",
)
_USER_SURFACE_DIFF_RE = re.compile(
    r"^\+\+\+\s+b/("
    r"src/ui/|ui/|frontend/|web/|"
    r".*\.(?:tsx|jsx|css|scss|html)"
    r")",
    re.IGNORECASE | re.MULTILINE,
)


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
        update_bg_worker_status: StatusCallback | None = None,
        epic_manager: EpicManager | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._bus = event_bus
        self._ac_generator = ac_generator
        self._retrospective = retrospective
        self._verification_judge = verification_judge
        self._epic_checker = epic_checker
        self._update_bg_worker_status = update_bg_worker_status
        self._prompt_telemetry = PromptTelemetry(config)
        self._epic_manager = epic_manager

    async def handle_approved(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        diff: str,
        worker_id: int,
        ci_gate_fn: CiGateFn,
        escalate_fn: EscalateFn,
        publish_fn: PublishFn,
        code_scanning_alerts: list[dict] | None = None,
        visual_decision: VisualValidationDecision | None = None,
    ) -> None:
        """Attempt merge for an approved PR (with optional CI gate)."""
        should_merge = True
        if self._config.max_ci_fix_attempts > 0:
            should_merge = await ci_gate_fn(
                pr,
                issue,
                self._config.worktree_path_for_issue(pr.issue_number),
                result,
                worker_id,
                code_scanning_alerts=code_scanning_alerts,
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
            self._state.increment_session_counter("merged")
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
            self._state.record_outcome(
                pr.issue_number,
                IssueOutcomeType.MERGED,
                reason="PR approved and merged",
                pr_number=pr.number,
                phase="review",
            )
            self._state.reset_review_attempts(pr.issue_number)
            self._state.reset_issue_attempts(pr.issue_number)
            self._state.clear_review_feedback(pr.issue_number)
            await self._prs.swap_pipeline_labels(
                pr.issue_number, self._config.fixed_label[0]
            )
            await self._post_inference_totals_comment(pr, issue)
            await self._run_post_merge_hooks(pr, issue, result, diff, visual_decision)
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
                task=issue,
            )

    async def _post_inference_totals_comment(self, pr: PRInfo, issue: Task) -> None:
        """Post PR inference totals to the issue after a successful merge."""
        totals = self._prompt_telemetry.get_pr_totals(pr.number)
        if not totals:
            return
        token_total = int(totals.get("total_tokens", 0))
        est_total = int(totals.get("total_est_tokens", 0))
        calls = int(totals.get("inference_calls", 0))
        actual_calls = int(totals.get("actual_usage_calls", 0))
        source = "actual usage" if actual_calls > 0 else "estimated usage"

        body = (
            "## Inference Usage\n\n"
            f"- PR: #{pr.number}\n"
            f"- Inference calls: {calls}\n"
            f"- Total tokens: {token_total:,} ({source})\n"
            f"- Estimated fallback tokens: {est_total:,}\n"
        )
        try:
            await self._prs.post_comment(issue.id, body)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not post inference usage comment for issue #%d (PR #%d)",
                issue.id,
                pr.number,
                exc_info=True,
            )

    async def _safe_hook(
        self,
        name: str,
        coro: Coroutine[Any, Any, _T],
        issue_number: int,
    ) -> _T | None:
        """Await a post-merge hook, recording failures for visibility."""
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)[:500]
            logger.warning(
                "%s failed for issue #%d",
                name,
                issue_number,
                exc_info=True,
            )
            try:
                self._state.record_hook_failure(issue_number, name, error_msg)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Failed to record hook failure for issue #%d",
                    issue_number,
                    exc_info=True,
                )
            try:
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data={
                            "message": (
                                f"Post-merge hook '{name}' failed for issue "
                                f"#{issue_number}: {error_msg}"
                            ),
                            "source": "post_merge_hook",
                            "hook_name": name,
                            "issue": issue_number,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Failed to publish hook failure event for issue #%d",
                    issue_number,
                    exc_info=True,
                )
            try:
                await self._prs.post_comment(
                    issue_number,
                    f"**Post-merge hook failure:** `{name}` failed.\n\n"
                    f"Error: {error_msg}\n\n"
                    f"---\n*HydraFlow PostMergeHandler*",
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not post hook-failure comment for issue #%d",
                    issue_number,
                    exc_info=True,
                )
            return None

    async def _run_post_merge_hooks(
        self,
        pr: PRInfo,
        issue: Task,
        result: ReviewResult,
        diff: str,
        visual_decision: VisualValidationDecision | None = None,
    ) -> None:
        """Run non-blocking post-merge hooks (AC, retrospective, judge, epic)."""
        if self._ac_generator:
            await self._safe_hook(
                "AC generation",
                self._ac_generator.generate(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    issue=GitHubIssue.from_task(issue),
                    diff=diff,
                ),
                pr.issue_number,
            )
        if self._retrospective:
            retro_status = "ok"
            try:
                await self._retrospective.record(
                    issue_number=pr.issue_number,
                    pr_number=pr.number,
                    review_result=result,
                )
            except Exception:  # noqa: BLE001
                retro_status = "error"
                logger.warning(
                    "retrospective failed for issue #%d",
                    pr.issue_number,
                    exc_info=True,
                )
            if self._update_bg_worker_status:
                try:
                    self._update_bg_worker_status(
                        "retrospective",
                        retro_status,
                        {"issue_number": pr.issue_number, "pr_number": pr.number},
                    )
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "retrospective status callback failed for issue #%d",
                        pr.issue_number,
                        exc_info=True,
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
        if judge_result is not None and self._should_create_verification_issue(
            issue, judge_result, diff, visual_decision
        ):
            await self._safe_hook(
                "verification issue creation",
                self._create_verification_issue(issue, pr, judge_result),
                pr.issue_number,
            )

        # Notify EpicManager of child completion (handles auto-close internally)
        if self._epic_manager is not None:
            epic_state = self._state.get_epic_state(pr.issue_number)
            if epic_state is None:
                # Check all tracked epics if this issue is a child
                for es in self._state.get_all_epic_states().values():
                    if pr.issue_number in es.child_issues:
                        await self._safe_hook(
                            "epic child completion",
                            self._epic_manager.on_child_completed(
                                es.epic_number, pr.issue_number
                            ),
                            pr.issue_number,
                        )
                        break
        elif self._epic_checker:
            # Fallback to legacy checker if EpicManager is not wired
            await self._safe_hook(
                "epic completion check",
                self._epic_checker.check_and_close_epics(pr.issue_number),
                pr.issue_number,
            )

    def _get_judge_result(
        self,
        issue: Task,
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
            issue_number=issue.id,
            pr_number=pr.number,
            criteria=criteria,
            verification_instructions=verdict.verification_instructions,
            summary=verdict.summary,
        )

    def _should_create_verification_issue(
        self,
        issue: Task,
        judge_result: JudgeResult,
        diff: str,
        visual_decision: VisualValidationDecision | None = None,
    ) -> bool:
        """Return True only when the change needs human/manual verification.

        When a ``VisualValidationDecision`` is provided, it takes precedence
        over the legacy heuristic for UI-surface detection:
        - REQUIRED → always create a verification issue (if instructions exist).
        - SKIPPED  → skip the user-surface diff check (still honours manual cues).
        """
        instructions = judge_result.verification_instructions.strip()
        if not instructions:
            logger.info(
                "Skipping verification issue for #%d: no verification instructions",
                issue.id,
            )
            return False

        # Visual validation override: REQUIRED forces creation
        if (
            visual_decision is not None
            and visual_decision.policy == VisualValidationPolicy.REQUIRED
        ):
            logger.info(
                "Creating verification issue for #%d: visual validation required (%s)",
                issue.id,
                visual_decision.reason,
            )
            return True

        issue_text = f"{issue.title}\n{issue.body}".lower()
        instructions_text = instructions.lower()
        has_manual_cues = any(
            kw in instructions_text or kw in issue_text
            for kw in _MANUAL_VERIFY_KEYWORDS
        )

        # When visual validation says SKIPPED, skip the diff-based user-surface check
        if (
            visual_decision is not None
            and visual_decision.policy == VisualValidationPolicy.SKIPPED
        ):
            touches_user_surface = False
        else:
            touches_user_surface = bool(_USER_SURFACE_DIFF_RE.search(diff or ""))

        if has_manual_cues or touches_user_surface:
            return True

        if any(kw in issue_text for kw in _NON_MANUAL_WORK_KEYWORDS):
            logger.info(
                "Skipping verification issue for #%d: non-user-facing change",
                issue.id,
            )
            return False

        logger.info(
            "Skipping verification issue for #%d: no human-verification signal",
            issue.id,
        )
        return False

    async def _create_verification_issue(
        self,
        issue: Task,
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
            self._state.set_verification_issue(issue.id, issue_number)
            logger.info(
                "Created verification issue #%d for issue #%d (PR #%d)",
                issue_number,
                issue.id,
                pr.number,
            )

        return issue_number
