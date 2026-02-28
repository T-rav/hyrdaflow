"""Tests for review_phase.py — metrics, verification, and insights."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventType
from models import (
    CriterionResult,
    CriterionVerdict,
    JudgeResult,
    JudgeVerdict,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
    VerificationCriterion,
)
from review_phase import ReviewPhase
from tests.conftest import (
    PRInfoFactory,
    ReviewResultFactory,
    TaskFactory,
)
from tests.helpers import make_review_phase

# ---------------------------------------------------------------------------
# Lifecycle metric recording
# ---------------------------------------------------------------------------


class TestLifecycleMetricRecording:
    """Tests that review_prs records new lifecycle metrics in state."""

    @pytest.mark.asyncio
    async def test_records_review_verdict_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """Approving a PR should record an approval verdict in state."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_approvals == 1
        assert stats.total_review_request_changes == 0

    @pytest.mark.asyncio
    async def test_records_review_verdict_request_changes(
        self, config: HydraFlowConfig
    ) -> None:
        """Request-changes verdict should record in state."""
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Needs changes.",
            fixes_made=False,
        )
        phase = make_review_phase(config, default_mocks=True, review_result=result)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_request_changes == 1
        assert stats.total_review_approvals == 0

    @pytest.mark.asyncio
    async def test_records_reviewer_fixes(self, config: HydraFlowConfig) -> None:
        """When reviewer makes fixes, it should be counted."""
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="Fixed and approved.",
            fixes_made=True,
        )
        phase = make_review_phase(config, default_mocks=True, review_result=result)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_reviewer_fixes == 1

    @pytest.mark.asyncio
    async def test_records_review_duration(self, config: HydraFlowConfig) -> None:
        """Review duration should be recorded when positive."""
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="OK",
            duration_seconds=45.5,
        )
        phase = make_review_phase(config, default_mocks=True, review_result=result)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_seconds == pytest.approx(45.5)

    @pytest.mark.asyncio
    async def test_does_not_record_zero_review_duration(
        self, config: HydraFlowConfig
    ) -> None:
        """Zero duration should not be recorded."""
        result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            summary="OK",
            duration_seconds=0.0,
        )
        phase = make_review_phase(config, default_mocks=True, review_result=result)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_review_seconds == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_merge_conflict_records_hitl_escalation(
        self, config: HydraFlowConfig
    ) -> None:
        """Merge conflict HITL escalation should increment the hitl counter."""
        mock_agents = AsyncMock()
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(config, agents=mock_agents, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_merge_failure_records_hitl_escalation(
        self, config: HydraFlowConfig
    ) -> None:
        """PR merge failure should increment the hitl counter."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_ci_failure_records_ci_fix_rounds_and_hitl(
        self, config: HydraFlowConfig
    ) -> None:
        """CI failure escalation should record ci fix rounds and hitl escalation."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

        await phase.review_prs([pr], [issue])

        stats = phase._state.get_lifetime_stats()
        assert stats.total_ci_fix_rounds == 1
        assert stats.total_hitl_escalations == 1

    @pytest.mark.asyncio
    async def test_successful_merge_with_ci_fixes_records_rounds(
        self, config: HydraFlowConfig
    ) -> None:
        """When CI eventually passes after fix(es), ci_fix_rounds should be recorded."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        ci_results = [
            (False, "Failed checks: ci"),
            (True, "All 2 checks passed"),
        ]
        ci_call_count = 0

        async def fake_wait_for_ci(_pr_num, _timeout, _interval, _stop):
            nonlocal ci_call_count
            result = ci_results[ci_call_count]
            ci_call_count += 1
            return result

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = fake_wait_for_ci

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True
        stats = phase._state.get_lifetime_stats()
        assert stats.total_ci_fix_rounds == 1  # 1 fix attempt before success


# ---------------------------------------------------------------------------
# Retrospective integration
# ---------------------------------------------------------------------------


class TestRetrospectiveIntegration:
    """Tests that retrospective.record() is called correctly after merge."""

    @pytest.mark.asyncio
    async def test_retrospective_called_on_successful_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """retrospective.record() should be called when PR is merged."""
        mock_retro = AsyncMock()
        phase = make_review_phase(config, default_mocks=True)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        mock_retro.record.assert_awaited_once()
        call_kwargs = mock_retro.record.call_args[1]
        assert call_kwargs["issue_number"] == 42
        assert call_kwargs["pr_number"] == 101
        assert call_kwargs["review_result"].merged is True

    @pytest.mark.asyncio
    async def test_retrospective_not_called_on_failed_merge(
        self, config: HydraFlowConfig
    ) -> None:
        """retrospective.record() should NOT be called when merge fails."""
        mock_retro = AsyncMock()
        phase = make_review_phase(config, default_mocks=True)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=True)

        await phase.review_prs([pr], [issue])

        mock_retro.record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retrospective_failure_does_not_crash_review(
        self, config: HydraFlowConfig
    ) -> None:
        """If retrospective.record() raises, it should not crash the review."""
        mock_retro = AsyncMock()
        mock_retro.record = AsyncMock(side_effect=RuntimeError("retro boom"))
        phase = make_review_phase(config, default_mocks=True)
        phase._retrospective = mock_retro
        phase._post_merge._retrospective = mock_retro

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Should not raise despite retro failure
        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True

    @pytest.mark.asyncio
    async def test_retrospective_not_called_when_not_configured(
        self, config: HydraFlowConfig
    ) -> None:
        """When no retrospective is set, merge should work normally."""
        phase = make_review_phase(config, default_mocks=True)
        # phase._retrospective and phase._post_merge._retrospective are None by default

        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        results = await phase.review_prs([pr], [issue])

        assert results[0].merged is True


# ---------------------------------------------------------------------------
# Review insight integration
# ---------------------------------------------------------------------------


class TestReviewInsightIntegration:
    """Tests for review insight recording during the review flow."""

    @pytest.mark.asyncio
    async def test_review_records_insight_after_review(
        self, config: HydraFlowConfig
    ) -> None:
        """After a review, a record should be appended to the insight store."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        # Check that a review record was written
        reviews_path = config.repo_root / ".hydraflow" / "memory" / "reviews.jsonl"
        assert reviews_path.exists()
        lines = reviews_path.read_text().strip().splitlines()
        assert len(lines) == 1

    @pytest.mark.asyncio
    async def test_review_insight_files_proposal_when_threshold_met(
        self, config: HydraFlowConfig
    ) -> None:
        """When a category crosses the threshold, an improvement issue is filed."""
        from review_insights import ReviewInsightStore, ReviewRecord

        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Pre-populate the insight store with records near threshold
        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        for i in range(3):
            store.append_review(
                ReviewRecord(
                    pr_number=90 + i,
                    issue_number=30 + i,
                    timestamp="2026-02-20T10:00:00Z",
                    verdict=ReviewVerdict.REQUEST_CHANGES,
                    summary="Missing test coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )

        # This review will also have "test" in summary → missing_tests
        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Missing test coverage for edge cases",
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=review_result)
        phase._prs.create_issue = AsyncMock(return_value=999)

        await phase.review_prs([pr], [issue])

        # Should have filed an improvement issue
        phase._prs.create_task.assert_awaited_once()
        call_args = phase._prs.create_task.call_args
        assert "[Review Insight]" in call_args.args[0]
        assert "hydraflow-improve" in call_args.args[2]
        assert "hydraflow-hitl" in call_args.args[2]

    @pytest.mark.asyncio
    async def test_review_insight_does_not_refile_proposed_category(
        self, config: HydraFlowConfig
    ) -> None:
        """Once a category has been proposed, it should not be re-filed."""
        from review_insights import ReviewInsightStore, ReviewRecord

        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="Missing test coverage",
            fixes_made=False,
        )
        phase = make_review_phase(
            config, default_mocks=True, review_result=review_result
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Pre-populate and mark as proposed
        store = ReviewInsightStore(config.repo_root / ".hydraflow" / "memory")
        for i in range(4):
            store.append_review(
                ReviewRecord(
                    pr_number=90 + i,
                    issue_number=30 + i,
                    timestamp="2026-02-20T10:00:00Z",
                    verdict=ReviewVerdict.REQUEST_CHANGES,
                    summary="Missing test coverage",
                    fixes_made=False,
                    categories=["missing_tests"],
                )
            )
        store.mark_category_proposed("missing_tests")

        phase._prs.create_issue = AsyncMock(return_value=999)

        await phase.review_prs([pr], [issue])

        # Should NOT have filed an improvement issue
        phase._prs.create_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_insight_failure_does_not_crash_review(
        self, config: HydraFlowConfig
    ) -> None:
        """If insight recording fails, the review should still complete."""
        from unittest.mock import patch

        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        # Make the insight store raise
        with patch.object(
            phase._insights, "append_review", side_effect=OSError("disk full")
        ):
            results = await phase.review_prs([pr], [issue])

        # Review should still succeed
        assert len(results) == 1
        assert results[0].merged is True


# ---------------------------------------------------------------------------
# Granular REVIEW_UPDATE status events
# ---------------------------------------------------------------------------


class TestGranularReviewStatusEvents:
    """Tests that review_phase emits granular status events at each lifecycle stage."""

    @pytest.mark.asyncio
    async def test_merge_main_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'merge_main' event should be published before merging main."""
        phase = make_review_phase(config, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        merge_main_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "merge_main"
        ]
        assert len(merge_main_events) == 1
        assert merge_main_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_merge_fix_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'merge_fix' event should be published when resolving conflicts."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(True, ""))
        phase = make_review_phase(
            config, agents=mock_agents, default_mocks=True, event_bus=event_bus
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        conflict_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "merge_fix"
        ]
        # One event from the caller in review_prs, one from the retry loop
        assert len(conflict_events) == 2
        assert conflict_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_escalating_status_emitted_on_conflict_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """An 'escalating' event should be published when conflicts can't be resolved."""
        mock_agents = AsyncMock()
        mock_agents._execute = AsyncMock(return_value="transcript")
        mock_agents._verify_result = AsyncMock(return_value=(False, ""))
        phase = make_review_phase(
            config, agents=mock_agents, default_mocks=True, event_bus=event_bus
        )
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._worktrees.merge_main = AsyncMock(return_value=False)
        phase._worktrees.start_merge_main = AsyncMock(return_value=False)
        phase._worktrees.abort_merge = AsyncMock()

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        escalating_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "escalating"
        ]
        assert len(escalating_events) == 1
        assert escalating_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_merging_status_emitted_before_merge(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'merging' event should be published before merging the PR."""
        phase = make_review_phase(config, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        merging_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "merging"
        ]
        assert len(merging_events) == 1
        assert merging_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_escalating_status_emitted_on_merge_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """An 'escalating' event should be published when PR merge fails."""
        phase = make_review_phase(config, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.merge_pr = AsyncMock(return_value=False)
        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        escalating_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "escalating"
        ]
        assert len(escalating_events) == 1
        assert escalating_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_ci_wait_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'ci_wait' event should be published before waiting for CI."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        ci_wait_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "ci_wait"
        ]
        assert len(ci_wait_events) == 1
        assert ci_wait_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_ci_fix_status_emitted(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """A 'ci_fix' event should be published before running the CI fix agent."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=2,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        ci_results = [
            (False, "Failed checks: ci"),
            (True, "All checks passed"),
        ]
        ci_call_count = 0

        async def fake_wait_for_ci(_pr_num, _timeout, _interval, _stop):
            nonlocal ci_call_count
            result = ci_results[ci_call_count]
            ci_call_count += 1
            return result

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = fake_wait_for_ci

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        ci_fix_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "ci_fix"
        ]
        assert len(ci_fix_events) == 1
        assert ci_fix_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_escalating_status_emitted_on_ci_exhaustion(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """An 'escalating' event should be published when CI fix attempts are exhausted."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            max_ci_fix_attempts=1,
            repo_root=config.repo_root,
            worktree_base=config.worktree_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        fix_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )

        phase._reviewers.fix_ci = AsyncMock(return_value=fix_result)
        phase._prs.wait_for_ci = AsyncMock(return_value=(False, "Failed checks: ci"))

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        escalating_events = [
            e
            for e in history
            if e.type == EventType.REVIEW_UPDATE
            and e.data.get("status") == "escalating"
        ]
        assert len(escalating_events) == 1
        assert escalating_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_event_ordering_happy_path(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        """Events should be emitted in order: start -> merge_main -> reviewing -> merging."""
        phase = make_review_phase(config, default_mocks=True, event_bus=event_bus)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        await phase.review_prs([pr], [issue])

        history = event_bus.get_history()
        review_statuses = [
            e.data["status"] for e in history if e.type == EventType.REVIEW_UPDATE
        ]
        assert review_statuses.index("start") < review_statuses.index("merge_main")
        assert review_statuses.index("merge_main") < review_statuses.index("merging")
        assert review_statuses[-1] == "done"


# ---------------------------------------------------------------------------
# _count_review_findings
# ---------------------------------------------------------------------------


class TestCountReviewFindings:
    """Tests for ReviewPhase._count_review_findings."""

    def test_counts_bullet_points(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("- Fix A\n- Fix B\n- Fix C") == 3

    def test_counts_numbered_items(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("1. Fix A\n2. Fix B") == 2

    def test_counts_asterisk_bullets(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("* Fix A\n* Fix B") == 2

    def test_counts_mixed_formats(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        summary = "- Bullet item\n1. Numbered item\n* Star item"
        assert phase._count_review_findings(summary) == 3

    def test_returns_zero_for_no_findings(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("All looks good.") == 0

    def test_returns_zero_for_empty_string(self, config: HydraFlowConfig) -> None:
        phase = make_review_phase(config)
        assert phase._count_review_findings("") == 0


# ---------------------------------------------------------------------------
# Self-fix re-review
# ---------------------------------------------------------------------------


class TestSelfFixReReview:
    """Tests for the self-fix re-review logic.

    When the reviewer fixes its own findings (fixes_made=True) but still
    returns REQUEST_CHANGES or COMMENT, the phase should re-review the
    updated code and upgrade the verdict to APPROVE if the re-review passes.
    """

    def _setup_phase(self, config: HydraFlowConfig) -> tuple[ReviewPhase, PRInfo, Task]:
        """Helper to set up a ReviewPhase ready for self-fix re-review tests."""
        phase = make_review_phase(config, default_mocks=True)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        phase._prs.remove_pr_label = AsyncMock()
        phase._prs.add_pr_labels = AsyncMock()
        phase._prs.post_comment = AsyncMock()

        return phase, pr, issue

    @pytest.mark.asyncio
    async def test_self_fix_with_re_review_approve_upgrades_verdict(
        self, config: HydraFlowConfig
    ) -> None:
        """fixes_made=True + REQUEST_CHANGES → re-review APPROVE → merge."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        results = await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 2
        phase._prs.merge_pr.assert_awaited_once()
        assert results[0].verdict == ReviewVerdict.APPROVE
        # Label should NOT be swapped to ready
        for call_args in phase._prs.add_labels.call_args_list:
            assert call_args[0][1] != config.ready_label

    @pytest.mark.asyncio
    async def test_self_fix_with_re_review_reject_preserves_behavior(
        self, config: HydraFlowConfig
    ) -> None:
        """fixes_made=True + REQUEST_CHANGES → re-review REQUEST_CHANGES → re-queue."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 2
        phase._prs.merge_pr.assert_not_awaited()
        # Should swap labels to ready (re-queue)
        phase._prs.transition.assert_any_await(
            pr.issue_number, "ready", pr_number=pr.number
        )
        assert phase._state.get_review_attempts(42) == 1

    @pytest.mark.asyncio
    async def test_no_fixes_no_re_review(self, config: HydraFlowConfig) -> None:
        """fixes_made=False + REQUEST_CHANGES → no re-review, just re-queue."""
        phase, pr, issue = self._setup_phase(config)

        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(return_value=result)

        await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 1
        phase._prs.transition.assert_any_await(
            pr.issue_number, "ready", pr_number=pr.number
        )

    @pytest.mark.asyncio
    async def test_self_fix_comment_verdict_triggers_re_review(
        self, config: HydraFlowConfig
    ) -> None:
        """fixes_made=True + COMMENT → re-review APPROVE → merge."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.COMMENT,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        results = await phase.review_prs([pr], [issue])

        assert phase._reviewers.review.await_count == 2
        phase._prs.merge_pr.assert_awaited_once()
        assert results[0].verdict == ReviewVerdict.APPROVE

    @pytest.mark.asyncio
    async def test_self_fix_re_review_pushes_additional_fixes(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review with fixes_made=True should push additional fixes."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        await phase.review_prs([pr], [issue])

        # push_branch called for: merge-main, initial fixes (in _run_and_post_review),
        # and re-review fixes
        assert phase._prs.push_branch.await_count == 3

    @pytest.mark.asyncio
    async def test_self_fix_re_review_approve_does_not_increment_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """Self-fix + re-review APPROVE should NOT increment review attempts."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        second_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )
        phase._reviewers.review = AsyncMock(side_effect=[first_result, second_result])

        await phase.review_prs([pr], [issue])

        assert phase._state.get_review_attempts(42) == 0

    @pytest.mark.asyncio
    async def test_re_review_exception_falls_back_to_rejection(
        self, config: HydraFlowConfig
    ) -> None:
        """Re-review exception falls back gracefully to original rejection (re-queue)."""
        phase, pr, issue = self._setup_phase(config)

        first_result = ReviewResultFactory.create(
            verdict=ReviewVerdict.REQUEST_CHANGES,
            fixes_made=True,
        )
        phase._reviewers.review = AsyncMock(
            side_effect=[first_result, RuntimeError("transient re-review failure")]
        )

        await phase.review_prs([pr], [issue])

        # Both calls attempted
        assert phase._reviewers.review.await_count == 2
        # Exception falls back to original rejection — no merge
        phase._prs.merge_pr.assert_not_awaited()
        # Label swapped to ready (re-queue as original REQUEST_CHANGES)
        phase._prs.transition.assert_any_await(
            pr.issue_number, "ready", pr_number=pr.number
        )
        assert phase._state.get_review_attempts(pr.issue_number) == 1


# ---------------------------------------------------------------------------
# Verification Issue Creation
# ---------------------------------------------------------------------------


def _make_judge_result(
    issue_number: int = 42,
    pr_number: int = 101,
    criteria: list[VerificationCriterion] | None = None,
    verification_instructions: str = "1. Run the app\n2. Click the button",
    all_pass: bool = True,
) -> JudgeResult:
    """Build a JudgeResult for testing."""
    if criteria is None:
        if all_pass:
            criteria = [
                VerificationCriterion(
                    description="Unit tests pass", passed=True, details="All pass"
                ),
                VerificationCriterion(
                    description="Lint passes", passed=True, details="Clean"
                ),
            ]
        else:
            criteria = [
                VerificationCriterion(
                    description="Unit tests pass", passed=True, details="All pass"
                ),
                VerificationCriterion(
                    description="Lint passes", passed=False, details="3 errors found"
                ),
            ]
    return JudgeResult(
        issue_number=issue_number,
        pr_number=pr_number,
        criteria=criteria,
        verification_instructions=verification_instructions,
    )


class TestCreateVerificationIssue:
    """Tests for ReviewPhase._create_verification_issue."""

    @pytest.mark.asyncio
    async def test_creates_issue_all_criteria_passed(
        self, config: HydraFlowConfig
    ) -> None:
        """Judge with all criteria passing creates issue with correct title and label."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(title="Fix the frobnicator")
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=500)

        result = await phase._create_verification_issue(issue, pr, judge)

        assert result == 500
        phase._prs.create_issue.assert_awaited_once()
        call_args = phase._prs.create_issue.call_args
        title = call_args[0][0]
        body = call_args[0][1]
        labels = call_args[0][2]

        assert title == "Verify: Fix the frobnicator"
        assert labels == ["hydraflow-hitl"]
        assert "All criteria passed at code level" in body
        assert "#42" in body
        assert "#101" in body

    @pytest.mark.asyncio
    async def test_creates_issue_with_failed_criteria(
        self, config: HydraFlowConfig
    ) -> None:
        """Judge with mixed results highlights failures in the body."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result(all_pass=False)

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        body = phase._prs.create_issue.call_args[0][1]
        assert "failed at code level" in body
        assert "pay extra attention" in body
        assert "\u274c FAIL" in body

    @pytest.mark.asyncio
    async def test_creates_issue_includes_verification_instructions(
        self, config: HydraFlowConfig
    ) -> None:
        """Body includes the verification instructions from judge result."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result(
            verification_instructions="1. Start server\n2. Check /health"
        )

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        body = phase._prs.create_issue.call_args[0][1]
        assert "Verification Instructions" in body
        assert "Start server" in body
        assert "Check /health" in body

    @pytest.mark.asyncio
    async def test_creates_issue_includes_links(self, config: HydraFlowConfig) -> None:
        """Body contains references to the original issue and PR."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(id=99, title="Add auth")
        pr = PRInfoFactory.create(number=200, issue_number=99)
        judge = _make_judge_result(issue_number=99, pr_number=200)

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        body = phase._prs.create_issue.call_args[0][1]
        assert "#99" in body
        assert "#200" in body

    @pytest.mark.asyncio
    async def test_returns_zero_on_failure(self, config: HydraFlowConfig) -> None:
        """When create_issue returns 0, method returns 0."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=0)

        result = await phase._create_verification_issue(issue, pr, judge)

        assert result == 0

    @pytest.mark.asyncio
    async def test_state_tracked_on_success(self, config: HydraFlowConfig) -> None:
        """After successful creation, state tracks the verification issue."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=500)

        await phase._create_verification_issue(issue, pr, judge)

        assert phase._state.get_verification_issue(42) == 500

    @pytest.mark.asyncio
    async def test_state_not_tracked_on_failure(self, config: HydraFlowConfig) -> None:
        """When create_issue returns 0, state is not updated."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        phase._prs.create_issue = AsyncMock(return_value=0)

        await phase._create_verification_issue(issue, pr, judge)

        assert phase._state.get_verification_issue(42) is None


