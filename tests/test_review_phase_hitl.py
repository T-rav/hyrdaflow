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
    HitlEscalation,
    LoopResult,
    PRInfo,
    ReviewVerdict,
    Task,
    VisualFailureClass,
    VisualScreenResult,
    VisualScreenVerdict,
    VisualValidationReport,
)
from review_phase import ReviewPhase
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import ConfigFactory, make_review_phase

# ---------------------------------------------------------------------------
# Shared mock setup helpers
# ---------------------------------------------------------------------------


def _setup_escalate_to_hitl_mocks(phase: ReviewPhase) -> None:
    """Set up the PR manager mocks required by _escalate_to_hitl."""
    phase._prs.post_pr_comment = AsyncMock()
    phase._prs.remove_label = AsyncMock()
    phase._prs.remove_pr_label = AsyncMock()
    phase._prs.add_labels = AsyncMock()
    phase._prs.add_pr_labels = AsyncMock()


def _setup_conflict_scenario(phase: ReviewPhase) -> None:
    """Set up mocks for a merge-conflict escalation scenario (merge_main returns False)."""
    _setup_escalate_to_hitl_mocks(phase)
    phase._workspaces.merge_main = AsyncMock(return_value=False)


# ---------------------------------------------------------------------------


class TestHITLEscalationEvents:
    """Tests that HITL escalation points emit HITL_ESCALATION events."""

    @pytest.mark.asyncio
    async def test_merge_conflict_escalation_emits_hitl_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Merge conflict escalation should emit HITL_ESCALATION with cause merge_conflict."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(
            return_value=LoopResult(passed=False, summary="")
        )
        phase = make_review_phase(config, agents=mock_agents, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        _setup_conflict_scenario(phase)
        phase._workspaces.start_merge_main = AsyncMock(return_value=False)
        phase._workspaces.abort_merge = AsyncMock()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "diagnostic"
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
        _setup_escalate_to_hitl_mocks(phase)
        phase._workspaces.merge_main = AsyncMock(return_value=True)

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "diagnostic"
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
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.review = AsyncMock(return_value=ReviewResultFactory.create())
        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))
        _setup_escalate_to_hitl_mocks(phase)
        phase._workspaces.merge_main = AsyncMock(return_value=True)

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "diagnostic"
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
        phase._workspaces.merge_main = AsyncMock(return_value=True)

        wt = config.workspace_path_for_issue(42)
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
        _setup_escalate_to_hitl_mocks(phase)
        phase._prs.post_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()
        phase._workspaces.merge_main = AsyncMock(return_value=True)

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["issue"] == 42
        assert data["pr"] == 101
        assert data["status"] == "diagnostic"
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

        wt = config.workspace_path_for_issue(42)
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

        phase._workspaces.destroy.assert_not_awaited()

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
        """REQUEST_CHANGES at cap should escalate to diagnostic loop."""
        phase, pr, issue = self._setup_phase_for_retry(config)
        # Set attempts to max
        phase._state.increment_review_attempts(42)
        phase._state.increment_review_attempts(42)

        await phase.review_prs([pr], [issue])

        phase._prs.transition.assert_any_await(42, "diagnose", pr_number=101)

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
        _setup_escalate_to_hitl_mocks(phase)
        phase._prs.post_comment = AsyncMock()
        phase._prs.submit_review = AsyncMock()

        wt = config.workspace_path_for_issue(42)
        wt.mkdir(parents=True, exist_ok=True)

        await phase.review_prs([pr], [issue])

        # Should swap to ready label (same as REQUEST_CHANGES)
        phase._prs.transition.assert_any_await(42, "ready", pr_number=101)
        # Worktree should be preserved
        phase._workspaces.destroy.assert_not_awaited()

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

        wt = config.workspace_path_for_issue(42)
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

        wt = config.workspace_path_for_issue(42)
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
        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="- Fix A\n- Fix B\n- Fix C",
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.workspace_path_for_issue(42)
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

        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="All good",
            transcript="...THOROUGH_REVIEW_COMPLETE\nCorrectness: No issues...",
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.workspace_path_for_issue(42)
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
        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good",
            transcript="VERDICT: APPROVE\nSUMMARY: Looks good",
        )
        # Second review: has enough findings
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="- Fix A\n- Fix B\n- Fix C",
            transcript="VERDICT: APPROVE\nSUMMARY: - Fix A",
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.workspace_path_for_issue(42)
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
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Approve with zero findings and no justification — should NOT trigger re-review
        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="All good",
            transcript="VERDICT: APPROVE",
        )
        phase._reviewers.review = AsyncMock(return_value=result)
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.workspace_path_for_issue(42)
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
        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="LGTM",
            transcript="VERDICT: APPROVE",
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="Still LGTM",
            transcript="VERDICT: APPROVE",
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])
        phase._prs.get_pr_diff = AsyncMock(return_value="diff text")
        phase._prs.push_branch = AsyncMock(return_value=True)
        phase._prs.merge_pr = AsyncMock(return_value=True)
        phase._prs.remove_label = AsyncMock()
        phase._prs.add_labels = AsyncMock()

        wt = config.workspace_path_for_issue(42)
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
        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            summary="Looks fine",
            transcript="VERDICT: APPROVE",
        )
        # Re-review: makes fixes
        second_result = ReviewResultFactory.create(
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

        wt = config.workspace_path_for_issue(42)
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
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test failure",
                origin_label="hydraflow-review",
                comment="Escalation comment",
            )
        )

        assert phase._state.get_hitl_origin(42) == "hydraflow-review"
        assert phase._state.get_hitl_cause(42) == "Test failure"

    @pytest.mark.asyncio
    async def test_records_hitl_escalation_counter(
        self, config: HydraFlowConfig
    ) -> None:
        """Should increment the HITL escalation counter."""
        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="comment",
            )
        )

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_swaps_labels_on_issue_and_pr(self, config: HydraFlowConfig) -> None:
        """Should remove review labels and add diagnose labels."""
        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="comment",
            )
        )

        phase._prs.transition.assert_awaited_once_with(42, "diagnose", pr_number=101)

    @pytest.mark.asyncio
    async def test_posts_comment_on_pr_by_default(
        self, config: HydraFlowConfig
    ) -> None:
        """By default, the comment is posted on the PR."""
        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="Escalation!",
            )
        )

        phase._prs.post_pr_comment.assert_awaited_once_with(101, "Escalation!")
        phase._prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_posts_comment_on_issue_when_post_on_pr_false(
        self, config: HydraFlowConfig
    ) -> None:
        """When post_on_pr=False, comment is posted on the issue."""
        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)
        phase._prs.post_comment = AsyncMock()

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="Escalation!",
                post_on_pr=False,
            )
        )

        phase._prs.post_comment.assert_awaited_once_with(42, "Escalation!")
        phase._prs.post_pr_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publishes_hitl_escalation_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Should publish an HITL_ESCALATION event."""
        phase = make_review_phase(config, event_bus=event_bus)
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test cause",
                origin_label="hydraflow-review",
                comment="comment",
                event_cause="test_event",
            )
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
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="CI failed",
                origin_label="hydraflow-review",
                comment="comment",
                extra_event_data={"ci_fix_attempts": 3},
            )
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
        _setup_escalate_to_hitl_mocks(phase)
        issue = TaskFactory.create(id=42)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=issue.id,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="Escalation!",
                task=issue,
            )
        )

        phase._store.enqueue_transition.assert_called_once_with(issue, "diagnose")

    @pytest.mark.asyncio
    async def test_enqueue_transition_not_called_when_no_task(
        self, config: HydraFlowConfig
    ) -> None:
        """Omitting task (default None) should not call enqueue_transition."""
        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Test",
                origin_label="hydraflow-review",
                comment="Escalation!",
            )
        )

        phase._store.enqueue_transition.assert_not_called()


# Visual validation HITL escalation
# ---------------------------------------------------------------------------


def _mock_visual_phase(config: HydraFlowConfig, event_bus) -> ReviewPhase:
    """Create a ReviewPhase with PR manager mocks for visual failure tests."""
    phase = make_review_phase(config, event_bus=event_bus)
    _setup_escalate_to_hitl_mocks(phase)
    return phase


class TestHandleVisualFailure:
    """Tests for _handle_visual_failure HITL escalation for each failure class."""

    @pytest.mark.asyncio
    async def test_infra_only_failure_uses_infra_cause(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Infra-only failures should escalate with infrastructure-specific cause."""
        # Arrange
        phase = _mock_visual_phase(config, event_bus)

        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create()
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="login",
                    failure_class=VisualFailureClass.INFRA_FAILURE,
                    verdict=VisualScreenVerdict.FAIL,
                    error="service unavailable",
                    retries_used=2,
                ),
            ],
            overall_verdict=VisualScreenVerdict.FAIL,
            total_retries=2,
            infra_failures=1,
            visual_diffs=0,
        )

        # Act
        updated = await phase._handle_visual_failure(pr, task, result, report, 0)

        # Assert
        assert updated.verdict == ReviewVerdict.REQUEST_CHANGES
        assert "infrastructure failure" in updated.summary.lower()
        assert "not a visual diff" in updated.summary.lower()

    @pytest.mark.asyncio
    async def test_visual_diff_failure_uses_generic_cause(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Visual diff failures should escalate with generic failure cause."""
        # Arrange
        phase = _mock_visual_phase(config, event_bus)

        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create()
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="dashboard",
                    diff_ratio=0.25,
                    failure_class=VisualFailureClass.VISUAL_DIFF,
                    verdict=VisualScreenVerdict.FAIL,
                ),
            ],
            overall_verdict=VisualScreenVerdict.FAIL,
            visual_diffs=1,
        )

        # Act
        updated = await phase._handle_visual_failure(pr, task, result, report, 0)

        # Assert
        assert updated.verdict == ReviewVerdict.REQUEST_CHANGES
        assert "detected failures" in updated.summary.lower()

    @pytest.mark.asyncio
    async def test_mixed_failures_uses_generic_cause(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Mixed infra + visual diff failures should use the generic cause."""
        # Arrange
        phase = _mock_visual_phase(config, event_bus)

        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create()
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="login",
                    failure_class=VisualFailureClass.INFRA_FAILURE,
                    verdict=VisualScreenVerdict.FAIL,
                ),
                VisualScreenResult(
                    screen_name="dashboard",
                    failure_class=VisualFailureClass.VISUAL_DIFF,
                    verdict=VisualScreenVerdict.FAIL,
                ),
            ],
            overall_verdict=VisualScreenVerdict.FAIL,
            infra_failures=1,
            visual_diffs=1,
        )

        # Act
        updated = await phase._handle_visual_failure(pr, task, result, report, 0)

        # Assert — mixed = generic cause, not infra-only
        assert updated.verdict == ReviewVerdict.REQUEST_CHANGES
        assert "detected failures" in updated.summary.lower()
        assert "infrastructure" not in updated.summary.lower()

    @pytest.mark.asyncio
    async def test_escalation_emits_hitl_event_with_visual_metadata(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Should emit HITL_ESCALATION event with visual-specific metadata."""
        # Arrange
        phase = _mock_visual_phase(config, event_bus)

        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create()
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="page",
                    failure_class=VisualFailureClass.TIMEOUT,
                    verdict=VisualScreenVerdict.FAIL,
                    retries_used=2,
                ),
            ],
            overall_verdict=VisualScreenVerdict.FAIL,
            total_retries=2,
            infra_failures=1,
        )

        # Act
        await phase._handle_visual_failure(pr, task, result, report, 0)

        # Assert
        escalation_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(escalation_events) == 1
        data = escalation_events[0].data
        assert data["cause"] == "visual_validation_failed"
        assert data["visual_verdict"] == "fail"
        assert data["visual_retries"] == 2
        assert data["infra_failures"] == 1
        assert data["visual_diffs"] == 0

    @pytest.mark.asyncio
    async def test_escalation_posts_comment_with_report_summary(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Should post a PR comment containing the visual validation report."""
        # Arrange
        phase = _mock_visual_phase(config, event_bus)

        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create()
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="homepage",
                    diff_ratio=0.25,
                    failure_class=VisualFailureClass.VISUAL_DIFF,
                    verdict=VisualScreenVerdict.FAIL,
                ),
            ],
            overall_verdict=VisualScreenVerdict.FAIL,
            visual_diffs=1,
        )

        # Act
        await phase._handle_visual_failure(pr, task, result, report, 0)

        # Assert
        phase._prs.post_pr_comment.assert_awaited()
        comment = phase._prs.post_pr_comment.call_args[0][1]
        assert "Visual validation failed" in comment
        assert "homepage" in comment

    @pytest.mark.asyncio
    async def test_escalation_transitions_to_hitl(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Should transition the issue to diagnostic loop."""
        # Arrange
        phase = _mock_visual_phase(config, event_bus)

        pr = PRInfoFactory.create()
        task = TaskFactory.create()
        result = ReviewResultFactory.create()
        report = VisualValidationReport(
            overall_verdict=VisualScreenVerdict.FAIL,
            visual_diffs=1,
        )

        # Act
        await phase._handle_visual_failure(pr, task, result, report, 0)

        # Assert
        phase._prs.transition.assert_awaited_once_with(42, "diagnose", pr_number=101)


# ---------------------------------------------------------------------------
# _run_visual_validation integration
# ---------------------------------------------------------------------------


class TestRunVisualValidation:
    """Tests for the _run_visual_validation method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self, config: HydraFlowConfig) -> None:
        """Should return None when visual validation is disabled."""
        # Arrange
        cfg = ConfigFactory.create(
            visual_validation_enabled=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg)
        pr = PRInfoFactory.create()

        # Act
        result = await phase._run_visual_validation(pr, config.workspace_base, 0)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_report_when_enabled(self, config: HydraFlowConfig) -> None:
        """Should return a report (empty screens by default) when enabled."""
        # Arrange
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()

        # Act
        result = await phase._run_visual_validation(pr, config.workspace_base, 0)

        # Assert
        assert result is not None
        assert result.overall_verdict == VisualScreenVerdict.PASS
        assert result.screens == []

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, config: HydraFlowConfig) -> None:
        """Should catch exceptions and return None."""
        # Arrange
        phase = make_review_phase(config)
        pr = PRInfoFactory.create()
        # Force an exception by breaking the validator
        phase._visual_validator.validate_screens = AsyncMock(
            side_effect=RuntimeError("boom"),
        )

        # Act
        result = await phase._run_visual_validation(pr, config.workspace_base, 0)

        # Assert
        assert result is None


