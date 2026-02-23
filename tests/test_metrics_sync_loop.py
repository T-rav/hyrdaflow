"""Tests for the MetricsSyncLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType
from metrics_sync_loop import MetricsSyncLoop
from tests.helpers import ConfigFactory


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    sync_error: Exception | None = None,
) -> tuple[MetricsSyncLoop, asyncio.Event]:
    """Build a MetricsSyncLoop with test-friendly defaults."""
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        metrics_sync_interval=interval,
    )

    store = MagicMock()
    store.get_queue_stats = MagicMock(return_value={"queued": 0})

    metrics_manager = MagicMock()
    if sync_error is not None:
        metrics_manager.sync = AsyncMock(side_effect=sync_error)
    else:
        metrics_manager.sync = AsyncMock(return_value={"issues_processed": 5})

    bus = EventBus()
    stop_event = asyncio.Event()

    call_count = 0

    async def instant_sleep(_seconds: int | float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        await asyncio.sleep(0)

    loop = MetricsSyncLoop(
        config=config,
        store=store,
        metrics_manager=metrics_manager,
        event_bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: enabled,
        sleep_fn=instant_sleep,
    )
    return loop, stop_event


class TestMetricsSyncLoopRun:
    """Tests for MetricsSyncLoop.run."""

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_success(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'ok' on success."""
        loop, _stop_event = _make_loop(tmp_path)

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "metrics"
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
        assert data["worker"] == "metrics"
        assert data["status"] == "ok"
        assert "last_run" in data

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_error(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'error' on failure."""
        loop, _stop_event = _make_loop(tmp_path, sync_error=RuntimeError("db down"))

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "metrics"
        assert args[1] == "error"

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_error_event_on_failure(
        self, tmp_path: Path
    ) -> None:
        """The loop publishes BACKGROUND_WORKER_STATUS and ERROR events on failure."""
        loop, _stop_event = _make_loop(tmp_path, sync_error=RuntimeError("db down"))

        await loop.run()

        history = loop._bus.get_history()
        worker_events = [
            e for e in history if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        error_events = [e for e in history if e.type == EventType.ERROR]

        assert len(worker_events) >= 1
        assert worker_events[0].data["worker"] == "metrics"
        assert worker_events[0].data["status"] == "error"
        assert "last_run" in worker_events[0].data

        assert len(error_events) >= 1
        assert error_events[0].data["source"] == "metrics"

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
            return {"issues_processed": 5}

        loop._metrics_manager.sync = fail_once

        await loop.run()

        assert call_count >= 2


class TestMetricsSyncLoopInterval:
    """Tests for MetricsSyncLoop interval handling."""

    def test_get_interval__uses_config_default(self, tmp_path: Path) -> None:
        """Without an interval callback, uses config.metrics_sync_interval."""
        loop, _ = _make_loop(tmp_path, interval=120)
        assert loop._get_interval() == 120

    def test_get_interval__prefers_callback(self, tmp_path: Path) -> None:
        """With an interval callback, uses the callback result."""
        loop, _ = _make_loop(tmp_path, interval=120)
        loop._interval_cb = lambda _name: 77
        assert loop._get_interval() == 77