# ---------------------------------------------------------------------------
# _get_judge_result conversion
# ---------------------------------------------------------------------------


class TestGetJudgeResult:
    """Tests for ReviewPhase._get_judge_result verdict-to-result conversion."""

    def test_returns_none_when_verdict_is_none(self, config: HydraFlowConfig) -> None:
        """When no verdict is produced, returns None."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        result = phase._get_judge_result(issue, pr, None)

        assert result is None

    def test_maps_pass_criterion(self, config: HydraFlowConfig) -> None:
        """PASS criterion is converted with passed=True."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Tests pass",
                ),
            ],
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 1
        assert result.criteria[0].description == "AC-1"
        assert result.criteria[0].passed is True
        assert result.criteria[0].details == "Tests pass"

    def test_maps_fail_criterion(self, config: HydraFlowConfig) -> None:
        """FAIL criterion is converted with passed=False."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-2",
                    verdict=CriterionVerdict.FAIL,
                    reasoning="No test coverage",
                ),
            ],
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 1
        assert result.criteria[0].passed is False
        assert result.criteria[0].details == "No test coverage"

    def test_maps_mixed_criteria(self, config: HydraFlowConfig) -> None:
        """Multiple criteria with mixed verdicts are all converted."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="OK",
                ),
                CriterionResult(
                    criterion="AC-2",
                    verdict=CriterionVerdict.FAIL,
                    reasoning="Missing",
                ),
                CriterionResult(
                    criterion="AC-3",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Covered",
                ),
            ],
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert len(result.criteria) == 3
        assert result.criteria[0].passed is True
        assert result.criteria[1].passed is False
        assert result.criteria[2].passed is True

    def test_passes_through_verification_instructions(
        self, config: HydraFlowConfig
    ) -> None:
        """verification_instructions from verdict flows to result."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            verification_instructions="1. Run app\n2. Check output",
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.verification_instructions == "1. Run app\n2. Check output"

    def test_passes_through_summary(self, config: HydraFlowConfig) -> None:
        """summary from verdict flows to result."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(
            issue_number=issue.id,
            summary="2/3 criteria passed, instructions: ready",
        )

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.summary == "2/3 criteria passed, instructions: ready"

    def test_uses_issue_and_pr_numbers(self, config: HydraFlowConfig) -> None:
        """issue_number and pr_number come from the issue/pr args, not verdict."""
        phase = make_review_phase(config)
        issue = TaskFactory.create(id=99)
        pr = PRInfoFactory.create(number=200, issue_number=99)
        verdict = JudgeVerdict(issue_number=99)

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.issue_number == 99
        assert result.pr_number == 200

    def test_empty_criteria(self, config: HydraFlowConfig) -> None:
        """Verdict with no criteria produces result with empty criteria list."""
        phase = make_review_phase(config)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        verdict = JudgeVerdict(issue_number=issue.id)

        result = phase._get_judge_result(issue, pr, verdict)

        assert result is not None
        assert result.criteria == []


