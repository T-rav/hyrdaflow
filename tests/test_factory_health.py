"""Tests for the factory_health module."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    issue_number: int = 1,
    pr_number: int = 10,
    timestamp: str | None = None,
    plan_accuracy_pct: float = 80.0,
    quality_fix_rounds: int = 0,
    review_verdict: str = "approve",
    reviewer_fixes_made: bool = False,
    ci_fix_rounds: int = 0,
    duration_seconds: float = 120.0,
) -> dict:
    ts = timestamp or datetime.now(UTC).isoformat()
    return {
        "issue_number": issue_number,
        "pr_number": pr_number,
        "timestamp": ts,
        "plan_accuracy_pct": plan_accuracy_pct,
        "planned_files": [],
        "actual_files": [],
        "unplanned_files": [],
        "missed_files": [],
        "quality_fix_rounds": quality_fix_rounds,
        "review_verdict": review_verdict,
        "reviewer_fixes_made": reviewer_fixes_made,
        "ci_fix_rounds": ci_fix_rounds,
        "duration_seconds": duration_seconds,
    }


def _make_telemetry(
    issue_number: int = 1,
    context_chars_before: int = 5000,
) -> dict:
    return {
        "issue_number": issue_number,
        "context_chars_before": context_chars_before,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# compute_rolling_averages
# ---------------------------------------------------------------------------


class TestComputeRollingAverages:
    """Tests for compute_rolling_averages()."""

    def test_empty_entries(self):
        from factory_health import compute_rolling_averages

        result = compute_rolling_averages([])
        assert result == {}

    def test_single_entry(self):
        from factory_health import compute_rolling_averages

        entries = [_make_entry(plan_accuracy_pct=75.0, quality_fix_rounds=2)]
        result = compute_rolling_averages(entries, window_size=10)
        # With fewer entries than window, should still produce data points
        assert "plan_accuracy_pct" in result
        assert len(result["plan_accuracy_pct"]) == 1
        assert result["plan_accuracy_pct"][0]["value"] == 75.0

    def test_window_averages(self):
        from factory_health import compute_rolling_averages

        entries = [
            _make_entry(issue_number=i, plan_accuracy_pct=float(i * 10))
            for i in range(1, 6)
        ]
        result = compute_rolling_averages(entries, window_size=3)
        # Should produce 3 data points (windows: [1,2,3], [2,3,4], [3,4,5])
        pts = result["plan_accuracy_pct"]
        assert len(pts) == 3
        # First window: avg of 10, 20, 30 = 20
        assert pts[0]["value"] == pytest.approx(20.0)
        # Second window: avg of 20, 30, 40 = 30
        assert pts[1]["value"] == pytest.approx(30.0)
        # Third window: avg of 30, 40, 50 = 40
        assert pts[2]["value"] == pytest.approx(40.0)

    def test_all_metrics_present(self):
        from factory_health import compute_rolling_averages

        entries = [_make_entry() for _ in range(5)]
        result = compute_rolling_averages(entries, window_size=5)
        expected_keys = {
            "plan_accuracy_pct",
            "quality_fix_rounds",
            "ci_fix_rounds",
            "duration_seconds",
            "first_pass_rate",
        }
        assert set(result.keys()) == expected_keys

    def test_first_pass_rate_computation(self):
        from factory_health import compute_rolling_averages

        entries = [
            _make_entry(review_verdict="approve"),
            _make_entry(review_verdict="approve"),
            _make_entry(review_verdict="request-changes"),
        ]
        result = compute_rolling_averages(entries, window_size=3)
        pts = result["first_pass_rate"]
        assert len(pts) == 1
        # 2 out of 3 approved on first pass
        assert pts[0]["value"] == pytest.approx(2.0 / 3.0, rel=1e-3)


# ---------------------------------------------------------------------------
# compute_cohorts
# ---------------------------------------------------------------------------


class TestComputeCohorts:
    """Tests for compute_cohorts()."""

    def test_empty_inputs(self):
        from factory_health import compute_cohorts

        result = compute_cohorts([], [])
        assert result["memory_available"]["count"] == 0
        assert result["memory_unavailable"]["count"] == 0

    def test_splits_by_memory_availability(self):
        from factory_health import compute_cohorts

        retro = [
            _make_entry(issue_number=1, plan_accuracy_pct=90.0),
            _make_entry(issue_number=2, plan_accuracy_pct=60.0),
            _make_entry(issue_number=3, plan_accuracy_pct=70.0),
        ]
        telemetry = [
            _make_telemetry(issue_number=1, context_chars_before=5000),
            _make_telemetry(issue_number=2, context_chars_before=0),
            _make_telemetry(issue_number=3, context_chars_before=3000),
        ]
        result = compute_cohorts(retro, telemetry)
        assert result["memory_available"]["count"] == 2
        assert result["memory_unavailable"]["count"] == 1
        # Memory-available cohort: issues 1,3 → avg accuracy (90+70)/2 = 80
        assert result["memory_available"]["plan_accuracy_pct"] == pytest.approx(80.0)
        # Memory-unavailable: issue 2 → accuracy 60
        assert result["memory_unavailable"]["plan_accuracy_pct"] == pytest.approx(60.0)

    def test_no_matching_telemetry(self):
        from factory_health import compute_cohorts

        retro = [_make_entry(issue_number=1)]
        telemetry = [_make_telemetry(issue_number=99)]
        result = compute_cohorts(retro, telemetry)
        # Issue 1 has no telemetry match → treated as memory_unavailable
        assert result["memory_unavailable"]["count"] == 1
        assert result["memory_available"]["count"] == 0


# ---------------------------------------------------------------------------
# detect_regressions
# ---------------------------------------------------------------------------


class TestDetectRegressions:
    """Tests for detect_regressions()."""

    def test_empty_entries(self):
        from factory_health import detect_regressions

        result = detect_regressions([])
        assert result == []

    def test_insufficient_entries(self):
        from factory_health import detect_regressions

        entries = [_make_entry() for _ in range(3)]
        result = detect_regressions(entries, baseline_window=20, recent_window=5)
        assert result == []

    def test_no_regression_stable_data(self):
        from factory_health import detect_regressions

        entries = [_make_entry(plan_accuracy_pct=80.0) for _ in range(25)]
        result = detect_regressions(entries, baseline_window=20, recent_window=5)
        assert result == []

    def test_detects_accuracy_drop(self):
        from factory_health import detect_regressions

        # 20 entries with high accuracy (slight variation), 5 with very low
        baseline = [_make_entry(plan_accuracy_pct=88.0 + i % 5) for i in range(20)]
        recent = [_make_entry(plan_accuracy_pct=10.0) for _ in range(5)]
        entries = baseline + recent
        result = detect_regressions(entries, baseline_window=20, recent_window=5)
        metric_names = [r["metric"] for r in result]
        assert "plan_accuracy_pct" in metric_names

    def test_detects_fix_rounds_increase(self):
        from factory_health import detect_regressions

        baseline = [_make_entry(quality_fix_rounds=i % 2) for i in range(20)]
        recent = [_make_entry(quality_fix_rounds=5) for _ in range(5)]
        entries = baseline + recent
        result = detect_regressions(entries, baseline_window=20, recent_window=5)
        metric_names = [r["metric"] for r in result]
        assert "quality_fix_rounds" in metric_names

    def test_detects_ci_fix_rounds_regression(self):
        from factory_health import detect_regressions

        baseline = [_make_entry(ci_fix_rounds=i % 2) for i in range(20)]
        recent = [_make_entry(ci_fix_rounds=5) for _ in range(5)]
        entries = baseline + recent
        result = detect_regressions(entries, baseline_window=20, recent_window=5)
        metric_names = [r["metric"] for r in result]
        assert "ci_fix_rounds" in metric_names

    def test_zero_stddev_no_false_positive(self):
        from factory_health import detect_regressions

        # All identical values → stddev = 0 → no regression
        entries = [_make_entry(plan_accuracy_pct=80.0) for _ in range(25)]
        result = detect_regressions(entries, baseline_window=20, recent_window=5)
        assert result == []


# ---------------------------------------------------------------------------
# compute_summary
# ---------------------------------------------------------------------------


class TestComputeSummary:
    """Tests for compute_summary()."""

    def test_empty_entries(self):
        from factory_health import compute_summary

        result = compute_summary([], [])
        assert result["rolling_averages"] == {}
        assert result["regressions"] == []
        assert result["cohorts"]["memory_available"]["count"] == 0

    def test_full_summary_structure(self):
        from factory_health import compute_summary

        entries = [_make_entry(issue_number=i) for i in range(1, 26)]
        telemetry = [_make_telemetry(issue_number=i) for i in range(1, 26)]
        result = compute_summary(entries, telemetry)
        assert "rolling_averages" in result
        assert "cohorts" in result
        assert "regressions" in result
        assert "memory_available" in result["cohorts"]
        assert "memory_unavailable" in result["cohorts"]


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


class TestFactoryHealthRoute:
    """Tests for the /api/factory-health/summary endpoint."""

    def test_returns_summary_structure(self, tmp_path: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from dashboard_routes._factory_health_routes import build_factory_health_router

        config = MagicMock()
        config.data_path = tmp_path.joinpath

        retro_path = tmp_path / "memory" / "retrospectives.jsonl"
        _write_jsonl(retro_path, [_make_entry(issue_number=1)])

        app = FastAPI()
        app.include_router(build_factory_health_router(config))
        client = TestClient(app)

        resp = client.get("/api/factory-health/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "rolling_averages" in body
        assert "cohorts" in body
        assert "regressions" in body

    def test_empty_files(self, tmp_path: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from dashboard_routes._factory_health_routes import build_factory_health_router

        config = MagicMock()
        config.data_path = tmp_path.joinpath

        app = FastAPI()
        app.include_router(build_factory_health_router(config))
        client = TestClient(app)

        resp = client.get("/api/factory-health/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["rolling_averages"] == {}
        assert body["regressions"] == []
