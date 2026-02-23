"""Tests for the PRUnstickerLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType
from pr_unsticker_loop import PRUnstickerLoop
from tests.helpers import ConfigFactory


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    unstick_error: Exception | None = None,
) -> tuple[PRUnstickerLoop, asyncio.Event]:
    """Build a PRUnstickerLoop with test-friendly defaults."""
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        pr_unstick_interval=interval,
    )

    pr_unsticker = MagicMock()
    if unstick_error is not None:
        pr_unsticker.unstick = AsyncMock(side_effect=unstick_error)
    else:
        pr_unsticker.unstick = AsyncMock(return_value={"resolved": 0, "skipped": 0})

    prs = MagicMock()
    prs.list_hitl_items = AsyncMock(return_value=[])

    bus = EventBus()
    stop_event = asyncio.Event()

    call_count = 0

    async def instant_sleep(_seconds: int | float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        await asyncio.sleep(0)

    loop = PRUnstickerLoop(
        config=config,
        pr_unsticker=pr_unsticker,
        prs=prs,
        bus=bus,
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _name: enabled,
        sleep_fn=instant_sleep,
    )
    return loop, stop_event


class TestPRUnstickerLoopRun:
    """Tests for PRUnstickerLoop.run."""

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_success(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'ok' on success."""
        loop, _stop_event = _make_loop(tmp_path)

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "pr_unsticker"
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
        assert data["worker"] == "pr_unsticker"
        assert data["status"] == "ok"
        assert "last_run" in data

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_error(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'error' on failure."""
        loop, _stop_event = _make_loop(tmp_path, unstick_error=RuntimeError("conflict"))

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "pr_unsticker"
        assert args[1] == "error"

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_error_event_on_failure(
        self, tmp_path: Path
    ) -> None:
        """The loop publishes BACKGROUND_WORKER_STATUS and ERROR events on failure."""
        loop, _stop_event = _make_loop(tmp_path, unstick_error=RuntimeError("conflict"))

        await loop.run()

        history = loop._bus.get_history()
        worker_events = [
            e for e in history if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        error_events = [e for e in history if e.type == EventType.ERROR]

        assert len(worker_events) >= 1
        assert worker_events[0].data["worker"] == "pr_unsticker"
        assert worker_events[0].data["status"] == "error"
        assert "last_run" in worker_events[0].data

        assert len(error_events) >= 1
        assert error_events[0].data["source"] == "pr_unsticker"

    @pytest.mark.asyncio
    async def test_run__skips_when_disabled(self, tmp_path: Path) -> None:
        """The loop skips unsticking when the enabled callback returns False."""
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
            return {"resolved": 0, "skipped": 0}

        loop._pr_unsticker.unstick = fail_once  # type: ignore[method-assign]

        await loop.run()

        assert call_count >= 2
