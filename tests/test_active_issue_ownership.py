"""Tests for issue #5951: Active-issue state ownership.

Verifies that:
- ReviewPhase and ImplementPhase do NOT call StateTracker.set_active_issue_numbers
- Both phases invoke the active_issues_cb callback when active issues change
- Both phases expose an active_issues read-only property
- The orchestrator is the sole writer to set_active_issue_numbers
- _sync_active_issue_numbers merges all three phase sources
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.conftest import PRInfoFactory, TaskFactory, WorkerResultFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# ImplementPhase — callback and property
# ---------------------------------------------------------------------------


class TestImplementPhaseActiveIssueOwnership:
    """ImplementPhase delegates active-issue state to the orchestrator via callback."""

    def _make_phase(self, tmp_path, *, active_issues_cb=None):
        from implement_phase import ImplementPhase
        from state import StateTracker

        config = ConfigFactory.create(
            workspace_base=tmp_path / "worktrees",
            repo_root=tmp_path / "repo",
            max_workers=1,
        )
        state = StateTracker(tmp_path / "state.json")

        mock_agents = AsyncMock()
        mock_agents.run = AsyncMock(
            side_effect=lambda issue, wt, br, **_kw: WorkerResultFactory.create(
                issue_number=issue.id,
                branch=br,
                success=True,
                commits=1,
                workspace_path=str(wt),
                use_defaults=True,
            )
        )

        mock_prs = AsyncMock()
        mock_prs.push_branch = AsyncMock(return_value=True)
        mock_prs.create_pr = AsyncMock(return_value=MagicMock(number=0, issue_number=0))
        mock_prs.post_comment = AsyncMock()

        mock_wt = AsyncMock()
        mock_wt.create = AsyncMock(
            side_effect=lambda num, _br: tmp_path / "worktrees" / f"issue-{num}"
        )

        mock_store = AsyncMock()
        mock_store.mark_active = MagicMock()
        mock_store.mark_complete = MagicMock()

        phase = ImplementPhase(
            config=config,
            state=state,
            workspaces=mock_wt,
            agents=mock_agents,
            prs=mock_prs,
            store=mock_store,
            stop_event=asyncio.Event(),
            active_issues_cb=active_issues_cb,
        )
        return phase, state

    def test_active_issues_property_returns_set(self, tmp_path):
        """active_issues property exposes the internal tracking set."""
        phase, _ = self._make_phase(tmp_path)
        assert isinstance(phase.active_issues, set)
        assert len(phase.active_issues) == 0

    def test_active_issues_property_reflects_mutations(self, tmp_path):
        """The property reflects changes to the internal set."""
        phase, _ = self._make_phase(tmp_path)
        phase._active_issues.add(42)
        assert 42 in phase.active_issues

    @pytest.mark.asyncio
    async def test_callback_invoked_on_worker_start_and_finish(self, tmp_path):
        """active_issues_cb is called when a worker starts and finishes."""
        cb = MagicMock()
        phase, _ = self._make_phase(tmp_path, active_issues_cb=cb)

        issues = [TaskFactory.create(id=1)]
        wt = tmp_path / "worktrees" / "issue-1"
        wt.mkdir(parents=True, exist_ok=True)

        await phase.run_batch(issues)

        # Callback called at least twice: once on add, once on discard
        assert cb.call_count >= 2

    @pytest.mark.asyncio
    async def test_no_direct_state_write(self, tmp_path):
        """ImplementPhase never calls state.set_active_issue_numbers directly."""
        cb = MagicMock()
        phase, state = self._make_phase(tmp_path, active_issues_cb=cb)

        issues = [TaskFactory.create(id=1)]
        wt = tmp_path / "worktrees" / "issue-1"
        wt.mkdir(parents=True, exist_ok=True)

        with patch.object(state, "set_active_issue_numbers") as mock_set:
            await phase.run_batch(issues)
            mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_callback_when_none(self, tmp_path):
        """Phase works without a callback (backward compatibility)."""
        phase, _ = self._make_phase(tmp_path, active_issues_cb=None)

        issues = [TaskFactory.create(id=1)]
        wt = tmp_path / "worktrees" / "issue-1"
        wt.mkdir(parents=True, exist_ok=True)

        # Should not raise
        await phase.run_batch(issues)
        assert phase.active_issues == set()


# ---------------------------------------------------------------------------
# ReviewPhase — callback and property
# ---------------------------------------------------------------------------


class TestReviewPhaseActiveIssueOwnership:
    """ReviewPhase delegates active-issue state to the orchestrator via callback."""

    def _make_phase(self, tmp_path, *, active_issues_cb=None):
        from events import EventBus
        from review_phase import ReviewPhase
        from state import StateTracker

        config = ConfigFactory.create(
            workspace_base=tmp_path / "worktrees",
            repo_root=tmp_path / "repo",
        )
        state = StateTracker(tmp_path / "state.json")

        mock_wt = AsyncMock()
        mock_reviewers = AsyncMock()
        mock_prs = AsyncMock()
        mock_prs.expected_pr_title = MagicMock(return_value="Fixes #0: test")
        mock_store = MagicMock()
        mock_store.mark_active = lambda _num, _stage: None
        mock_store.mark_complete = lambda _num: None

        bus = EventBus()

        phase = ReviewPhase(
            config,
            state,
            mock_wt,
            mock_reviewers,
            mock_prs,
            asyncio.Event(),
            mock_store,
            MagicMock(),  # conflict_resolver
            MagicMock(),  # post_merge
            event_bus=bus,
            active_issues_cb=active_issues_cb,
        )
        return phase, state, mock_reviewers, mock_prs

    def test_active_issues_property_returns_set(self, tmp_path):
        """active_issues property exposes the internal tracking set."""
        phase, *_ = self._make_phase(tmp_path)
        assert isinstance(phase.active_issues, set)
        assert len(phase.active_issues) == 0

    def test_active_issues_property_reflects_mutations(self, tmp_path):
        """The property reflects changes to the internal set."""
        phase, *_ = self._make_phase(tmp_path)
        phase._active_issues.add(99)
        assert 99 in phase.active_issues

    @pytest.mark.asyncio
    async def test_no_direct_state_write_during_review(self, tmp_path):
        """ReviewPhase never calls state.set_active_issue_numbers directly."""
        from tests.conftest import ReviewResultFactory

        cb = MagicMock()
        phase, state, mock_reviewers, mock_prs = self._make_phase(
            tmp_path, active_issues_cb=cb
        )

        mock_reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                pr_number=10, issue_number=1, use_defaults=True
            )
        )
        mock_prs.get_pr_diff = AsyncMock(return_value="diff")

        pr = PRInfoFactory.create(number=10, issue_number=1)
        issue = TaskFactory.create(id=1)

        with patch.object(state, "set_active_issue_numbers") as mock_set:
            await phase.review_prs([pr], [issue])
            mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_invoked_during_review(self, tmp_path):
        """active_issues_cb is called when review starts and finishes."""
        from tests.conftest import ReviewResultFactory

        cb = MagicMock()
        phase, _, mock_reviewers, mock_prs = self._make_phase(
            tmp_path, active_issues_cb=cb
        )

        mock_reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                pr_number=10, issue_number=1, use_defaults=True
            )
        )
        mock_prs.get_pr_diff = AsyncMock(return_value="diff")

        pr = PRInfoFactory.create(number=10, issue_number=1)
        issue = TaskFactory.create(id=1)

        await phase.review_prs([pr], [issue])

        # Callback called at least twice: once on add, once on discard
        assert cb.call_count >= 2


# ---------------------------------------------------------------------------
# Orchestrator — sole writer via _sync_active_issue_numbers
# ---------------------------------------------------------------------------


class TestOrchestratorSoleWriter:
    """Orchestrator._sync_active_issue_numbers merges all phase sources."""

    def _make_orchestrator(self, tmp_path):
        from orchestrator import HydraFlowOrchestrator

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        return HydraFlowOrchestrator(config)

    def test_sync_merges_all_three_sources(self, tmp_path):
        """_sync_active_issue_numbers writes the union of impl + review + hitl."""
        orch = self._make_orchestrator(tmp_path)

        orch._svc.implementer.active_issues.add(1)
        orch._svc.reviewer.active_issues.add(2)
        orch._svc.hitl_phase.active_hitl_issues.add(3)

        orch._sync_active_issue_numbers()

        persisted = set(orch._state.get_active_issue_numbers())
        assert persisted == {1, 2, 3}

    def test_sync_with_overlapping_issues(self, tmp_path):
        """Overlapping issues across phases are deduplicated."""
        orch = self._make_orchestrator(tmp_path)

        orch._svc.implementer.active_issues.update({1, 2})
        orch._svc.reviewer.active_issues.update({2, 3})

        orch._sync_active_issue_numbers()

        persisted = set(orch._state.get_active_issue_numbers())
        assert persisted == {1, 2, 3}

    def test_sync_empty_when_no_active_issues(self, tmp_path):
        """Empty sets produce an empty persisted list."""
        orch = self._make_orchestrator(tmp_path)

        orch._sync_active_issue_numbers()

        persisted = orch._state.get_active_issue_numbers()
        assert persisted == []

    def test_reset_clears_phase_sets(self, tmp_path):
        """reset() clears all phase active-issue sets."""
        orch = self._make_orchestrator(tmp_path)

        orch._svc.implementer.active_issues.add(1)
        orch._svc.reviewer.active_issues.add(2)
        orch._svc.hitl_phase.active_hitl_issues.add(3)

        orch.reset()

        assert len(orch._svc.implementer.active_issues) == 0
        assert len(orch._svc.reviewer.active_issues) == 0
        assert len(orch._svc.hitl_phase.active_hitl_issues) == 0

    def test_reset_persists_empty_active_issue_numbers(self, tmp_path):
        """reset() syncs the cleared sets to persisted state via _sync_active_issue_numbers."""
        orch = self._make_orchestrator(tmp_path)

        # Populate persisted state
        orch._svc.implementer.active_issues.add(1)
        orch._svc.reviewer.active_issues.add(2)
        orch._sync_active_issue_numbers()
        assert set(orch._state.get_active_issue_numbers()) == {1, 2}

        # reset() must clear the persisted list too
        orch.reset()

        assert orch._state.get_active_issue_numbers() == []

    def test_phases_have_callback_wired(self, tmp_path):
        """ImplementPhase, ReviewPhase, and HITLPhase all have the callback wired."""
        orch = self._make_orchestrator(tmp_path)

        assert orch._svc.implementer._active_issues_cb is not None
        assert orch._svc.reviewer._active_issues_cb is not None
        assert orch._svc.hitl_phase._active_issues_cb is not None

    def test_callback_triggers_sync(self, tmp_path):
        """Invoking the callback persists the merged active set."""
        orch = self._make_orchestrator(tmp_path)

        # Simulate what a phase does: add to its set, then call the callback
        orch._svc.implementer.active_issues.add(42)
        orch._svc.implementer._active_issues_cb()

        persisted = set(orch._state.get_active_issue_numbers())
        assert 42 in persisted

    @pytest.mark.asyncio
    async def test_build_interrupted_issues_reads_from_phase_properties(self, tmp_path):
        """_build_interrupted_issues snapshots from phase active_issues properties."""
        orch = self._make_orchestrator(tmp_path)

        orch._svc.implementer.active_issues.add(10)
        orch._svc.reviewer.active_issues.add(20)

        interrupted = await orch._build_interrupted_issues()

        assert interrupted.get(10) == "implement"
        assert interrupted.get(20) == "review"
