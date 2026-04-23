"""Tests for FlakeTrackerLoop (spec §4.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from flake_tracker_loop import FlakeTrackerLoop, parse_junit_xml


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_flake_counts.return_value = {}
    state.get_flake_attempts.return_value = 0
    state.inc_flake_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr_manager, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "flake_tracker"
    assert loop._get_default_interval() == 14400


def test_parse_junit_xml_counts_failures_per_test() -> None:
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.scenarios" name="test_alpha" />
    <testcase classname="tests.scenarios" name="test_bravo">
      <failure message="AssertionError"/>
    </testcase>
    <testcase classname="tests.scenarios" name="test_charlie">
      <error message="Timeout"/>
    </testcase>
  </testsuite>
</testsuites>
"""
    results = parse_junit_xml(xml)
    assert results == {
        "tests.scenarios.test_alpha": "pass",
        "tests.scenarios.test_bravo": "fail",
        "tests.scenarios.test_charlie": "fail",
    }


async def test_tally_flakes_counts_mixed_results(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    # Three runs: alpha always passes, bravo fails twice, charlie fails once.
    runs = [
        {"tests.scenarios.test_alpha": "pass", "tests.scenarios.test_bravo": "fail"},
        {"tests.scenarios.test_alpha": "pass", "tests.scenarios.test_bravo": "fail"},
        {"tests.scenarios.test_alpha": "pass", "tests.scenarios.test_charlie": "fail"},
    ]
    counts = loop._tally_flakes(runs)
    assert counts["tests.scenarios.test_bravo"] == 2
    assert counts["tests.scenarios.test_charlie"] == 1
    assert "tests.scenarios.test_alpha" not in counts  # no failures recorded


async def test_do_work_files_issue_when_threshold_hit(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    fake_runs = [
        {"tests.foo.test_flake": "fail"},
        {"tests.foo.test_flake": "pass"},
        {"tests.foo.test_flake": "fail"},
        {"tests.foo.test_flake": "fail"},
    ]

    async def fake_fetch():
        return [{"databaseId": i, "url": f"u{i}"} for i in range(len(fake_runs))]

    async def fake_download(run):
        return fake_runs[run["databaseId"]]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch)
    monkeypatch.setattr(loop, "_download_junit", fake_download)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    assert "test_flake" in title
    labels = pr.create_issue.await_args.args[2]
    assert "flaky-test" in labels


async def test_escalation_fires_after_three_attempts(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_flake_attempts.return_value = 2  # next inc → 3
    state.inc_flake_attempts.return_value = 3
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_fetch():
        return [{"databaseId": 0, "url": "u"}]

    async def fake_dl(_):
        return {
            "tests.scenarios.test_bad": "fail",
            "tests.scenarios.test_other": "pass",
        }

    async def fake_reconcile():
        return None

    # Threshold=1 so a single fail-in-mixed-set triggers.
    cfg.flake_threshold = 1
    monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch)
    monkeypatch.setattr(loop, "_download_junit", fake_dl)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "flaky-test-stuck" in labels


async def test_reconcile_closed_escalations_clears_dedup(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"flake_tracker:tests.foo.test_bar"}
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                b'[{"title": "HITL: flaky test tests.foo.test_bar unresolved after 3 attempts"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "flake_tracker:tests.foo.test_bar" not in remaining
    state.clear_flake_attempts.assert_called_once_with("tests.foo.test_bar")
