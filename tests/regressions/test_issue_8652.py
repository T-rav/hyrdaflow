"""Regression test for issue #8652.

Bug: BGWorkerManager.get_interval() used a hardcoded defaults dict that omitted
most registered loops (including repo_wiki). For any loop not in the dict the
method fell through to poll_interval (30 s).

This caused two problems:
1. TrustFleetSanityLoop computed staleness thresholds using 30 s instead of the
   loop's actual interval (3600 s for repo_wiki), firing false-positive staleness
   alerts within 60 s of every run.
2. The loop itself ran every 30 s instead of every 3600 s.

Fix: query the loop's own _get_default_interval() from the registry before
consulting the non-loop fallback table.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from bg_worker_manager import BGWorkerManager
from config import HydraFlowConfig


def _make_manager(
    config: HydraFlowConfig, state: Any, registry: dict
) -> BGWorkerManager:
    return BGWorkerManager(config, state, registry)


def _fake_loop(interval: int) -> MagicMock:
    loop = MagicMock()
    loop._get_default_interval.return_value = interval
    return loop


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig()


@pytest.fixture
def state(tmp_path: Any) -> Any:
    from state import StateTracker

    return StateTracker(tmp_path / "state.json")


class TestIssue8652:
    """get_interval must use the loop's own default, not poll_interval."""

    def test_repo_wiki_returns_configured_interval_not_poll(
        self, config: HydraFlowConfig, state: Any
    ) -> None:
        """repo_wiki get_interval must return repo_wiki_interval, not poll_interval."""
        registry = {"repo_wiki": _fake_loop(config.repo_wiki_interval)}
        mgr = _make_manager(config, state, registry)

        assert mgr.get_interval("repo_wiki") == config.repo_wiki_interval
        assert mgr.get_interval("repo_wiki") != config.poll_interval

    def test_registered_loop_interval_beats_fallback(
        self, config: HydraFlowConfig, state: Any
    ) -> None:
        """Any loop in the registry returns its own interval, not poll_interval."""
        custom_interval = 7200
        registry = {"some_loop": _fake_loop(custom_interval)}
        mgr = _make_manager(config, state, registry)

        assert mgr.get_interval("some_loop") == custom_interval

    def test_dynamic_override_still_beats_loop_default(
        self, config: HydraFlowConfig, state: Any
    ) -> None:
        """Dynamic set_interval override takes precedence over the loop's default."""
        registry = {"repo_wiki": _fake_loop(config.repo_wiki_interval)}
        mgr = _make_manager(config, state, registry)
        mgr.set_interval("repo_wiki", 999)

        assert mgr.get_interval("repo_wiki") == 999

    def test_non_loop_workers_still_use_fallback_table(
        self, config: HydraFlowConfig, state: Any
    ) -> None:
        """memory_sync and pipeline_poller (not in registry) use their fallback."""
        mgr = _make_manager(config, state, {})

        assert mgr.get_interval("memory_sync") == config.memory_sync_interval
        assert mgr.get_interval("pipeline_poller") == 5
