"""Tests for EpicMonitorLoop background worker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import make_bg_loop_deps


def _make_loop(tmp_path: Path, *, enabled: bool = True, interval: int = 60):
    """Build an EpicMonitorLoop with mock EpicManager."""
    from epic_monitor_loop import EpicMonitorLoop

    deps = make_bg_loop_deps(tmp_path, enabled=enabled, epic_monitor_interval=interval)

    epic_manager = MagicMock()
    epic_manager.check_stale_epics = AsyncMock(return_value=[])
    epic_manager.get_all_progress = MagicMock(return_value=[])

    loop = EpicMonitorLoop(
        config=deps.config,
        epic_manager=epic_manager,
        event_bus=deps.bus,
        stop_event=deps.stop_event,
        status_cb=deps.status_cb,
        enabled_cb=deps.enabled_cb,
        sleep_fn=deps.sleep_fn,
    )
    return loop, deps.stop_event, epic_manager


class TestEpicMonitorLoop:
    @pytest.mark.asyncio
    async def test_do_work_calls_manager(self, tmp_path: Path) -> None:
        loop, stop, mgr = _make_loop(tmp_path)
        await loop.run()

        mgr.check_stale_epics.assert_called()
        mgr.get_all_progress.assert_called()

    @pytest.mark.asyncio
    async def test_returns_stale_count(self, tmp_path: Path) -> None:
        loop, stop, mgr = _make_loop(tmp_path)
        mgr.check_stale_epics = AsyncMock(return_value=[100, 200])
        mgr.get_all_progress = MagicMock(
            return_value=[MagicMock(), MagicMock(), MagicMock()]
        )

        result = await loop._do_work()
        assert result == {"stale_count": 2, "tracked_epics": 3}

    @pytest.mark.asyncio
    async def test_disabled_skips_work(self, tmp_path: Path) -> None:
        loop, stop, mgr = _make_loop(tmp_path, enabled=False)
        await loop.run()

        mgr.check_stale_epics.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_interval(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path, interval=900)
        assert loop._get_default_interval() == 900

    @pytest.mark.asyncio
    async def test_worker_name(self, tmp_path: Path) -> None:
        loop, _, _ = _make_loop(tmp_path)
        assert loop._worker_name == "epic_monitor"
