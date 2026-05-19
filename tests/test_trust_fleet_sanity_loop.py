"""Tests for TrustFleetSanityLoop (spec §12.1)."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from trust_fleet_sanity_loop import (
    _DAY_SECONDS,
    _parse_iso,
    TrustFleetSanityLoop,
)


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


# ---------------------------------------------------------------------------
# Task 6 — filing + 1-attempt escalation + close-reconcile
# ---------------------------------------------------------------------------


async def test_do_work_files_escalation_on_issues_per_hour_breach(loop_env) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    async def fake_load(since):  # noqa: ARG001
        return [
            _make_status_event("ci_monitor", "ok", ago_s=600, filed=20),
        ]

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    assert pr.create_issue.await_count >= 1
    title = pr.create_issue.await_args.args[0]
    assert "trust-loop anomaly" in title
    assert "ci_monitor" in title
    assert "issues_per_hour" in title
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "trust-loop-anomaly" in labels


async def test_do_work_skips_filing_when_dedup_key_present(loop_env) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    dedup.get.return_value = {"trust_fleet_sanity:issues_per_hour:ci_monitor"}

    async def fake_load(since):  # noqa: ARG001
        return [_make_status_event("ci_monitor", "ok", ago_s=600, filed=20)]

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] == 0
    pr.create_issue.assert_not_awaited()


async def test_do_work_staleness_detector_uses_bg_worker_state(loop_env) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    old = (datetime.now(UTC) - timedelta(seconds=99_999)).isoformat()
    state.get_worker_heartbeats.return_value = {
        "rc_budget": {"status": "ok", "last_run": old, "details": {}},
    }
    bg_workers.worker_enabled = {"rc_budget": True}
    bg_workers.get_interval.return_value = 600

    async def fake_load(since):  # noqa: ARG001
        return []

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    title = pr.create_issue.await_args.args[0]
    assert "rc_budget" in title
    assert "staleness" in title


async def test_do_work_cost_spike_skipped_when_reader_absent(loop_env) -> None:
    """Cost-reader-absent = no breach, no escalation, no crash."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    async def fake_load(since):  # noqa: ARG001
        return []  # no tick events anywhere

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] == 0
    pr.create_issue.assert_not_awaited()


async def test_reconcile_closed_escalations_clears_dedup(loop_env, monkeypatch) -> None:
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    dedup.get.return_value = {
        "trust_fleet_sanity:issues_per_hour:ci_monitor",
        "trust_fleet_sanity:staleness:rc_budget",
    }
    loop = _loop(loop_env)

    class _P:
        returncode = 0

        async def communicate(self):
            # Only the ci_monitor escalation was closed.
            return (
                b'[{"title": "HITL: trust-loop anomaly \xe2\x80\x94 '
                b'ci_monitor issues_per_hour"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "trust_fleet_sanity:issues_per_hour:ci_monitor" not in remaining
    assert "trust_fleet_sanity:staleness:rc_budget" in remaining
    state.clear_trust_fleet_sanity_attempts.assert_called_once_with(
        "issues_per_hour:ci_monitor"
    )


# ---------------------------------------------------------------------------
# Breach paths — repair_ratio, tick_error_ratio, cost_spike
# ---------------------------------------------------------------------------


async def test_do_work_files_escalation_on_repair_ratio_breach(loop_env) -> None:
    """Loop with high failed/repaired ratio -> repair_ratio escalation filed."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    async def fake_load(since):  # noqa: ARG001
        # repaired=1 failed=10 -> ratio 10.0 >= default threshold 2.0
        return [
            _make_status_event("rc_budget", "ok", ago_s=3600, repaired=1, failed=10),
        ]

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    titles = [call.args[0] for call in pr.create_issue.await_args_list]
    assert any("repair_ratio" in t and "rc_budget" in t for t in titles)


async def test_do_work_files_escalation_on_tick_error_ratio_breach(loop_env) -> None:
    """Loop with high errored/total tick ratio -> tick_error_ratio escalation filed."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    async def fake_load(since):  # noqa: ARG001
        # 4 error ticks out of 5 total = 0.8 >= default threshold 0.2
        return [
            _make_status_event("rc_budget", "ok", ago_s=3601),
            _make_status_event("rc_budget", "error", ago_s=3602),
            _make_status_event("rc_budget", "error", ago_s=3603),
            _make_status_event("rc_budget", "error", ago_s=3604),
            _make_status_event("rc_budget", "error", ago_s=3605),
        ]

    bus.load_events_since = fake_load  # type: ignore[method-assign]
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=None)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    titles = [call.args[0] for call in pr.create_issue.await_args_list]
    assert any("tick_error_ratio" in t and "rc_budget" in t for t in titles)


