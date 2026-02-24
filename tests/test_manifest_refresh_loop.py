"""Tests for the ManifestRefreshLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from manifest import ProjectManifestManager
from manifest_refresh_loop import ManifestRefreshLoop
from state import StateTracker
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
) -> tuple[ManifestRefreshLoop, asyncio.Event, ProjectManifestManager, StateTracker]:
    """Build a ManifestRefreshLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path, enabled=enabled, manifest_refresh_interval=interval
    )

    repo_root = deps.config.repo_root
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "pyproject.toml").write_text("[project]")

    manager = ProjectManifestManager(deps.config)
    state = StateTracker(tmp_path / "state.json")

    loop = ManifestRefreshLoop(
        config=deps.config,
        manifest_manager=manager,
        state=state,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
    )
    return loop, deps.stop_event, manager, state


class TestManifestRefreshLoopRun:
    """Tests for ManifestRefreshLoop.run."""

    @pytest.mark.asyncio
    async def test_run__initial_refresh_writes_manifest(self, tmp_path: Path) -> None:
        """The loop performs an initial refresh immediately on startup."""
        loop, stop_event, manager, state = _make_loop(tmp_path)
        # Stop immediately after initial refresh
        stop_event.set()

        await loop.run()

        assert manager.manifest_path.is_file()
        content = manager.manifest_path.read_text()
        assert "python" in content

    @pytest.mark.asyncio
    async def test_run__updates_state_hash(self, tmp_path: Path) -> None:
        """The loop updates the state tracker with the manifest hash."""
        loop, stop_event, _manager, state = _make_loop(tmp_path)
        stop_event.set()

        await loop.run()

        manifest_hash, last_updated = state.get_manifest_state()
        assert manifest_hash != ""
        assert last_updated is not None

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_success(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'ok' on success."""
        loop, stop_event, _manager, _state = _make_loop(tmp_path)
        stop_event.set()

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args
        assert args[0][0] == "manifest_refresh"
        assert args[0][1] == "ok"
        assert "hash" in args[0][2]
        assert "length" in args[0][2]

    @pytest.mark.asyncio
    async def test_run__continues_on_error(self, tmp_path: Path) -> None:
        """The loop survives exceptions in _do_refresh and retries."""
        loop, stop_event, manager, _state = _make_loop(tmp_path)

        call_count = 0
        original_refresh = manager.refresh

        def failing_then_ok() -> tuple[str, str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("disk full")
            return original_refresh()

        manager.refresh = failing_then_ok  # type: ignore[method-assign]

        await loop.run()

        # Should have been called at least twice (initial + retry after error)
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_event_on_success(
        self, tmp_path: Path
    ) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, stop_event, _manager, _state = _make_loop(tmp_path)
        stop_event.set()

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "manifest_refresh"
        assert data["status"] == "ok"
        assert "last_run" in data
        assert "hash" in data["details"]

    @pytest.mark.asyncio
    async def test_run__publishes_error_event_on_failure(self, tmp_path: Path) -> None:
        """The loop publishes an ERROR event when refresh fails."""
        loop, stop_event, manager, _state = _make_loop(tmp_path)
        stop_event.set()

        manager.refresh = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("broken")
        )

        await loop.run()

        error_events = [e for e in loop._bus.get_history() if e.type == EventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].data["source"] == "manifest_refresh"

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_error_event_on_failure(
        self, tmp_path: Path
    ) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS error event on failure."""
        loop, stop_event, manager, _state = _make_loop(tmp_path)
        stop_event.set()

        manager.refresh = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("broken")
        )

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "manifest_refresh"
        assert data["status"] == "error"
        assert "last_run" in data

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips refresh when the enabled callback returns False."""
        loop, stop_event, manager, _state = _make_loop(tmp_path, enabled=False)

        # Override to verify refresh is only called once (initial, before
        # the enabled check in the loop body)
        refresh_count = 0
        original_refresh = manager.refresh

        def counting_refresh() -> tuple[str, str]:
            nonlocal refresh_count
            refresh_count += 1
            return original_refresh()

        manager.refresh = counting_refresh  # type: ignore[method-assign]

        await loop.run()

        # Initial refresh always runs; subsequent cycles skipped
        assert refresh_count == 1


class TestManifestRefreshLoopInterval:
    """Tests for ManifestRefreshLoop interval handling."""

    def test_get_interval__uses_config_default(self, tmp_path: Path) -> None:
        """Without an interval callback, uses config.manifest_refresh_interval."""
        loop, _stop, _mgr, _state = _make_loop(tmp_path, interval=900)
        assert loop._get_interval() == 900

    def test_get_interval__prefers_callback(self, tmp_path: Path) -> None:
        """With an interval callback, uses the callback result."""
        loop, _stop, _mgr, _state = _make_loop(tmp_path, interval=900)
        loop._interval_cb = lambda name: 42
        assert loop._get_interval() == 42
