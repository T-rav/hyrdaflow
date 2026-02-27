"""Tests for race condition guards added in issue #1036.

Verifies that asyncio.Lock guards exist and protect shared mutable state
in concurrent async contexts, that PRManager cache is per-instance, and
that EventBus.publish iterates a snapshot of subscribers.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus, EventType
from tests.conftest import EventFactory, TaskFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# ImplementPhase — active issues lock
# ---------------------------------------------------------------------------


class TestImplementPhaseActiveIssuesLock:
    """ImplementPhase protects _active_issues with an asyncio.Lock."""

    def _make_phase(self, tmp_path):
        """Build an ImplementPhase with mocked dependencies."""
        from implement_phase import ImplementPhase
        from state import StateTracker

        config = ConfigFactory.create(
            worktree_base=tmp_path / "worktrees",
            repo_root=tmp_path / "repo",
        )
        state = StateTracker(tmp_path / "state.json")
        return ImplementPhase(
            config=config,
            state=state,
            worktrees=AsyncMock(),
            agents=AsyncMock(),
            prs=AsyncMock(),
            store=AsyncMock(),
            stop_event=asyncio.Event(),
        )

    def test_has_active_issues_lock(self, tmp_path) -> None:
        phase = self._make_phase(tmp_path)
        assert hasattr(phase, "_active_issues_lock")
        assert isinstance(phase._active_issues_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_concurrent_workers_produce_consistent_active_set(
        self, tmp_path
    ) -> None:
        """Multiple concurrent workers never produce a partial snapshot."""
        from implement_phase import ImplementPhase
        from models import WorkerResult
        from state import StateTracker

        config = ConfigFactory.create(
            worktree_base=tmp_path / "worktrees",
            repo_root=tmp_path / "repo",
            max_workers=3,
        )
        state = StateTracker(tmp_path / "state.json")

        # Track all values passed to set_active_issue_numbers
        recorded_sets: list[list[int]] = []
        original_set = state.set_active_issue_numbers

        def recording_set(numbers: list[int]) -> None:
            recorded_sets.append(sorted(numbers))
            original_set(numbers)

        state.set_active_issue_numbers = recording_set  # type: ignore[assignment]

        mock_store = AsyncMock()
        mock_store.mark_active = MagicMock()
        mock_store.mark_complete = MagicMock()

        mock_agents = AsyncMock()
        mock_agents.run = AsyncMock(
            side_effect=lambda issue, wt, br, **_kw: WorkerResult(
                issue_number=issue.number,
                branch=br,
                success=True,
                commits=1,
                worktree_path=str(wt),
            )
        )

        mock_prs = AsyncMock()
        mock_prs.push_branch = AsyncMock(return_value=True)
        mock_prs.create_pr = AsyncMock(return_value=MagicMock(number=0, issue_number=0))
        mock_prs.remove_label = AsyncMock()
        mock_prs.add_labels = AsyncMock()
        mock_prs.swap_pipeline_labels = AsyncMock()
        mock_prs.post_comment = AsyncMock()
        mock_prs.close_issue = AsyncMock()

        mock_worktrees = AsyncMock()
        mock_worktrees.create = AsyncMock(
            side_effect=lambda num, _branch: tmp_path / "worktrees" / f"issue-{num}"
        )

        phase = ImplementPhase(
            config=config,
            state=state,
            worktrees=mock_worktrees,
            agents=mock_agents,
            prs=mock_prs,
            store=mock_store,
            stop_event=asyncio.Event(),
        )

        issues = [TaskFactory.create(id=i) for i in range(1, 4)]

        # Create worktree dirs so the phase finds them
        for issue in issues:
            wt = tmp_path / "worktrees" / f"issue-{issue.id}"
            wt.mkdir(parents=True, exist_ok=True)

        await phase.run_batch(issues)

        # After all workers complete, active set should be empty
        assert phase._active_issues == set()

        # All recorded sets should be valid subsets of {1, 2, 3}
        valid_numbers = {1, 2, 3}
        for snapshot in recorded_sets:
            assert set(snapshot) <= valid_numbers


# ---------------------------------------------------------------------------
# ReviewPhase — active issues lock
# ---------------------------------------------------------------------------


class TestReviewPhaseActiveIssuesLock:
    """ReviewPhase protects _active_issues with an asyncio.Lock."""

    def _make_phase(self, tmp_path):
        """Build a ReviewPhase with mocked dependencies."""
        from review_phase import ReviewPhase
        from state import StateTracker

        config = ConfigFactory.create(
            worktree_base=tmp_path / "worktrees",
            repo_root=tmp_path / "repo",
        )
        state = StateTracker(tmp_path / "state.json")
        return ReviewPhase(
            config=config,
            state=state,
            worktrees=AsyncMock(),
            reviewers=AsyncMock(),
            prs=AsyncMock(),
            stop_event=asyncio.Event(),
            store=AsyncMock(),
        )

    def test_has_active_issues_lock(self, tmp_path) -> None:
        phase = self._make_phase(tmp_path)
        assert hasattr(phase, "_active_issues_lock")
        assert isinstance(phase._active_issues_lock, asyncio.Lock)


# ---------------------------------------------------------------------------
# EventBus — publish safe during unsubscribe
# ---------------------------------------------------------------------------


class TestEventBusPublishSafeDuringUnsubscribe:
    """EventBus.publish() iterates a snapshot, safe against mid-iteration unsubscribe."""

    @pytest.mark.asyncio
    async def test_unsubscribe_during_publish_no_error(self) -> None:
        """Unsubscribing a queue while publish iterates should not raise."""
        bus = EventBus()
        q1 = bus.subscribe(max_queue=100)
        q2 = bus.subscribe(max_queue=100)

        # Unsubscribe q1 while iterating (simulated by removing it before
        # publish completes — the snapshot ensures this is safe)
        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": 1})

        # Patch put_nowait on q1 to unsubscribe itself mid-iteration
        original_put = q1.put_nowait

        def unsubscribe_on_put(item):
            original_put(item)
            bus.unsubscribe(q1)

        q1.put_nowait = unsubscribe_on_put  # type: ignore[assignment]

        # This should not raise RuntimeError from list modification during iteration
        await bus.publish(event)

        # q2 should still have received the event
        assert not q2.empty()
        assert q2.get_nowait() is event

    @pytest.mark.asyncio
    async def test_subscribe_during_publish_does_not_receive_current_event(
        self,
    ) -> None:
        """A subscriber added during publish should not receive the in-flight event."""
        bus = EventBus()
        q1 = bus.subscribe(max_queue=100)

        new_queue = None
        original_put = q1.put_nowait

        def subscribe_on_put(item):
            nonlocal new_queue
            original_put(item)
            new_queue = bus.subscribe(max_queue=100)

        q1.put_nowait = subscribe_on_put  # type: ignore[assignment]

        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": 1})
        await bus.publish(event)

        # The new subscriber was added after the snapshot, so it should not
        # have received the current event
        assert new_queue is not None
        assert new_queue.empty()


# ---------------------------------------------------------------------------
# PRManager — label cache per instance
# ---------------------------------------------------------------------------


class TestPRManagerLabelCachePerInstance:
    """PRManager._label_counts_cache is per-instance, not shared across instances."""

    def test_cache_is_instance_variable(self) -> None:
        config = ConfigFactory.create()
        bus = EventBus()
        pm1 = _make_pr_manager(config, bus)
        pm2 = _make_pr_manager(config, bus)

        pm1._label_counts_cache = {
            "open_by_label": {},
            "total_closed": 0,
            "total_merged": 0,
        }
        pm1._label_counts_ts = 99.0

        assert pm2._label_counts_cache is None
        assert pm2._label_counts_ts == 0.0

    def test_cache_not_class_attribute(self) -> None:
        """Verify _label_counts_cache is not defined at class level."""
        from pr_manager import PRManager

        # Class should not have _label_counts_cache as a class variable
        assert "_label_counts_cache" not in PRManager.__dict__
        assert "_label_counts_ts" not in PRManager.__dict__


# ---------------------------------------------------------------------------
# Orchestrator — _build_interrupted_issues consistency
# ---------------------------------------------------------------------------


class TestOrchestratorBuildInterruptedIssuesLock:
    """Orchestrator._build_interrupted_issues reads sets under a lock."""

    def test_orchestrator_has_active_issues_lock(self, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        assert hasattr(orch, "_active_issues_lock")
        assert isinstance(orch._active_issues_lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_build_interrupted_issues_is_async(self, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._active_impl_issues = {1, 2}
        orch._active_review_issues = {3}

        result = await orch._build_interrupted_issues()

        assert result[1] == "implement"
        assert result[2] == "implement"
        assert result[3] == "review"

    @pytest.mark.asyncio
    async def test_build_interrupted_includes_hitl(self, tmp_path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._hitl_phase.active_hitl_issues.add(5)

        result = await orch._build_interrupted_issues()

        assert result[5] == "hitl"

    @pytest.mark.asyncio
    async def test_build_interrupted_issues_acquires_lock(self, tmp_path) -> None:
        """Verify that _build_interrupted_issues acquires the lock."""
        orch = _make_orchestrator(tmp_path)
        orch._active_impl_issues = {10}

        lock_acquired = False
        original_acquire = orch._active_issues_lock.acquire

        async def tracking_acquire() -> bool:
            nonlocal lock_acquired
            lock_acquired = True
            return await original_acquire()

        orch._active_issues_lock.acquire = tracking_acquire  # type: ignore[assignment]

        await orch._build_interrupted_issues()
        assert lock_acquired

    @pytest.mark.asyncio
    async def test_do_implement_work_recovered_issues_under_lock(
        self, tmp_path
    ) -> None:
        """Verify recovered issues cleanup acquires the lock."""
        orch = _make_orchestrator(tmp_path)
        orch._recovered_issues = {99}
        orch._active_impl_issues = {99}

        # Mock the implementer to return no results
        orch._implementer.run_batch = AsyncMock(return_value=([], []))

        lock_acquired = False
        original_acquire = orch._active_issues_lock.acquire

        async def tracking_acquire() -> bool:
            nonlocal lock_acquired
            lock_acquired = True
            return await original_acquire()

        orch._active_issues_lock.acquire = tracking_acquire  # type: ignore[assignment]

        await orch._do_implement_work()
        assert lock_acquired
        assert orch._recovered_issues == set()


# ---------------------------------------------------------------------------
# IssueStore — take_from_queue safety documentation
# ---------------------------------------------------------------------------


class TestIssueStoreTakeFromQueueSafety:
    """IssueStore._take_from_queue is synchronous and safe by GIL guarantee."""

    def test_take_from_queue_is_synchronous(self) -> None:
        """Verify _take_from_queue is not a coroutine (safety relies on this)."""
        from issue_store import IssueStore

        assert not inspect.iscoroutinefunction(IssueStore._take_from_queue)

    def test_take_from_queue_docstring_documents_safety(self) -> None:
        from issue_store import IssueStore

        doc = IssueStore._take_from_queue.__doc__ or ""
        assert "synchronous" in doc.lower()
        assert "GIL" in doc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_manager(config=None, bus=None):
    """Create a PRManager with test defaults."""
    from pr_manager import PRManager

    config = config or ConfigFactory.create()
    bus = bus or EventBus()
    return PRManager(config, bus)


def _make_orchestrator(tmp_path):
    """Create a minimal HydraFlowOrchestrator for testing."""
    from orchestrator import HydraFlowOrchestrator

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return HydraFlowOrchestrator(config)