async def test_do_work_files_escalation_on_cost_spike_breach(loop_env) -> None:
    """Today cost is 10x the 30d median -> cost_spike escalation filed."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    async def fake_load(since):  # noqa: ARG001
        return []

    bus.load_events_since = fake_load  # type: ignore[method-assign]

    cost_reader = MagicMock()
    cost_reader.get_loop_cost_today.return_value = 50.0
    cost_reader.get_loop_cost_30d_median.return_value = 5.0  # ratio 10.0 >= 5.0 threshold

    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._load_cost_reader = MagicMock(return_value=cost_reader)
    stats = await loop._do_work()
    assert stats["anomalies"] >= 1
    titles = [call.args[0] for call in pr.create_issue.await_args_list]
    assert any("cost_spike" in t for t in titles)


# ---------------------------------------------------------------------------
# config_disabled path
# ---------------------------------------------------------------------------


async def test_do_work_returns_config_disabled_when_flag_off(loop_env) -> None:
    """trust_fleet_sanity_loop_enabled=False returns config_disabled without scanning."""
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    cfg.trust_fleet_sanity_loop_enabled = False
    loop = _loop(loop_env)
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    stats = await loop._do_work()
    assert stats["status"] == "config_disabled"
    pr.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# set_bg_workers late-binding
# ---------------------------------------------------------------------------


def test_set_bg_workers_replaces_instance(loop_env) -> None:
    """set_bg_workers() stores the injected manager (post-ctor wiring)."""
    loop = _loop(loop_env)
    new_bg = MagicMock()
    loop.set_bg_workers(new_bg)
    assert loop._bg_workers is new_bg


# ---------------------------------------------------------------------------
# _parse_iso edge cases (lines 139, 142-143)
# ---------------------------------------------------------------------------


def test_parse_iso_returns_none_for_empty_string() -> None:
    assert _parse_iso("") is None


def test_parse_iso_returns_none_for_none() -> None:
    assert _parse_iso(None) is None


def test_parse_iso_returns_none_for_invalid_string() -> None:
    assert _parse_iso("not-a-date") is None


def test_parse_iso_parses_valid_iso() -> None:
    result = _parse_iso("2026-01-15T12:00:00+00:00")
    assert result is not None
    assert result.year == 2026


# ---------------------------------------------------------------------------
# _reconcile_closed_escalations error paths
# ---------------------------------------------------------------------------


async def test_reconcile_tolerates_subprocess_exception(loop_env, monkeypatch) -> None:
    """Subprocess raises OSError -> method swallows, dedup untouched."""
    loop = _loop(loop_env)
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    dedup.get.return_value = {"trust_fleet_sanity:issues_per_hour:rc_budget"}

    async def boom(*args, **kwargs):
        raise OSError("no gh binary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    # Must not raise; dedup must not be modified.
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_not_called()


async def test_reconcile_tolerates_nonzero_returncode(loop_env, monkeypatch) -> None:
    """gh exits non-zero -> early return, dedup unchanged."""
    loop = _loop(loop_env)
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    class _P:
        returncode = 1

        async def communicate(self):
            return b"", b"error"

    async def fake_subproc(*a, **k):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_not_called()


async def test_reconcile_tolerates_invalid_json(loop_env, monkeypatch) -> None:
    """gh returns non-JSON stdout -> JSONDecodeError swallowed, dedup unchanged."""
    loop = _loop(loop_env)
    cfg, state, bg_workers, pr, dedup, bus = loop_env

    class _P:
        returncode = 0

        async def communicate(self):
            return b"not valid json{{", b""

    async def fake_subproc(*a, **k):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_not_called()


async def test_reconcile_skips_issues_with_unmatched_title(loop_env, monkeypatch) -> None:
    """Closed issue whose title doesn't match _TITLE_RE -> key NOT cleared."""
    loop = _loop(loop_env)
    cfg, state, bg_workers, pr, dedup, bus = loop_env
    dedup.get.return_value = {"trust_fleet_sanity:staleness:rc_budget"}

    class _P:
        returncode = 0

        async def communicate(self):
            return b'[{"title": "Some unrelated issue title"}]', b""

    async def fake_subproc(*a, **k):
        return _P()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)
    await loop._reconcile_closed_escalations()
    # No regex match -> set_all never called, existing key preserved.
    dedup.set_all.assert_not_called()


# ---------------------------------------------------------------------------
# _load_events_since exception path (lines 511-514)
# ---------------------------------------------------------------------------


async def test_load_events_since_returns_empty_on_exception(loop_env) -> None:
    """EventBus.load_events_since raising a generic error -> [] returned, no crash."""
    loop = _loop(loop_env)

    async def exploding_load(since):
        raise RuntimeError("event store offline")

    loop._source_bus.load_events_since = exploding_load  # type: ignore[method-assign]
    result = await loop._load_events_since(datetime.now(UTC))
    assert result == []


# ---------------------------------------------------------------------------
# _collect_window_metrics edge cases (event-filtering branches)
# ---------------------------------------------------------------------------


