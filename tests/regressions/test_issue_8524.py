"""Regression test for issue #8524.

Bug: ``BGWorkerManager.get_interval`` did not have entries for ``stale_issue``
or ``stale_issue_gc``, so both workers fell through to ``poll_interval`` (30 s)
instead of their configured daily/hourly intervals (86400 s / 3600 s).

``TrustFleetSanityLoop`` picks up every worker from heartbeats and checks
staleness using ``bg.get_interval(worker)``.  With the wrong interval, a
``stale_issue`` loop that ran hours ago (correctly, once per day) looks
overdue against a 30 s baseline — triggering a false-positive escalation
that auto-filed issue #8524.

Fix (PR #8664): query each loop's own ``_get_default_interval()`` from the
loop registry, removing the need for a hardcoded defaults dict entry for every
registered loop. ``stale_issue`` and ``stale_issue_gc`` are registered loops
and now return their real intervals automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))


def _fake_loop(interval: int) -> MagicMock:
    loop = MagicMock()
    loop._get_default_interval.return_value = interval
    return loop


@pytest.fixture()
def manager(tmp_path: Any):
    from bg_worker_manager import BGWorkerManager
    from config import HydraFlowConfig
    from state import StateTracker

    config = HydraFlowConfig()
    state = StateTracker(tmp_path / "state.json")
    registry = {
        "stale_issue": _fake_loop(config.stale_issue_interval),
        "stale_issue_gc": _fake_loop(config.stale_issue_gc_interval),
    }
    return BGWorkerManager(config, state, bg_loop_registry=registry)


class TestStaleIssueIntervalDefaults:
    def test_stale_issue_returns_config_interval_not_poll(self, manager: Any) -> None:
        interval = manager.get_interval("stale_issue")
        assert interval == manager._config.stale_issue_interval
        assert interval != manager._config.poll_interval, (
            "stale_issue fell through to poll_interval — "
            "TrustFleetSanityLoop will fire false staleness alerts"
        )

    def test_stale_issue_gc_returns_config_interval_not_poll(
        self, manager: Any
    ) -> None:
        interval = manager.get_interval("stale_issue_gc")
        assert interval == manager._config.stale_issue_gc_interval
        assert interval != manager._config.poll_interval, (
            "stale_issue_gc fell through to poll_interval — "
            "TrustFleetSanityLoop will fire false staleness alerts"
        )

    def test_stale_issue_interval_is_daily(self, manager: Any) -> None:
        assert manager.get_interval("stale_issue") == 86400

    def test_stale_issue_gc_interval_is_hourly(self, manager: Any) -> None:
        assert manager.get_interval("stale_issue_gc") == 3600
