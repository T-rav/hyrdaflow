"""Tests for the BGWorkerManager extracted module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from bg_worker_manager import BGWorkerManager
from config import HydraFlowConfig


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig()


@pytest.fixture
def state(tmp_path: Any) -> Any:
    from state import StateTracker

    return StateTracker(tmp_path / "state.json")


@pytest.fixture
def manager(config: HydraFlowConfig, state: Any) -> BGWorkerManager:
    return BGWorkerManager(config, state, bg_loop_registry={})


class TestUpdateStatus:
    """Tests for update_status."""

    def test_stores_fields(self, manager: BGWorkerManager) -> None:
        manager.update_status("memory_sync", "running")
        s = manager.worker_states["memory_sync"]
        assert s["name"] == "memory_sync"
        assert s["status"] == "running"
        assert "last_run" in s

    def test_with_details(self, manager: BGWorkerManager) -> None:
        manager.update_status("metrics", "ok", details={"synced": 5})
        assert manager.worker_states["metrics"]["details"]["synced"] == 5

    def test_without_details(self, manager: BGWorkerManager) -> None:
        manager.update_status("x", "idle")
        assert manager.worker_states["x"]["details"] == {}

    def test_persists_to_state(self, manager: BGWorkerManager) -> None:
        manager.update_status("memory_sync", "ok")
        persisted = manager._state.get_bg_worker_states()
        assert "memory_sync" in persisted


class TestEnabled:
    """Tests for set_enabled / is_enabled."""

    def test_defaults_true(self, manager: BGWorkerManager) -> None:
        assert manager.is_enabled("memory_sync") is True

    def test_set_false(self, manager: BGWorkerManager) -> None:
        manager.set_enabled("memory_sync", False)
        assert manager.is_enabled("memory_sync") is False

    def test_set_true_after_false(self, manager: BGWorkerManager) -> None:
        manager.set_enabled("x", False)
        manager.set_enabled("x", True)
        assert manager.is_enabled("x") is True

    def test_independent_workers(self, manager: BGWorkerManager) -> None:
        manager.set_enabled("a", False)
        manager.set_enabled("b", True)
        assert manager.is_enabled("a") is False
        assert manager.is_enabled("b") is True

    def test_persists_to_state(self, manager: BGWorkerManager) -> None:
        manager.set_enabled("x", False)
        disabled = manager._state.get_disabled_workers()
        assert "x" in disabled


class TestGetStates:
    """Tests for get_states."""

    def test_empty_by_default(self, manager: BGWorkerManager) -> None:
        assert manager.get_states() == {}

    def test_includes_enabled_flag(self, manager: BGWorkerManager) -> None:
        manager.update_status("memory_sync", "ok")
        manager.set_enabled("memory_sync", False)
        states = manager.get_states()
        assert states["memory_sync"]["enabled"] is False

    def test_returns_copy(self, manager: BGWorkerManager) -> None:
        manager.update_status("x", "ok")
        s1 = manager.get_states()
        s2 = manager.get_states()
        assert s1 == s2
        assert s1 is not s2


class TestTrigger:
    """Tests for trigger."""

    def test_known_worker(self, config: HydraFlowConfig, state: Any) -> None:
        mock_loop = MagicMock()
        mgr = BGWorkerManager(config, state, {"memory_sync": mock_loop})
        assert mgr.trigger("memory_sync") is True
        mock_loop.trigger.assert_called_once()

    def test_unknown_worker(self, manager: BGWorkerManager) -> None:
        assert manager.trigger("nonexistent") is False


class TestInterval:
    """Tests for set_interval / get_interval."""

    def test_override(self, manager: BGWorkerManager) -> None:
        manager.set_interval("memory_sync", 300)
        assert manager.get_interval("memory_sync") == 300

    def test_default_falls_back_to_config(self, manager: BGWorkerManager) -> None:
        interval = manager.get_interval("memory_sync")
        assert interval == manager._config.memory_sync_interval

    def test_unknown_falls_back_to_poll(self, manager: BGWorkerManager) -> None:
        assert manager.get_interval("unknown") == manager._config.poll_interval

    def test_pipeline_poller_default(self, manager: BGWorkerManager) -> None:
        assert manager.get_interval("pipeline_poller") == 5

    def test_persists_to_state(self, manager: BGWorkerManager) -> None:
        manager.set_interval("x", 99)
        saved = manager._state.get_worker_intervals()
        assert saved["x"] == 99


class TestRestoreMethods:
    """Tests for bulk restore methods used by StateRestorer."""

    def test_restore_intervals(self, manager: BGWorkerManager) -> None:
        manager._restore_intervals({"memory_sync": 120, "metrics": 60})
        assert manager.get_interval("memory_sync") == 120
        assert manager.get_interval("metrics") == 60

    def test_restore_enabled_flags(self, manager: BGWorkerManager) -> None:
        manager._restore_enabled_flags({"memory_sync", "metrics"})
        assert manager.is_enabled("memory_sync") is False
        assert manager.is_enabled("metrics") is False
        assert manager.is_enabled("other") is True

    def test_remove_enabled_entry(self, manager: BGWorkerManager) -> None:
        manager.set_enabled("x", False)
        assert manager.is_enabled("x") is False
        manager._remove_enabled_entry("x")
        # Defaults back to True since entry is gone
        assert manager.is_enabled("x") is True

    def test_remove_enabled_entry_missing(self, manager: BGWorkerManager) -> None:
        # Removing a nonexistent entry should be a no-op
        manager._remove_enabled_entry("nonexistent")
        assert manager.is_enabled("nonexistent") is True

    def test_restore_worker_state(self, manager: BGWorkerManager) -> None:
        from models import BackgroundWorkerState

        s = BackgroundWorkerState(
            name="x", status="ok", last_run="2026-01-01T00:00:00Z", details={}
        )
        manager._restore_worker_state("x", s)
        assert manager.worker_states["x"]["status"] == "ok"

    def test_restore_worker_states_bulk(self, manager: BGWorkerManager) -> None:
        from models import BackgroundWorkerState

        states = {
            "a": BackgroundWorkerState(
                name="a", status="ok", last_run=None, details={}
            ),
            "b": BackgroundWorkerState(
                name="b", status="idle", last_run=None, details={}
            ),
        }
        manager._restore_worker_states(states)
        assert "a" in manager.worker_states
        assert "b" in manager.worker_states

    def test_known_worker_state_names(self, manager: BGWorkerManager) -> None:
        assert manager._known_worker_state_names() == set()
        manager.update_status("x", "ok")
        manager.update_status("y", "idle")
        assert manager._known_worker_state_names() == {"x", "y"}