async def test_collect_window_metrics_ignores_non_status_events(loop_env) -> None:
    """Events with a type other than BACKGROUND_WORKER_STATUS are ignored."""
    loop = _loop(loop_env)

    non_status = HydraFlowEvent(
        type=EventType.ISSUE_CREATED,
        timestamp=datetime.now(UTC).isoformat(),
        data={"worker": "rc_budget", "status": "ok", "details": {"filed": 50}},
    )

    async def fake_load(since):  # noqa: ARG001
        return [non_status]

    loop._source_bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    assert metrics["rc_budget"]["ticks_total"] == 0


async def test_collect_window_metrics_ignores_event_with_no_worker_field(
    loop_env,
) -> None:
    """Status event missing 'worker' key -> bucket not created, no crash."""
    loop = _loop(loop_env)

    ev = HydraFlowEvent(
        type=EventType.BACKGROUND_WORKER_STATUS,
        timestamp=datetime.now(UTC).isoformat(),
        data={"status": "ok"},  # no "worker" key
    )

    async def fake_load(since):  # noqa: ARG001
        return [ev]

    loop._source_bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    # Known trust workers still exist (zeroed); unnamed event skipped.
    assert metrics["rc_budget"]["ticks_total"] == 0


async def test_collect_window_metrics_ignores_event_with_nondict_data(
    loop_env,
) -> None:
    """Status event whose 'data' attribute is not a dict -> skipped cleanly.

    Uses a plain object to bypass Pydantic validation and exercise the
    ``if not isinstance(data, dict): continue`` guard in the metrics loop.
    """
    loop = _loop(loop_env)

    class _FakeEvent:
        type = EventType.BACKGROUND_WORKER_STATUS
        timestamp = datetime.now(UTC).isoformat()
        data = "not-a-dict"  # triggers the isinstance guard

    async def fake_load(since):  # noqa: ARG001
        return [_FakeEvent()]

    loop._source_bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    assert metrics["rc_budget"]["ticks_total"] == 0


async def test_collect_window_metrics_ignores_event_outside_day_window(
    loop_env,
) -> None:
    """Status event older than 24h -> not counted even if type matches."""
    loop = _loop(loop_env)

    old_event = _make_status_event("rc_budget", "ok", ago_s=_DAY_SECONDS + 600, filed=99)

    async def fake_load(since):  # noqa: ARG001
        return [old_event]

    loop._source_bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    assert metrics["rc_budget"]["ticks_total"] == 0
    assert metrics["rc_budget"]["issues_filed_day"] == 0


async def test_collect_window_metrics_handles_nondict_details(loop_env) -> None:
    """Status event with details=<string> (non-dict) -> filed/repaired default to 0."""
    loop = _loop(loop_env)

    ts = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    ev = HydraFlowEvent(
        type=EventType.BACKGROUND_WORKER_STATUS,
        timestamp=ts,
        data={"worker": "rc_budget", "status": "ok", "details": "bad_string_details"},
    )

    async def fake_load(since):  # noqa: ARG001
        return [ev]

    loop._source_bus.load_events_since = fake_load  # type: ignore[method-assign]
    metrics = await loop._collect_window_metrics()
    rc = metrics["rc_budget"]
    assert rc["ticks_total"] == 1
    assert rc["issues_filed_day"] == 0
    assert rc["repaired_day"] == 0


# ---------------------------------------------------------------------------
# _load_cost_reader — cost_reader module is None (lines 532-534)
# ---------------------------------------------------------------------------


def test_load_cost_reader_returns_none_when_module_is_none(
    loop_env, monkeypatch
) -> None:
    """sys.modules['trust_fleet_cost_reader'] = None -> _load_cost_reader returns None."""
    loop = _loop(loop_env)
    monkeypatch.setitem(sys.modules, "trust_fleet_cost_reader", None)
    reader = loop._load_cost_reader()
    assert reader is None


# ---------------------------------------------------------------------------
# _emit_trace paths (lines 425-426, 436-438)
# ---------------------------------------------------------------------------


def test_emit_trace_survives_import_error(loop_env, monkeypatch) -> None:
    """trace_collector ImportError -> _emit_trace returns silently."""
    loop = _loop(loop_env)
    monkeypatch.setitem(sys.modules, "trace_collector", None)
    # Should not raise.
    loop._emit_trace(0.0, anomalies=0)


def test_emit_trace_survives_emission_exception(loop_env, monkeypatch) -> None:
    """emit_loop_subprocess_trace raises -> _emit_trace swallows, no crash."""
    loop = _loop(loop_env)

    fake_module = MagicMock()
    fake_module.emit_loop_subprocess_trace.side_effect = RuntimeError("oops")
    monkeypatch.setitem(sys.modules, "trace_collector", fake_module)
    # Should not raise.
    loop._emit_trace(0.0, anomalies=1)
