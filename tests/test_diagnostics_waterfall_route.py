"""Integration test for /api/diagnostics/issue/{issue}/waterfall."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    cfg.repo = "o/r"
    return cfg


@pytest.fixture
def client(config: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(
        return_value=MagicMock(
            number=1234,
            title="Test issue",
            labels=["hydraflow-ready"],
            created_at="2026-04-22T10:00:00+00:00",
        )
    )
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._build_issue_fetcher",
        lambda cfg: fetcher,
    )
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _write_inference(config: MagicMock, **fields: object) -> None:
    d = config.data_root / "metrics" / "prompt"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_trace(
    config: MagicMock, issue: int, phase: str, run_id: int, idx: int, payload: dict
) -> None:
    d = config.data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"subprocess-{idx}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_waterfall_route_full_issue_returns_all_kinds(
    client: TestClient, config: MagicMock
) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="triage",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=50,
        output_tokens=20,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    _write_inference(
        config,
        timestamp="2026-04-22T10:05:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=500,
        output_tokens=200,
        cache_creation_input_tokens=10,
        cache_read_input_tokens=50,
        duration_seconds=30,
        status="success",
    )
    _write_trace(
        config,
        1234,
        "implement",
        1,
        1,
        {
            "issue_number": 1234,
            "phase": "implement",
            "source": "implementer",
            "run_id": 1,
            "subprocess_idx": 1,
            "backend": "claude",
            "started_at": "2026-04-22T10:05:00+00:00",
            "ended_at": "2026-04-22T10:10:00+00:00",
            "success": True,
            "tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_hit_rate": 0.0,
            },
            "tools": {
                "tool_counts": {"Bash": 1},
                "tool_errors": {},
                "total_invocations": 1,
            },
            "tool_calls": [
                {
                    "tool_name": "Bash",
                    "started_at": "2026-04-22T10:06:00+00:00",
                    "duration_ms": 900,
                    "input_summary": "pytest",
                    "succeeded": True,
                    "tool_use_id": "t1",
                },
            ],
            "skill_results": [
                {
                    "skill_name": "diff-sanity",
                    "passed": True,
                    "attempts": 1,
                    "duration_seconds": 2.0,
                    "blocking": True,
                },
            ],
            "inference_count": 0,
            "turn_count": 0,
        },
    )
    resp = client.get("/api/diagnostics/issue/1234/waterfall")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["issue"] == 1234
    assert payload["title"] == "Test issue"
    assert "hydraflow-ready" in payload["labels"]
    kinds = {a["kind"] for p in payload["phases"] for a in p["actions"]}
    assert {"llm", "skill", "subprocess"}.issubset(kinds)
    assert payload["total"]["tokens_in"] >= 550
    assert payload["total"]["tokens_out"] >= 220


def test_waterfall_route_partial_telemetry_returns_missing_phases(
    client: TestClient, config: MagicMock
) -> None:
    _write_inference(
        config,
        timestamp="2026-04-22T10:00:00+00:00",
        source="implementer",
        tool="claude",
        model="claude-sonnet-4-6",
        issue_number=1234,
        input_tokens=1,
        output_tokens=1,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        duration_seconds=1,
        status="success",
    )
    resp = client.get("/api/diagnostics/issue/1234/waterfall")
    assert resp.status_code == 200
    payload = resp.json()
    assert "missing_phases" in payload
    assert "triage" in payload["missing_phases"]
    assert "merge" in payload["missing_phases"]
    assert {p["phase"] for p in payload["phases"]} == {"implement"}


def test_waterfall_route_ghost_issue_still_returns_200(
    config: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Separate client with a fetcher that returns None (deleted/closed issue).
    fetcher = MagicMock()
    fetcher.fetch_issue_by_number = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._build_issue_fetcher",
        lambda cfg: fetcher,
    )
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    resp = TestClient(app).get("/api/diagnostics/issue/9999/waterfall")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["title"] == "(unknown)"
    assert set(payload["missing_phases"]) == {
        "triage",
        "discover",
        "shape",
        "plan",
        "implement",
        "review",
        "merge",
    }
