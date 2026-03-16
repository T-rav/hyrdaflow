"""Tests for the StateRestorer extracted module."""

from __future__ import annotations

from typing import Any

import pytest

from bg_worker_manager import BGWorkerManager
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from state_restorer import StateRestorer


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig()


@pytest.fixture
def state(tmp_path: Any) -> Any:
    from state import StateTracker

    return StateTracker(tmp_path / "state.json")


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def bg_workers(config: HydraFlowConfig, state: Any) -> BGWorkerManager:
    return BGWorkerManager(config, state, bg_loop_registry={})


@pytest.fixture
def restorer(state: Any, bus: EventBus, bg_workers: BGWorkerManager) -> StateRestorer:
    return StateRestorer(state, bus, bg_workers)


class TestRestoreAll:
    """Tests for restore_all orchestration."""

    def test_restores_worker_intervals(
        self, restorer: StateRestorer, state: Any
    ) -> None:
        state.set_worker_intervals({"memory_sync": 120})
        recovered: set[int] = set()
        impl: set[int] = set()
        review: set[int] = set()
        hitl: set[int] = set()
        restorer.restore_all(recovered, impl, review, hitl)
        assert restorer._bg_workers.worker_intervals.get("memory_sync") == 120

    def test_restores_crash_recovered_issues(
        self, restorer: StateRestorer, state: Any
    ) -> None:
        state.set_active_issue_numbers([10, 20])
        recovered: set[int] = set()
        impl: set[int] = set()
        restorer.restore_all(recovered, impl, set(), set())
        assert 10 in recovered
        assert 20 in recovered
        assert 10 in impl
        assert 20 in impl

    def test_restores_interrupted_issues(
        self, restorer: StateRestorer, state: Any
    ) -> None:
        state.set_active_issue_numbers([10])
        state.set_interrupted_issues({10: "implement"})
        recovered: set[int] = set()
        impl: set[int] = set()
        restorer.restore_all(recovered, impl, set(), set())
        # Interrupted issues should be removed from recovery sets
        assert 10 not in recovered
        assert 10 not in impl

    def test_restores_disabled_workers(
        self,
        restorer: StateRestorer,
        state: Any,
        bg_workers: BGWorkerManager,
    ) -> None:
        state.set_disabled_workers({"memory_sync"})
        restorer.restore_all(set(), set(), set(), set())
        assert bg_workers.is_enabled("memory_sync") is False

    def test_restores_bg_worker_states(
        self,
        restorer: StateRestorer,
        state: Any,
        bg_workers: BGWorkerManager,
    ) -> None:
        state.set_bg_worker_state(
            "metrics",
            {
                "name": "metrics",
                "status": "ok",
                "last_run": "2026-01-01T00:00:00Z",
                "details": {},
            },
        )
        restorer.restore_all(set(), set(), set(), set())
        assert "metrics" in bg_workers.worker_states


class TestPruneStaleDisabledWorkers:
    """Tests for prune_stale_disabled_workers."""

    def test_prunes_stale(
        self,
        restorer: StateRestorer,
        state: Any,
        bg_workers: BGWorkerManager,
    ) -> None:
        bg_workers.set_enabled("old_worker", False)
        bg_workers.set_enabled("memory_sync", False)
        known = {"memory_sync", "metrics"}
        restorer.prune_stale_disabled_workers(known)
        # old_worker was pruned (defaults to True again)
        assert bg_workers.is_enabled("old_worker") is True
        # memory_sync stays disabled (it's in known)
        assert bg_workers.is_enabled("memory_sync") is False

    def test_noop_when_no_stale(self, restorer: StateRestorer, state: Any) -> None:
        restorer.prune_stale_disabled_workers({"a", "b"})
        # No error, no crash

    def test_noop_when_no_known(self, restorer: StateRestorer) -> None:
        restorer.prune_stale_disabled_workers(set())


class TestBackfillFromEvents:
    """Tests for _backfill_bg_worker_states_from_events."""

    @pytest.mark.asyncio
    async def test_backfills_from_event_history(
        self,
        restorer: StateRestorer,
        bus: EventBus,
        bg_workers: BGWorkerManager,
    ) -> None:
        await bus.publish(
            HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                data={
                    "worker": "memory_sync",
                    "status": "ok",
                    "last_run": "2026-02-25T09:00:00Z",
                    "details": {"count": 4},
                },
            )
        )
        count = restorer._backfill_bg_worker_states_from_events()
        assert count == 1
        assert "memory_sync" in bg_workers.worker_states
        assert bg_workers.worker_states["memory_sync"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_skips_already_existing(
        self,
        restorer: StateRestorer,
        bus: EventBus,
        bg_workers: BGWorkerManager,
    ) -> None:
        bg_workers.update_status("memory_sync", "running")
        await bus.publish(
            HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                data={"worker": "memory_sync", "status": "ok"},
            )
        )
        count = restorer._backfill_bg_worker_states_from_events()
        assert count == 0
        # Original status preserved
        assert bg_workers.worker_states["memory_sync"]["status"] == "running"

    def test_returns_zero_on_empty_history(self, restorer: StateRestorer) -> None:
        assert restorer._backfill_bg_worker_states_from_events() == 0