# ---------------------------------------------------------------------------
# _run_delta_verification
# ---------------------------------------------------------------------------


class TestRunDeltaVerification:
    """Regression tests for _run_delta_verification using .hydraflow/plans/."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_plan_file_missing(
        self, config: HydraFlowConfig
    ) -> None:
        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=99)

        result = await phase._run_delta_verification(pr, "some diff")

        assert result == ""

    @pytest.mark.asyncio
    async def test_reads_plan_from_hydraflow_plans_dir(
        self, config: HydraFlowConfig
    ) -> None:
        from unittest.mock import patch

        plan_content = "## File Delta\n\n```\nMODIFIED: foo.py\nMODIFIED: bar.py\n```\n"
        plans_dir = config.repo_root / ".hydraflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "issue-42.md").write_text(plan_content)

        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=42)

        with (
            patch("delta_verifier.parse_file_delta") as mock_parse,
            patch("delta_verifier.verify_delta") as mock_verify,
        ):
            mock_parse.return_value = ["foo.py", "bar.py"]
            mock_report = mock_verify.return_value
            mock_report.has_drift = False

            await phase._run_delta_verification(pr, "some diff")

            mock_parse.assert_called_once_with(plan_content)

    @pytest.mark.asyncio
    async def test_returns_empty_when_parse_returns_empty_list(
        self, config: HydraFlowConfig
    ) -> None:
        """Plan file exists but has no File Delta section → returns empty string."""
        plans_dir = config.repo_root / ".hydraflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "issue-42.md").write_text("## Implementation\nSome plan text.")

        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=42)

        with patch("delta_verifier.parse_file_delta", return_value=[]):
            result = await phase._run_delta_verification(pr, "diff")

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_summary_on_drift(self, config: HydraFlowConfig) -> None:
        """When verify_delta reports drift, should return non-empty summary."""
        from models import DeltaReport

        plans_dir = config.repo_root / ".hydraflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "issue-42.md").write_text(
            "## File Delta\n\n```\nMODIFIED: foo.py\n```\n"
        )

        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=42)
        phase._prs.get_pr_diff_names = AsyncMock(return_value=["bar.py"])

        drift_report = DeltaReport(
            planned=["foo.py"],
            actual=["bar.py"],
            missing=["foo.py"],
            unexpected=["bar.py"],
        )

        with (
            patch("delta_verifier.parse_file_delta", return_value=["foo.py"]),
            patch("delta_verifier.verify_delta", return_value=drift_report),
        ):
            result = await phase._run_delta_verification(pr, "diff")

        assert result != ""
        assert "foo.py" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_plan_read_oserror(
        self, config: HydraFlowConfig
    ) -> None:
        """Plan file exists but reading raises OSError → returns empty string."""
        plans_dir = config.repo_root / ".hydraflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plans_dir / "issue-42.md"
        plan_file.write_text("some content")

        phase = make_review_phase(config)
        pr = PRInfoFactory.create(issue_number=42)

        with patch.object(
            type(plan_file), "read_text", side_effect=OSError("disk error")
        ):
            result = await phase._run_delta_verification(pr, "diff")

        assert result == ""

    @pytest.mark.asyncio
    async def test_calls_get_pr_diff_names(self, config: HydraFlowConfig) -> None:
        """Should call get_pr_diff_names with the PR number."""
        plans_dir = config.repo_root / ".hydraflow" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        (plans_dir / "issue-42.md").write_text(
            "## File Delta\n\n```\nMODIFIED: foo.py\n```\n"
        )

        phase = make_review_phase(config)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        phase._prs.get_pr_diff_names = AsyncMock(return_value=["foo.py"])

        with (
            patch("delta_verifier.parse_file_delta", return_value=["foo.py"]),
            patch("delta_verifier.verify_delta") as mock_verify,
        ):
            mock_verify.return_value.has_drift = False
            await phase._run_delta_verification(pr, "diff")

        phase._prs.get_pr_diff_names.assert_awaited_once_with(101)


# ---------------------------------------------------------------------------
# _record_review_insight
# ---------------------------------------------------------------------------


class TestRecordReviewInsight:
    """Tests for ReviewPhase._record_review_insight."""

    @pytest.mark.asyncio
    async def test_appends_review_record_on_approve(
        self, config: HydraFlowConfig
    ) -> None:
        """Should append a ReviewRecord to the insight store for every result."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(
            verdict=ReviewVerdict.APPROVE,
            fixes_made=False,
        )

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = []
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        with patch("review_phase.analyze_patterns", return_value=[]):
            await phase._record_review_insight(result)

        mock_insights.append_review.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_issue_when_pattern_detected(
        self, config: HydraFlowConfig
    ) -> None:
        """When a recurring pattern is detected, a GitHub improvement issue is created."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)
        phase._prs.create_task = AsyncMock(return_value=123)

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = [MagicMock()] * 5
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        from review_insights import ReviewRecord

        mock_evidence = [
            ReviewRecord(
                pr_number=101,
                issue_number=42,
                timestamp="2026-01-01T00:00:00",
                verdict="request-changes",
                summary="Missing tests",
                fixes_made=False,
                categories=["test_coverage"],
            ),
            ReviewRecord(
                pr_number=102,
                issue_number=43,
                timestamp="2026-01-02T00:00:00",
                verdict="request-changes",
                summary="Missing tests again",
                fixes_made=False,
                categories=["test_coverage"],
            ),
        ]
        with patch(
            "review_phase.analyze_patterns",
            return_value=[("test_coverage", 4, mock_evidence)],
        ):
            await phase._record_review_insight(result)

        phase._prs.create_task.assert_awaited_once()
        call_title, _call_body, call_labels = phase._prs.create_task.call_args[0]
        assert (
            "test_coverage" in call_title.lower() or "Recurring feedback" in call_title
        )
        assert config.improve_label[0] in call_labels
        mock_insights.mark_category_proposed.assert_called_once_with("test_coverage")

    @pytest.mark.asyncio
    async def test_skips_already_proposed_category(
        self, config: HydraFlowConfig
    ) -> None:
        """Should not create a duplicate issue for an already-proposed category."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(verdict=ReviewVerdict.REQUEST_CHANGES)
        phase._prs.create_task = AsyncMock(return_value=None)

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = [MagicMock()] * 5
        mock_insights.get_proposed_categories.return_value = {"test_coverage"}
        phase._insights = mock_insights

        mock_evidence = [
            MagicMock(pr_number=1, issue_number=10, summary="needs tests"),
            MagicMock(pr_number=2, issue_number=20, summary="missing coverage"),
        ]
        with patch(
            "review_phase.analyze_patterns",
            return_value=[("test_coverage", 4, mock_evidence)],
        ):
            await phase._record_review_insight(result)

        phase._prs.create_task.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sets_hitl_state_when_issue_created(
        self, config: HydraFlowConfig
    ) -> None:
        """When an insight issue is created, HITL origin and cause are recorded in state."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(
            issue_number=42, verdict=ReviewVerdict.REQUEST_CHANGES
        )
        phase._prs.create_task = AsyncMock(return_value=99)

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = [MagicMock()] * 5
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        from review_insights import ReviewRecord

        mock_evidence = [
            ReviewRecord(
                pr_number=10,
                issue_number=42,
                timestamp="2026-01-01T00:00:00",
                verdict="request-changes",
                summary="Type errors found",
                fixes_made=False,
                categories=["type_errors"],
            ),
        ]
        with patch(
            "review_phase.analyze_patterns",
            return_value=[("type_errors", 3, mock_evidence)],
        ):
            await phase._record_review_insight(result)

        assert phase._state.get_hitl_origin(99) == config.improve_label[0]
        cause = phase._state.get_hitl_cause(99)
        assert cause is not None and "Recurring review pattern" in cause

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self, config: HydraFlowConfig) -> None:
        """Any exception during insight recording is swallowed — review flow continues."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create()

        mock_insights = MagicMock()
        mock_insights.append_review.side_effect = RuntimeError("disk full")
        phase._insights = mock_insights

        # Should not raise
        await phase._record_review_insight(result)

    @pytest.mark.asyncio
    async def test_updates_bg_status_on_success(self, config: HydraFlowConfig) -> None:
        """Successful insight recording should update review_insights worker status."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(issue_number=42, pr_number=101)
        status_cb = MagicMock()
        phase._update_bg_worker_status = status_cb

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = []
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        with patch("review_phase.analyze_patterns", return_value=[]):
            await phase._record_review_insight(result)

        status_cb.assert_called_with(
            "review_insights",
            "ok",
            {"issue_number": 42, "pr_number": 101},
        )

    @pytest.mark.asyncio
    async def test_updates_bg_status_on_error(self, config: HydraFlowConfig) -> None:
        """Insight recording failure should mark review_insights worker as error."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(issue_number=42, pr_number=101)
        status_cb = MagicMock()
        phase._update_bg_worker_status = status_cb

        mock_insights = MagicMock()
        mock_insights.append_review.side_effect = RuntimeError("disk full")
        phase._insights = mock_insights

        await phase._record_review_insight(result)

        status_cb.assert_called_with(
            "review_insights",
            "error",
            {
                "issue_number": 42,
                "pr_number": 101,
                "error": "review insight recording failed",
            },
        )

    @pytest.mark.asyncio
    async def test_status_callback_error_is_swallowed(
        self, config: HydraFlowConfig
    ) -> None:
        """Status callback failures must not break review insight recording."""
        phase = make_review_phase(config)
        result = ReviewResultFactory.create(issue_number=42, pr_number=101)
        status_cb = MagicMock(side_effect=RuntimeError("status boom"))
        phase._update_bg_worker_status = status_cb

        mock_insights = MagicMock()
        mock_insights.load_recent.return_value = []
        mock_insights.get_proposed_categories.return_value = set()
        phase._insights = mock_insights

        with patch("review_phase.analyze_patterns", return_value=[]):
            await phase._record_review_insight(result)

        mock_insights.append_review.assert_called_once()
