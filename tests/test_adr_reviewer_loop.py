"""Tests for the ADRReviewerLoop background worker."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_reviewer_loop import ADRReviewerLoop
from events import EventType
from tests.helpers import make_bg_loop_deps


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 86400,
    review_error: Exception | None = None,
) -> tuple[ADRReviewerLoop, asyncio.Event]:
    """Build an ADRReviewerLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        adr_review_interval=interval,
    )

    adr_reviewer = MagicMock()
    if review_error is not None:
        adr_reviewer.review_proposed_adrs = AsyncMock(side_effect=review_error)
    else:
        adr_reviewer.review_proposed_adrs = AsyncMock(
            return_value={"reviewed": 2, "accepted": 1, "rejected": 0, "escalated": 1}
        )

    loop = ADRReviewerLoop(
        config=deps.config,
        adr_reviewer=adr_reviewer,
        deps=deps.loop_deps,
    )
    return loop, deps.stop_event


class TestADRReviewerLoopRun:
    @pytest.mark.asyncio
    async def test_do_work__calls_reviewer_when_enabled(self, tmp_path: Path) -> None:
        """The loop calls review_proposed_adrs when enabled."""
        loop, _stop = _make_loop(tmp_path)

        await loop.run()

        loop._adr_reviewer.review_proposed_adrs.assert_awaited()

    @pytest.mark.asyncio
    async def test_do_work__skips_when_loop_disabled(self, tmp_path: Path) -> None:
        """The loop skips when the enabled callback returns False."""
        loop, _stop = _make_loop(tmp_path, enabled=False)

        await loop.run()

        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_work__returns_stats(self, tmp_path: Path) -> None:
        """The loop returns stats from the reviewer."""
        loop, _stop = _make_loop(tmp_path)

        result = await loop._do_work()

        assert result is not None
        assert result["reviewed"] == 2
        assert result["accepted"] == 1

    def test_get_default_interval(self, tmp_path: Path) -> None:
        """The default interval comes from config."""
        loop, _stop = _make_loop(tmp_path, interval=43200)
        assert loop._get_default_interval() == 43200

    @pytest.mark.asyncio
    async def test_run__publishes_worker_status_event(self, tmp_path: Path) -> None:
        """The loop publishes a BACKGROUND_WORKER_STATUS event on success."""
        loop, _stop = _make_loop(tmp_path)

        await loop.run()

        events = [
            e
            for e in loop._bus.get_history()
            if e.type == EventType.BACKGROUND_WORKER_STATUS
        ]
        assert len(events) >= 1
        data = events[0].data
        assert data["worker"] == "adr_reviewer"
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_run__calls_status_cb_on_error(self, tmp_path: Path) -> None:
        """The loop calls the status callback with 'error' on failure."""
        loop, _stop = _make_loop(tmp_path, review_error=RuntimeError("boom"))

        await loop.run()

        loop._status_cb.assert_called()
        args = loop._status_cb.call_args[0]
        assert args[0] == "adr_reviewer"
        assert args[1] == "error"