# ---------------------------------------------------------------------------
# Visual evidence escalation
# ---------------------------------------------------------------------------


class TestVisualEvidenceEscalation:
    """Tests for visual evidence wiring in _escalate_to_hitl and escalate_visual_failure."""

    @pytest.mark.asyncio
    async def test_escalate_to_hitl_persists_visual_evidence(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual_evidence is provided, it should be persisted in state."""
        from models import VisualEvidence, VisualEvidenceItem

        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=12.5, status="fail"
                )
            ],
            summary="1 screen exceeded threshold",
        )

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Visual validation failed",
                origin_label="hydraflow-review",
                comment="Visual failure",
                visual_evidence=evidence,
            )
        )

        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert len(stored.items) == 1
        assert stored.items[0].screen_name == "login"
        assert stored.items[0].diff_percent == 12.5

    @pytest.mark.asyncio
    async def test_escalate_to_hitl_skips_evidence_when_none(
        self, config: HydraFlowConfig
    ) -> None:
        """When visual_evidence is None, no evidence should be persisted."""
        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="CI failed",
                origin_label="hydraflow-review",
                comment="CI failure",
            )
        )

        assert phase._state.get_hitl_visual_evidence(42) is None

    @pytest.mark.asyncio
    async def test_escalate_to_hitl_includes_evidence_in_event(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Visual evidence should be included in the HITL_ESCALATION event data."""
        from models import VisualEvidence, VisualEvidenceItem

        phase = make_review_phase(config, event_bus=event_bus)
        _setup_escalate_to_hitl_mocks(phase)

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="dashboard", diff_percent=5.0, status="warn"
                )
            ],
            summary="Minor visual diff",
        )

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Visual validation warning",
                origin_label="hydraflow-review",
                comment="Visual warning",
                visual_evidence=evidence,
            )
        )

        hitl_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(hitl_events) == 1
        assert "visual_evidence" in hitl_events[0].data
        ev_data = hitl_events[0].data["visual_evidence"]
        assert ev_data["items"][0]["screen_name"] == "dashboard"

    @pytest.mark.asyncio
    async def test_escalate_visual_failure_full_flow(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """escalate_visual_failure should persist evidence, record harness failure, and escalate."""
        from models import VisualEvidence, VisualEvidenceItem

        phase = make_review_phase(config, event_bus=event_bus)
        _setup_escalate_to_hitl_mocks(phase)
        issue = TaskFactory.create(id=42)

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=15.0, status="fail"
                ),
                VisualEvidenceItem(
                    screen_name="settings", diff_percent=3.0, status="warn"
                ),
            ],
            summary="1 fail, 1 warn",
            run_url="https://ci.example.com/run/123",
        )

        await phase.escalate_visual_failure(42, 101, evidence, task=issue)

        # Verify visual evidence persisted
        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert len(stored.items) == 2

        # Verify HITL state was set
        assert phase._state.get_hitl_origin(42) == config.review_label[0]
        cause = phase._state.get_hitl_cause(42)
        assert cause is not None
        assert "Visual validation failed" in cause

        # Verify escalation event was published
        hitl_events = [
            e for e in event_bus.get_history() if e.type == EventType.HITL_ESCALATION
        ]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["cause"] == "visual_validation_failed"
        assert "visual_evidence" in hitl_events[0].data

        # Verify comment was posted on PR
        phase._prs.post_pr_comment.assert_awaited_once()
        comment = phase._prs.post_pr_comment.call_args[0][1]
        assert "Visual Validation Failed" in comment
        assert "login" in comment
        assert "15.0% diff" in comment

    @pytest.mark.asyncio
    async def test_escalate_visual_failure_warn_only(
        self, config: HydraFlowConfig
    ) -> None:
        """When all items are warnings, category should be VISUAL_WARN."""
        from models import VisualEvidence, VisualEvidenceItem

        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="header", diff_percent=2.0, status="warn"
                ),
            ],
            summary="Minor diff detected",
        )

        await phase.escalate_visual_failure(42, 101, evidence)

        # Should still escalate and persist
        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert stored.items[0].status == "warn"

    @pytest.mark.asyncio
    async def test_escalate_visual_failure_no_pr(self, config: HydraFlowConfig) -> None:
        """When pr_number is None, comment should go to issue instead."""
        from models import VisualEvidence, VisualEvidenceItem

        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)
        phase._prs.post_comment = AsyncMock()

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=10.0, status="fail"
                ),
            ],
            summary="Visual fail",
        )

        await phase.escalate_visual_failure(42, None, evidence)

        # Comment should go to issue since pr_number is None
        phase._prs.post_comment.assert_awaited_once()
        phase._prs.post_pr_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_escalate_visual_failure_empty_evidence(
        self, config: HydraFlowConfig
    ) -> None:
        """Empty evidence items should still escalate with minimal comment."""
        from models import VisualEvidence

        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        evidence = VisualEvidence(items=[], summary="No details available")

        await phase.escalate_visual_failure(42, 101, evidence)

        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert len(stored.items) == 0

    @pytest.mark.asyncio
    async def test_requeue_preserves_visual_evidence(
        self, config: HydraFlowConfig
    ) -> None:
        """Visual evidence should survive across requeue attempts (HITL failure -> retry)."""
        from models import VisualEvidence, VisualEvidenceItem

        phase = make_review_phase(config)
        _setup_escalate_to_hitl_mocks(phase)

        evidence = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=12.0, status="fail"
                )
            ],
            summary="Login page regression",
            attempt=1,
        )

        # First escalation
        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Visual validation failed",
                origin_label="hydraflow-review",
                comment="Visual failure",
                visual_evidence=evidence,
            )
        )

        # Evidence should be stored
        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert stored.attempt == 1

        # Overwrite with updated attempt (simulates requeue)
        evidence_v2 = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="login", diff_percent=8.0, status="fail")
            ],
            summary="Login page regression (retry)",
            attempt=2,
        )

        await phase._escalate_to_hitl(
            HitlEscalation(
                issue_number=42,
                pr_number=101,
                cause="Visual validation failed (retry)",
                origin_label="hydraflow-review",
                comment="Visual failure retry",
                visual_evidence=evidence_v2,
            )
        )

        # Updated evidence should be stored
        stored = phase._state.get_hitl_visual_evidence(42)
        assert stored is not None
        assert stored.attempt == 2
        assert stored.items[0].diff_percent == 8.0
