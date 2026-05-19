"""Unit tests for MergeStateWatcherLoop (advisor-2mf coverage gap).

Closes the unit-test gap identified in the coverage matrix audit.  The
watcher's underlying logic is already covered by ``test_merge_state_watcher.py``;
these tests focus on the loop shell: enabled/disabled path, default interval,
and that ``_do_work`` delegates to and propagates the watcher's stats.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from merge_state_watcher_loop import MergeStateWatcherLoop


def _make_loop(
    tmp_path,
    *,
    enabled: bool = True,
    conflicting_prs: list | None = None,
    rebase_result: bool = True,
    mergeable: bool = True,
) -> MergeStateWatcherLoop:
    """Factory: return a MergeStateWatcherLoop with stubbed dependencies."""
    cfg = HydraFlowConfig(repo="acme/widgets")
    stop = asyncio.Event()
    stop.set()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: enabled or name != "merge_state_watcher",
    )
    prs = AsyncMock()
    prs.list_conflicting_prs = AsyncMock(return_value=conflicting_prs or [])
    prs.update_pr_branch = AsyncMock(return_value=rebase_result)
    prs.get_pr_mergeable = AsyncMock(return_value=mergeable)
    prs.add_pr_labels = AsyncMock()
    return MergeStateWatcherLoop(config=cfg, prs=prs, deps=deps)


class TestMergeStateWatcherLoopShell:
    """Loop shell: enabled/disabled gate, default interval, stats pass-through."""

    async def test_disabled_via_kill_switch_returns_disabled_status(
        self, tmp_path
    ) -> None:
        """When the kill-switch is off the loop short-circuits without calling prs."""
        loop = _make_loop(tmp_path, enabled=False)
        result = await loop._do_work()
        assert result == {"status": "disabled"}

    async def test_default_interval_is_ten_minutes(self, tmp_path) -> None:
        """The default poll cadence is 600 s (10 min)."""
        loop = _make_loop(tmp_path)
        assert loop._get_default_interval() == 600

    async def test_worker_name_is_merge_state_watcher(self, tmp_path) -> None:
        """Worker name must match the constant used for kill-switch routing."""
        loop = _make_loop(tmp_path)
        assert loop._worker_name == "merge_state_watcher"

    async def test_no_conflicting_prs_returns_zero_stats(self, tmp_path) -> None:
        """Empty conflict list propagates as all-zero stats dict."""
        loop = _make_loop(tmp_path, conflicting_prs=[])
        result = await loop._do_work()
        assert result is not None
        assert result["checked"] == 0
        assert result["rebased"] == 0
        assert result["escalated"] == 0
        assert result["skipped"] == 0

    async def test_one_rebased_pr_reflected_in_stats(self, tmp_path) -> None:
        """One conflicting PR that rebases cleanly: checked=1, rebased=1."""
        from merge_state_watcher import ConflictingPR  # noqa: PLC0415

        pr = ConflictingPR(number=42, branch="feat/x", labels=[])
        loop = _make_loop(
            tmp_path,
            conflicting_prs=[pr],
            rebase_result=True,
            mergeable=True,
        )
        result = await loop._do_work()
        assert result is not None
        assert result["checked"] == 1
        assert result["rebased"] == 1
        assert result["escalated"] == 0

    async def test_unresolvable_conflict_escalated(self, tmp_path) -> None:
        """PR that cannot be rebased is escalated (HITL label applied)."""
        from merge_state_watcher import ConflictingPR  # noqa: PLC0415

        pr = ConflictingPR(number=99, branch="feat/y", labels=[])
        loop = _make_loop(
            tmp_path,
            conflicting_prs=[pr],
            rebase_result=False,
            mergeable=False,
        )
        result = await loop._do_work()
        assert result is not None
        assert result["escalated"] == 1
        assert result["rebased"] == 0
