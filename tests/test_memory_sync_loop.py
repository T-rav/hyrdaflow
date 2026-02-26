"""Tests for the MemorySyncLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from memory_sync_loop import MemorySyncLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    sync_error: Exception | None = None,
) -> tuple[MemorySyncLoop, asyncio.Event]:
    """Build a MemorySyncLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, memory_sync_interval=interval)

    fetcher = MagicMock()
    fetcher.fetch_issues_by_labels = AsyncMock(return_value=[])

    memory_sync = MagicMock()
    if sync_error is not None:
        memory_sync.sync = AsyncMock(side_effect=sync_error)
    else:
        memory_sync.sync = AsyncMock(return_value={"total": 0, "updated": 0})
    memory_sync.publish_sync_event = AsyncMock()

    loop = MemorySyncLoop(
        config=deps.config,
        fetcher=fetcher,
        memory_sync=memory_sync,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
    )
    return loop, deps.stop_event


class TestMemorySyncLoopRun:
    """Tests for MemorySyncLoop.run."""

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_success(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'ok' on success."""
        loop, _stop_event = _make_loop(tmp_path)

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "memory_sync"
        assert args[1] == "ok"

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_event_on_success(
        self, tmp_path: Path
    ) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, _stop_event = _make_loop(tmp_path)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "memory_sync"
        assert data["status"] == "ok"
        assert "last_run" in data

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_error(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'error' on failure."""
        loop, _stop_event = _make_loop(tmp_path, sync_error=RuntimeError("boom"))

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "memory_sync"
        assert args[1] == "error"

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_error_event_on_failure(
        self, tmp_path: Path
    ) -> None:
        """The loop publishes BACKGROUND_WORKER_STATUS and ERROR events on failure."""
        loop, _stop_event = _make_loop(tmp_path, sync_error=RuntimeError("boom"))

        await loop.run()

        history = loop._bus.get_history()
        worker_events = [
            e for e in history if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        error_events = [e for e in history if e.type == EventType.ERROR]

        assert len(worker_events) >= 1
        assert worker_events[0].data["worker"] == "memory_sync"
        assert worker_events[0].data["status"] == "error"
        assert "last_run" in worker_events[0].data

        assert len(error_events) >= 1
        assert error_events[0].data["source"] == "memory_sync"

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips sync when the enabled callback returns False."""
        loop, _stop_event = _make_loop(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_run__continues_on_error(self, tmp_path: Path) -> None:
        """The loop survives exceptions and retries on the next cycle."""
        call_count = 0

        loop, _stop = _make_loop(tmp_path)

        async def fail_once(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")
            return {"total": 0, "updated": 0}

        loop._memory_sync.sync = fail_once  # type: ignore[method-assign]

        await loop.run()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run__fetches_memory_sync_labels_with_high_limit(
        self, tmp_path: Path
    ) -> None:
        loop, _ = _make_loop(tmp_path)

        await loop.run()

        assert loop._fetcher.fetch_issues_by_labels.await_count >= 1
        for call in loop._fetcher.fetch_issues_by_labels.await_args_list:
            args = call.args
            kwargs = call.kwargs
            assert args[0] == loop._config.memory_sync_labels
            assert kwargs["limit"] == 500


class TestMemorySyncLoopInterval:
    """Tests for MemorySyncLoop interval handling."""

    def test_get_interval__uses_config_default(self, tmp_path: Path) -> None:
        """Without an interval callback, uses config.memory_sync_interval."""
        loop, _ = _make_loop(tmp_path, interval=300)
        assert loop._get_interval() == 300

    def test_get_interval__prefers_callback(self, tmp_path: Path) -> None:
        """With an interval callback, uses the callback result."""
        loop, _ = _make_loop(tmp_path, interval=300)
        loop._interval_cb = lambda _name: 99
        assert loop._get_interval() == 99
