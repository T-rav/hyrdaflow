"""Tests for /api/trust/fleet (spec §12.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._trust_routes import (
    _parse_range_for_trust,
    _read_fleet,
    build_trust_router,
)


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108
    cfg.repo = "o/r"
    return cfg


def _mk_event(
    worker, status, filed=0, closed=0, escalated=0, ts=None, repaired=0, failed=0
):
    ev = MagicMock()
    ev.type = "background_worker_status"
    ev.timestamp = ts or "2026-04-22T10:00:00+00:00"
    ev.data = {
        "worker": worker,
        "status": status,
        "last_run": ev.timestamp,
        "details": {
            "filed": filed,
            "closed": closed,
            "escalated": escalated,
            "repaired": repaired,
            "failed": failed,
        },
    }
    return ev


# ---------------------------------------------------------------------------
# _parse_range_for_trust
# ---------------------------------------------------------------------------


def test_parse_range_accepts_7d_30d() -> None:
    assert _parse_range_for_trust("7d") == timedelta(days=7)
    assert _parse_range_for_trust("30d") == timedelta(days=30)


def test_parse_range_default_is_7d() -> None:
    assert _parse_range_for_trust(None) == timedelta(days=7)
    assert _parse_range_for_trust("") == timedelta(days=7)


def test_parse_range_rejects_24h_and_unknown() -> None:
    with pytest.raises(ValueError):
        _parse_range_for_trust("24h")  # not allowed per §12.1
    with pytest.raises(ValueError):
        _parse_range_for_trust("15m")


# ---------------------------------------------------------------------------
# _read_fleet
# ---------------------------------------------------------------------------


def test_read_fleet_tallies_background_worker_status(config) -> None:
    bus = MagicMock()

    async def _load(since):
        return [
            _mk_event("rc_budget", "success", filed=1),
            _mk_event("rc_budget", "error"),
            _mk_event("corpus_learning", "success", filed=2, closed=1),
        ]

    bus.load_events_since = _load
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {
        "rc_budget": "2026-04-22T10:05:00+00:00",
        "corpus_learning": "2026-04-22T10:05:00+00:00",
    }
    import asyncio

    result = asyncio.run(
        _read_fleet(
            config,
            event_bus=bus,
            bg_workers=bg,
            state=state,
            range_td=timedelta(days=7),
            anomaly_reader=lambda repo: [],
        )
    )
    assert result["range"] == "7d"
    workers = {r["worker_name"]: r for r in result["loops"]}
    assert workers["rc_budget"]["ticks_total"] == 2
    assert workers["rc_budget"]["ticks_errored"] == 1
    assert workers["rc_budget"]["issues_filed_total"] == 1
    assert workers["corpus_learning"]["issues_closed_total"] == 1
    assert workers["corpus_learning"]["enabled"] is True
    assert workers["rc_budget"]["interval_s"] == 300


def test_read_fleet_30d_reports_range(config) -> None:
    bus = MagicMock()
    bus.load_events_since = AsyncMock(return_value=[])
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    import asyncio

    result = asyncio.run(
        _read_fleet(
            config,
            event_bus=bus,
            bg_workers=bg,
            state=state,
            range_td=timedelta(days=30),
            anomaly_reader=lambda repo: [],
        )
    )
    assert result["range"] == "30d"
    assert result["loops"] == []
    assert result["anomalies_recent"] == []


# ---------------------------------------------------------------------------
# build_trust_router
# ---------------------------------------------------------------------------


def test_fleet_route_default_range_is_7d(config) -> None:
    bus = MagicMock()
    bus.load_events_since = AsyncMock(return_value=[])
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    deps = SimpleNamespace(event_bus=bus, bg_workers=bg, state=state)

    app = FastAPI()
    app.include_router(build_trust_router(config, deps_factory=lambda: deps))
    client = TestClient(app)
    resp = client.get("/api/trust/fleet")
    assert resp.status_code == 200
    assert resp.json()["range"] == "7d"


def test_fleet_route_rejects_24h(config) -> None:
    bus = MagicMock()
    bus.load_events_since = AsyncMock(return_value=[])
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    deps = SimpleNamespace(event_bus=bus, bg_workers=bg, state=state)

    app = FastAPI()
    app.include_router(build_trust_router(config, deps_factory=lambda: deps))
    client = TestClient(app)
    resp = client.get("/api/trust/fleet?range=24h")
    assert resp.status_code == 400


def test_fleet_route_accepts_30d(config) -> None:
    bus = MagicMock()
    bus.load_events_since = AsyncMock(return_value=[])
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    deps = SimpleNamespace(event_bus=bus, bg_workers=bg, state=state)

    app = FastAPI()
    app.include_router(build_trust_router(config, deps_factory=lambda: deps))
    client = TestClient(app)
    resp = client.get("/api/trust/fleet?range=30d")
    assert resp.status_code == 200
    assert resp.json()["range"] == "30d"


def test_fleet_payload_schema_matches_lock(config) -> None:
    """Response keys match the FLEET_ENDPOINT_SCHEMA at trust_fleet_sanity_loop.py:53."""
    bus = MagicMock()

    async def _load(since):
        return [
            _mk_event(
                "rc_budget",
                "success",
                filed=1,
                closed=0,
                escalated=0,
                repaired=2,
                failed=1,
            ),
        ]

    bus.load_events_since = _load
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {
        "rc_budget": "2026-04-22T10:05:00+00:00",
    }
    deps = SimpleNamespace(event_bus=bus, bg_workers=bg, state=state)

    app = FastAPI()
    app.include_router(build_trust_router(config, deps_factory=lambda: deps))
    client = TestClient(app)
    resp = client.get("/api/trust/fleet")
    assert resp.status_code == 200
    payload = resp.json()
    for top_key in ("range", "generated_at", "loops", "anomalies_recent"):
        assert top_key in payload
    assert len(payload["loops"]) == 1
    loop = payload["loops"][0]
    for key in (
        "worker_name",
        "enabled",
        "interval_s",
        "last_tick_at",
        "ticks_total",
        "ticks_errored",
        "issues_filed_total",
        "issues_closed_total",
        "issues_open_escalated",
        "repair_attempts_total",
        "repair_successes_total",
        "repair_failures_total",
        "loop_specific",
    ):
        assert key in loop, f"missing: {key}"
    assert loop["repair_successes_total"] == 2
    assert loop["repair_failures_total"] == 1
    assert loop["repair_attempts_total"] == 3


def test_anomaly_reader_is_cached(config, monkeypatch) -> None:
    """Subsequent calls within 60s reuse the cached anomaly list."""
    calls: list[int] = []

    def _reader(repo):
        calls.append(1)
        return [
            {
                "kind": "repair_ratio",
                "worker": "rc_budget",
                "filed_at": "2026-04-22T09:00:00+00:00",
                "issue_number": 999,
                "details": {},
            }
        ]

    from dashboard_routes import _trust_routes as _mod

    monkeypatch.setattr(_mod, "_build_anomaly_reader", lambda repo: _reader)
    monkeypatch.setattr(_mod, "_ANOMALY_CACHE_TTL", 60)
    _mod._ANOMALY_CACHE.clear()

    bus = MagicMock()
    bus.load_events_since = AsyncMock(return_value=[])
    bg = MagicMock()
    bg.worker_enabled.return_value = True
    bg.get_interval.return_value = 300
    state = MagicMock()
    state.get_worker_heartbeats.return_value = {}
    deps = SimpleNamespace(event_bus=bus, bg_workers=bg, state=state)

    app = FastAPI()
    app.include_router(build_trust_router(config, deps_factory=lambda: deps))
    client = TestClient(app)
    client.get("/api/trust/fleet")
    client.get("/api/trust/fleet")
    assert len(calls) == 1


def test_anomaly_reader_parses_gh_issue_list_titles(config, monkeypatch) -> None:
    """Anomaly reader parses ``HITL: trust-loop anomaly — <worker> <kind>`` titles."""
    from dashboard_routes import _trust_routes as _mod

    now_iso = datetime.now(UTC).isoformat()

    class _Completed:
        def __init__(self, out):
            self.stdout = out

    import json as _json

    def _fake_run(cmd, check, capture_output, text, timeout):  # noqa: FBT001, ARG001
        payload = [
            {
                "number": 501,
                "title": "HITL: trust-loop anomaly — rc_budget repair_ratio",
                "createdAt": now_iso,
            },
            {
                "number": 502,
                "title": "Random other issue",
                "createdAt": now_iso,
            },
        ]
        return _Completed(_json.dumps(payload))

    monkeypatch.setattr(_mod.subprocess, "run", _fake_run)
    reader = _mod._build_anomaly_reader("o/r")
    rows = reader("o/r")
    assert len(rows) == 1
    assert rows[0]["kind"] == "repair_ratio"
    assert rows[0]["worker"] == "rc_budget"
    assert rows[0]["issue_number"] == 501
