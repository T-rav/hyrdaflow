"""Tests for TrustFleetSanityLoop (spec §12.1)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from trust_fleet_sanity_loop import _DAY_SECONDS, TrustFleetSanityLoop


def _deps(stop: asyncio.Event, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_trust_fleet_sanity_attempts.return_value = 0
    state.inc_trust_fleet_sanity_attempts.return_value = 1
    state.get_trust_fleet_sanity_last_run.return_value = None
    state.get_trust_fleet_sanity_last_seen_counts.return_value = {}
    state.get_worker_heartbeats.return_value = {}
    bg_workers = MagicMock()
    bg_workers.worker_enabled = {}
    bg_workers.get_interval.return_value = 600
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    bus = EventBus()
    return cfg, state, bg_workers, pr_manager, dedup, bus


def _loop(env, enabled: bool = True) -> TrustFleetSanityLoop:
    cfg, state, bg_workers, pr, dedup, bus = env
    deps = _deps(asyncio.Event(), enabled=enabled)
    return TrustFleetSanityLoop(
        config=cfg,
        state=state,
        bg_workers=bg_workers,
        pr_manager=pr,
        dedup=dedup,
        event_bus=bus,
        deps=deps,
    )


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    loop = _loop(loop_env)
    assert loop._worker_name == "trust_fleet_sanity"
    assert loop._get_default_interval() == 600


async def test_do_work_noop_when_no_metrics(loop_env) -> None:
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "ok"
    assert stats["anomalies"] == 0
    _, _, _, pr, _, _ = loop_env
    pr.create_issue.assert_not_awaited()


async def test_kill_switch_short_circuits(loop_env) -> None:
    loop = _loop(loop_env, enabled=False)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "disabled"


# ---------------------------------------------------------------------------
# Task 4 — metrics-reader helpers
# ---------------------------------------------------------------------------


def _make_status_event(
    worker: str,
    status: str,
    *,
    ago_s: int,
    filed: int = 0,
    repaired: int = 0,
    failed: int = 0,
) -> HydraFlowEvent:
    ts = datetime.now(UTC) - timedelta(seconds=ago_s)
    return HydraFlowEvent(
        type=EventType.BACKGROUND_WORKER_STATUS,
        timestamp=ts.isoformat(),
        data={
            "worker": worker,
            "status": status,
            "last_run": ts.isoformat(),
            "details": {
                "filed": filed,
                "repaired": repaired,
                "failed": failed,
            },
        },
    )


async def test_collect_window_metrics_tallies_events(loop_env) -> None:
    loop = _loop(loop_env)
    events = [
        # Inside the hourly window (< 3600s ago).
        _make_status_event("rc_budget", "ok", ago_s=600, filed=2),
        # Outside the hourly window but inside the daily window.
        _make_status_event("rc_budget", "ok", ago_s=4000, filed=3),
        _make_status_event("rc_budget", "error", ago_s=5000),
        _make_status_event("wiki_rot_detector", "ok", ago_s=300, repaired=1),
        # Outside daily window — must be excluded entirely.
        _make_status_event("rc_budget", "ok", ago_s=_DAY_SECONDS + 120, filed=99),
    ]

    async def fake_load(since: datetime) -> list[HydraFlowEvent]:
        return [e for e in events if datetime.fromisoformat(e.timestamp) >= since]

    loop._source_bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    rc = metrics["rc_budget"]
    assert rc["ticks_total"] == 3
    assert rc["ticks_errored"] == 1
    assert rc["issues_filed_day"] == 5
    # Only the 600s-ago event falls inside the 1-hour window; the
    # 4000s-ago event is outside it but still counted in the daily tally.
    assert rc["issues_filed_hour"] == 2
    assert metrics["wiki_rot_detector"]["repaired_day"] == 1


async def test_collect_window_metrics_empty_when_bus_has_no_log(loop_env) -> None:
    loop = _loop(loop_env)
    # Vanilla EventBus().load_events_since returns None → helper yields [].
    metrics = await loop._collect_window_metrics()
    # All known workers present but zero-valued.
    for worker in ("rc_budget", "wiki_rot_detector", "corpus_learning"):
        assert worker in metrics
        assert metrics[worker]["ticks_total"] == 0
        assert metrics[worker]["issues_filed_day"] == 0
        assert metrics[worker]["last_seen_iso"] is None


def test_lazy_cost_reader_tolerates_missing_module(loop_env, monkeypatch) -> None:
    import sys

    loop = _loop(loop_env)
    monkeypatch.setitem(sys.modules, "trust_fleet_cost_reader", None)
    reader = loop._load_cost_reader()
    assert reader is None
