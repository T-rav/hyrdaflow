"""Regression test for issue #8524.

Bug: ``BGWorkerManager.get_interval`` did not have entries for ``stale_issue``
or ``stale_issue_gc``, so both workers fell through to ``poll_interval`` (30 s)
instead of their configured daily/hourly intervals (86400 s / 3600 s).

``TrustFleetSanityLoop`` picks up every worker from heartbeats and checks
staleness using ``bg.get_interval(worker)``.  With the wrong interval, a
``stale_issue`` loop that ran hours ago (correctly, once per day) looks
overdue against a 30 s baseline — triggering a false-positive escalation
that auto-filed issue #8524.

Fix: add ``stale_issue`` and ``stale_issue_gc`` to the defaults dict in
``BGWorkerManager.get_interval``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture()
def manager(tmp_path: Any):
    from bg_worker_manager import BGWorkerManager
    from config import HydraFlowConfig
    from state import StateTracker

    config = HydraFlowConfig()
    state = StateTracker(tmp_path / "state.json")
    return BGWorkerManager(config, state, bg_loop_registry={})


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
