"""Regression: /api/diagnostics/loops/cost keeps its existing field set.

Adding model_breakdown is additive — older clients that destructure
specific fields must continue to find them. Locks the row schema.

Timestamps use relative offsets from datetime.now(UTC) so this test is
not sensitive to calendar date. The /loops/cost route calls
datetime.now(UTC) directly (not a _utcnow helper), so we write records
that are ~1 hour old and use range=24h to keep them inside the window.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    cfg.repo = "o/r"
    return cfg


@pytest.fixture
def client(config: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _write_inference(config: MagicMock, **fields: object) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: MagicMock, loop: str, **fields: object) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    started = str(fields["started_at"])
    (d / f"run-{started.replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_loops_cost_row_keeps_pre_breakdown_fields(client: TestClient, config: MagicMock) -> None:
    """All previously-shipped fields still present alongside model_breakdown.

    Uses a timestamp 1 hour in the past so the record falls within the
    default 24h window regardless of the calendar date on which the test
    runs.
    """
    ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    _write_inference(
        config,
        timestamp=ts,
        source="implementer",
        model="claude-sonnet-4-6",
        issue_number=1,
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    _write_loop_trace(
        config,
        "ImplementerLoop",
        started_at=ts,
        duration_ms=60_000,
        command=["x"],
        exit_code=0,
    )

    resp = client.get("/api/diagnostics/loops/cost?range=24h")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "expected at least one loop row"
    row = rows[0]

    pre_breakdown_fields = {
        "loop",
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "llm_calls",
        "issues_filed",
        "issues_closed",
        "escalations",
        "ticks",
        "ticks_errored",
        "tick_cost_avg_usd",
        "wall_clock_seconds",
        "last_tick_at",
        "tick_cost_avg_usd_prev_period",
    }
    missing = pre_breakdown_fields - set(row.keys())
    assert not missing, f"endpoint dropped pre-existing fields: {missing}"
    assert "model_breakdown" in row
