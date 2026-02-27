"""Tests for review_phase.py — HITL escalation and retry logic."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventType
from models import (
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
)
from review_phase import ReviewPhase
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import ConfigFactory, make_review_phase


class TestHITLEscalationEvents:
    """Tests that HITL escalation points emit HITL_ESCALATION events."""

    @pytest.mark.asyncio
    async def test_merge_conflict_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Merge conflict escalation should emit HITL_ESCALATION with cause merge_conflict."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "merge_conflict"

    @pytest.mark.asyncio
    async def test_merge_failure_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Merge failure escalation should emit HITL_ESCALATION with cause merge_failed."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "merge_failed"

    @pytest.mark.asyncio
    async def test_ci_failure_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """CI failure escalation should emit HITL_ESCALATION with cause ci_failed."""
        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "ci_failed"
        assert data["ci_fix_attempts"] == 1

    @pytest.mark.asyncio
    async def test_successful_merge_does_not_emit_hitl_escalation(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Happy path (approve + merge) should NOT emit HITL_ESCALATION."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 0

    @pytest.mark.asyncio
    async def test_review_fix_cap_exceeded_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Review fix cap exceeded should emit HITL_ESCALATION with cause review_fix_cap_exceeded."""
        phase = make_review_phase(config, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Set attempts to max so cap is exceeded
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "escalated"
        assert data["role"] == "reviewer"
        assert data["cause"] == "review_fix_cap_exceeded"


# ---------------------------------------------------------------------------
# REQUEST_CHANGES retry logic
# ---------------------------------------------------------------------------


class TestRequestChangesRetry:
    """Tests for the REQUEST_CHANGES → retry → HITL escalation flow."""

    def _setup_phase_for_retry(
        self, config: HydraFlowConfig
    ) -> tuple[ReviewPhase, PRInfo, Task]:
        """Helper to set up a ReviewPhase ready for retry tests."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                verdict=ReviewVerdict.REQUEST_CHANGES
            )
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        return phase, pr, issue

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_swaps_label_to_ready(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should swap labels from review to ready."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        phase._prs.transition.assert_any_await(42, "ready", pr_number=101)

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_preserves_worktree(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should NOT destroy the worktree."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        phase._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_stores_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should store review feedback in state."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        feedback = phase._state.get_review_feedback(42)
        assert feedback is not None
        assert feedback == "Looks good."

    @pytest.mark.asyncio
    async def test_request_changes_under_cap_increments_attempt_counter(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES under cap should increment the attempt counter."""
        phase, pr, issue = self._setup_phase_for_retry(config)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_attempts(42) == 1

    @pytest.mark.asyncio
    async def test_request_changes_at_cap_escalates_to_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES at cap should escalate to HITL."""
        phase, pr, issue = self._setup_phase_for_retry(config)
        # Set attempts to max
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase.review_prs([pr], [issue])

        phase._prs.transition.assert_any_await(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_request_changes_at_cap_posts_escalation_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """REQUEST_CHANGES at cap should post an escalation comment."""
        phase, pr, issue = self._setup_phase_for_retry(config)
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase.review_prs([pr], [issue])

        phase._prs.post_comment.assert_awaited()
        comment_arg = phase._prs.post_comment.call_args[0][1]
        assert "cap exceeded" in comment_arg.lower()

    @pytest.mark.asyncio
    async def test_comment_verdict_treated_as_soft_rejection(
        self, config: HydraFlowConfig
    ) -> None:
        """COMMENT verdict should trigger the same retry flow as REQUEST_CHANGES."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(verdict=ReviewVerdict.COMMENT)
        )
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should swap to ready label (same as REQUEST_CHANGES)
        phase._prs.transition.assert_any_await(42, "ready", pr_number=101)
        # Worktree should be preserved
        phase._worktrees.destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approve_resets_review_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE should reset review attempt counter on successful merge."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Simulate previous review attempts
        phase._state.increment_review_attempts(42)

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_attempts(42) == 0

    @pytest.mark.asyncio
    async def test_approve_clears_review_feedback(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE should clear stored review feedback on successful merge."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Simulate stored feedback from a previous review
        phase._state.set_review_feedback(42, "Old feedback")

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_feedback(42) is None


# ---------------------------------------------------------------------------
# Adversarial review threshold
# ---------------------------------------------------------------------------


class TestAdversarialReview:
    """Tests for the adversarial review re-check logic."""

    @pytest.mark.asyncio
    async def test_approve_with_enough_findings_is_accepted(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE with >= min_review_findings should be accepted without re-review."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Summary with 3+ findings (bullets)
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="- Fix A\n- Fix B\n- Fix C",
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should only call review once (no re-review)
        assert phase._reviewers.review.await_count == 1

    @pytest.mark.asyncio
    async def test_approve_with_thorough_review_complete_accepted(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE with THOROUGH_REVIEW_COMPLETE block should be accepted."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="All good",
            fixes_made=False,
            transcript="...THOROUGH_REVIEW_COMPLETE\nCorrectness: No issues...",
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should only call review once (no re-review)
        assert phase._reviewers.review.await_count == 1

    @pytest.mark.asyncio
    async def test_approve_under_threshold_triggers_re_review(
        self, config: HydraFlowConfig
    ) -> None:
        """APPROVE with too few findings and no justification should trigger re-review."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # First review: few findings, no THOROUGH_REVIEW_COMPLETE
        first_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good",
            fixes_made=False,
            transcript="VERDICT: APPROVE\nSUMMARY: Looks good",
        )
        # Second review: has enough findings
        second_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="- Fix A\n- Fix B\n- Fix C",
            fixes_made=False,
            transcript="VERDICT: APPROVE\nSUMMARY: - Fix A",
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should call review twice (initial + re-review)
        assert phase._reviewers.review.await_count == 2

    @pytest.mark.asyncio
    async def test_disabled_when_min_findings_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """min_review_findings=0 should disable adversarial re-review entirely."""
        cfg = ConfigFactory.create(
            min_review_findings=0,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Approve with zero findings and no justification — should NOT trigger re-review
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="All good",
            fixes_made=False,
            transcript="VERDICT: APPROVE",
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should only call review once (no re-review)
        assert phase._reviewers.review.await_count == 1

    @pytest.mark.asyncio
    async def test_re_review_under_threshold_accepted_anyway(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review still under threshold with no justification should accept (no infinite loop)."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Both reviews: under threshold, no justification
        first_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="LGTM",
            fixes_made=False,
            transcript="VERDICT: APPROVE",
        )
        second_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Still LGTM",
            fixes_made=False,
            transcript="VERDICT: APPROVE",
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should call review exactly twice (initial + one re-review), then accept
        assert phase._reviewers.review.await_count == 2
        # PR should still be merged exactly once (accepted anyway)
        assert phase._prs.merge_pr.await_count == 1

    @pytest.mark.asyncio
    async def test_re_review_pushes_fixes(self, config: HydraFlowConfig) -> None:
        """Re-review with fixes_made=True should push the branch."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # First review: under threshold, no justification
        first_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks fine",
            fixes_made=False,
            transcript="VERDICT: APPROVE",
        )
        # Re-review: makes fixes
        second_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="- Fixed formatting\n- Fixed imports\n- Fixed types",
            fixes_made=True,
            transcript="VERDICT: APPROVE",
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.worktree_base / "issue-42"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # push_branch should be called for the re-review fixes
        assert phase._prs.push_branch.await_count >= 1


# ---------------------------------------------------------------------------
# Extracted method unit tests
# ---------------------------------------------------------------------------


class TestEscalateToHitl:
    """Unit tests for the shared _escalate_to_hitl helper."""

    @pytest.mark.asyncio
    async def test_sets_hitl_origin_and_cause(self, config: HydraFlowConfig) -> None:
        """Should set HITL origin label and cause in state."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test failure",
            origin_label="hydraflow-review",
            comment="Escalation comment",
        )

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        assert phase._state.get_hitl_cause(42) == "Test failure"

    @pytest.mark.asyncio
    async def test_records_hitl_escalation_counter(
        self, config: HydraFlowConfig
    ) -> None:
        """Should increment the HITL escalation counter."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="comment",
        )

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_swaps_labels_on_issue_and_pr(self, config: HydraFlowConfig) -> None:
        """Should remove review labels and add HITL labels."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="comment",
        )

        phase._prs.transition.assert_awaited_once_with(42, "hitl", pr_number=101)

    @pytest.mark.asyncio
    async def test_posts_comment_on_pr_by_default(
        self, config: HydraFlowConfig
    ) -> None:
        """By default, the comment is posted on the PR."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="Escalation!",
        )

        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Escalation!")
        phase._prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_posts_comment_on_issue_when_post_on_pr_false(
        self, config: HydraFlowConfig
    ) -> None:
        """When post_on_pr=False, comment is posted on the issue."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="Escalation!",
            post_on_pr=False,
        )

        phase._prs.post_comment.assert_awaited_once_with(42, "Escalation!")
        phase._prs.post_pr_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publishes_hitl_escalation_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Should publish an HITL_ESCALATION event."""
        phase = make_review_phase(config, event_bus=event_bus)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test cause",
            origin_label="hydraflow-review",
            comment="comment",
            event_cause="test_event",
        )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type == EventType.HITL_ESCALATION]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["pr"] == 101
        assert hitl_events[0].data["cause"] == "test_event"

    @pytest.mark.asyncio
    async def test_extra_event_data_included(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Extra event data should be merged into the HITL event."""
        phase = make_review_phase(config, event_bus=event_bus)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="CI failed",
            origin_label="hydraflow-review",
            comment="comment",
            extra_event_data={"ci_fix_attempts": 3},
        )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type == EventType.HITL_ESCALATION]
        assert hitl_events[0].data["ci_fix_attempts"] == 3

    @pytest.mark.asyncio
    async def test_enqueue_transition_called_when_task_provided(
        self, config: HydraFlowConfig
    ) -> None:
        """Providing task should enqueue transition immediately."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        issue = TaskFactory.create(id=42)

        await phase._escalate_to_hitl(
            issue.id,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="Escalation!",
            task=issue,
        )

        phase._store.enqueue_transition.assert_called_once_with(issue, "hitl")

    @pytest.mark.asyncio
    async def test_enqueue_transition_not_called_when_no_task(
        self, config: HydraFlowConfig
    ) -> None:
        """Omitting task (default None) should not call enqueue_transition."""
        phase = make_review_phase(config)
        phase._prs.remove_label = AsyncMock()
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()

        await phase._escalate_to_hitl(
            42,
            101,
            cause="Test",
            origin_label="hydraflow-review",
            comment="Escalation!",
        )

        phase._store.enqueue_transition.assert_not_called()
