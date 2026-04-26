"""Integration tests for cost-rollup routes on /api/diagnostics/."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    cfg.repo = "o/r"
    return cfg


@pytest.fixture
def client(config) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _write_inference(config, **fields) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config, loop, **fields) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    (d / f"run-{fields['started_at'].replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# /api/diagnostics/cost/rolling-24h
# ---------------------------------------------------------------------------


def test_rolling_24h_returns_total_by_phase_by_loop(
    client, config, monkeypatch
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    _write_inference(
        config,
        timestamp="2026-04-22T11:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_loop_trace(
        config,
        "rc_budget",
        command=["gh"],
        exit_code=0,
        duration_ms=1000,
        started_at="2026-04-22T10:00:00+00:00",
    )
    resp = client.get("/api/diagnostics/cost/rolling-24h")
    assert resp.status_code == 200
    data = resp.json()
    assert data["window_hours"] == 24
    assert "total" in data
    assert "by_phase" in data
    assert "by_loop" in data
    assert any(r["loop"] == "rc_budget" for r in data["by_loop"])


# ---------------------------------------------------------------------------
# /api/diagnostics/cost/top-issues
# ---------------------------------------------------------------------------


def test_top_issues_default_7d_limit_10(client, config) -> None:
    now = datetime.now(UTC)
    ts = now.isoformat()
    for n in range(12):
        _write_inference(
            config,
            timestamp=ts,
            source="implementer",
            tool="claude",
            model="claude-sonnet-4-6",
            issue_number=n + 1,
            input_tokens=n * 100,
            output_tokens=n * 50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            duration_seconds=float(n + 1),
            status="success",
        )
    resp = client.get("/api/diagnostics/cost/top-issues")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) <= 10


def test_top_issues_limit_param(client, config) -> None:
    ts = datetime.now(UTC).isoformat()
    for n in range(5):
        _write_inference(
            config,
            timestamp=ts,
            source="implementer",
            tool="claude",
            model="claude-sonnet-4-6",
            issue_number=n + 1,
            input_tokens=(n + 1) * 100,
            output_tokens=(n + 1) * 50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            duration_seconds=1,
            status="success",
        )
    resp = client.get("/api/diagnostics/cost/top-issues?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_top_issues_rejects_bad_range(client, config) -> None:
    resp = client.get("/api/diagnostics/cost/top-issues?range=99y")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/diagnostics/cost/by-loop
# ---------------------------------------------------------------------------


def test_cost_by_loop_shows_share(client, config) -> None:
    ts = datetime.now(UTC).isoformat()
    _write_loop_trace(
        config,
        "rc_budget",
        command=["gh"],
        exit_code=0,
        duration_ms=1000,
        started_at=ts,
    )
    _write_loop_trace(
        config,
        "corpus_learning",
        command=["gh"],
        exit_code=0,
        duration_ms=500,
        started_at=ts,
    )
    resp = client.get("/api/diagnostics/cost/by-loop")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["loop"] == "rc_budget" for r in rows)
    assert sum(r["share_of_ticks"] for r in rows) == pytest.approx(1.0)


def test_cost_by_loop_rejects_bad_range(client, config) -> None:
    resp = client.get("/api/diagnostics/cost/by-loop?range=99y")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/diagnostics/loops/cost
# ---------------------------------------------------------------------------


def test_loops_cost_per_loop_fields(client, config, monkeypatch) -> None:
    ts = datetime.now(UTC).isoformat()
    _write_loop_trace(
        config,
        "rc_budget",
        command=["gh"],
        exit_code=0,
        duration_ms=1000,
        started_at=ts,
    )

    bus = MagicMock()

    async def _load(since):
        ev = MagicMock()
        ev.type = "background_worker_status"
        ev.timestamp = ts
        ev.data = {
            "worker": "rc_budget",
            "status": "success",
            "last_run": ts,
            "details": {"filed": 1, "closed": 0, "escalated": 0},
        }
        return [ev]

    bus.load_events_since = _load
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._event_bus_for_rollup",
        lambda cfg: bus,
    )
    resp = client.get("/api/diagnostics/loops/cost?range=7d")
    assert resp.status_code == 200
    rows = resp.json()
    row = next(r for r in rows if r["loop"] == "rc_budget")
    for key in (
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "llm_calls",
        "issues_filed",
        "issues_closed",
        "escalations",
        "ticks",
        "tick_cost_avg_usd",
        "wall_clock_seconds",
        "tick_cost_avg_usd_prev_period",
    ):
        assert key in row


def test_loops_cost_accepts_7d_30d_90d(client, config, monkeypatch) -> None:
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._event_bus_for_rollup",
        lambda cfg: None,
    )
    for r in ("7d", "30d", "90d"):
        resp = client.get(f"/api/diagnostics/loops/cost?range={r}")
        assert resp.status_code == 200


def test_loops_cost_rejects_bad_range(client, config, monkeypatch) -> None:
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._event_bus_for_rollup",
        lambda cfg: None,
    )
    resp = client.get("/api/diagnostics/loops/cost?range=99y")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/diagnostics/cost/by-model
# ---------------------------------------------------------------------------


def test_cost_by_model_endpoint_returns_rows_sorted_by_cost(
    client, config, monkeypatch
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    _write_inference(
        config,
        timestamp="2026-04-22T11:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-opus-4-7",
        issue_number=1,
        input_tokens=10_000,
        output_tokens=2_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T11:01:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-haiku-4-5-20251001",
        issue_number=1,
        input_tokens=10_000,
        output_tokens=2_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )

    resp = client.get("/api/diagnostics/cost/by-model?range=24h")

    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert [r["model"] for r in rows][0] == "claude-opus-4-7"  # opus first (more $)
    for row in rows:
        for k in ("cost_usd", "calls", "input_tokens", "output_tokens"):
            assert k in row


def test_cost_by_model_endpoint_rejects_invalid_range(client) -> None:
    resp = client.get("/api/diagnostics/cost/by-model?range=99y")
    assert resp.status_code == 400


def test_cost_by_model_endpoint_returns_empty_list_for_no_data(
    client, monkeypatch
) -> None:
    now = datetime(2026, 4, 22, 12, tzinfo=UTC)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: now)
    resp = client.get("/api/diagnostics/cost/by-model?range=24h")
    assert resp.status_code == 200
    assert resp.json() == []
