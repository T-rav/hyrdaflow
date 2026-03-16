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

    def test_persists_to_state(self, manager: BGWorkerManager) -> None:
        manager.set_interval("x", 99)
        saved = manager._state.get_worker_intervals()
        assert saved["x"] == 99
