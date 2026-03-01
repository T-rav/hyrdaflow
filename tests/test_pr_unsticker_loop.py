"""Tests for the PRUnstickerLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from models import HITLItem
from pr_unsticker_loop import PRUnstickerLoop
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    unstick_error: Exception | None = None,
) -> tuple[PRUnstickerLoop, asyncio.Event]:
    """Build a PRUnstickerLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, pr_unstick_interval=interval)

    pr_unsticker = MagicMock()
    if unstick_error is not None:
        pr_unsticker.unstick = AsyncMock(side_effect=unstick_error)
    else:
        pr_unsticker.unstick = AsyncMock(return_value={"resolved": 0, "skipped": 0})

    prs = MagicMock()
    prs.list_hitl_items = AsyncMock(return_value=[])

    loop = PRUnstickerLoop(
        config=deps.config,
        pr_unsticker=pr_unsticker,
        prs=prs,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
    )
    return loop, deps.stop_event


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

    @pytest.mark.asyncio
    async def test_run__filters_to_hitl_items_with_active_prs(
        self, tmp_path: Path
    ) -> None:
        """Only HITL issues with an open PR should be handed to unsticker."""
        loop, _stop = _make_loop(tmp_path)
        loop._prs.list_hitl_items = AsyncMock(
            return_value=[
                HITLItem(
                    issue=1,
                    title="Verify: foo",
                    issueUrl="https://github.com/o/r/issues/1",
                    pr=0,
                    prUrl="",
                ),
                HITLItem(
                    issue=2,
                    title="Regular HITL issue",
                    issueUrl="https://github.com/o/r/issues/2",
                    pr=123,
                    prUrl="https://github.com/o/r/pull/123",
                ),
            ]
        )

        await loop.run()

        assert loop._pr_unsticker.unstick.await_count >= 1
        for call in loop._pr_unsticker.unstick.await_args_list:
            passed_items = call.args[0]
            assert [item.issue for item in passed_items] == [2]
