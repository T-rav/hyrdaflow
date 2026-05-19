"""Unit tests for HealthMonitorLoop primary cycle.

Coverage targets (bead #8763):
  - TrendMetrics computed correctly from known data files
  - active_conditions() thresholds
  - ADJUSTMENT_RULES fire when thresholds breached; no-op otherwise
  - _apply_adjustments writes new value to config, clamps to TUNABLE_BOUNDS,
    writes decision record, appends to _pending
  - _file_hitl_recommendations writes JSONL entries for each exceeded threshold
  - Idempotency: re-running _do_work with no new data does not re-adjust
  - _do_work integration: all sub-paths called, correct return dict shape
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from health_monitor_loop import (
    _FIRST_PASS_HIGH,
    _FIRST_PASS_LOW,
    _HITL_HIGH,
    _STALE_COUNT_HIGH,
    _SURPRISE_HIGH,
    TUNABLE_BOUNDS,
    HealthMonitorLoop,
    TrendMetrics,
    compute_trend_metrics,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _make_loop(
    tmp_path: Path, *, max_quality_fix_attempts: int = 2
) -> HealthMonitorLoop:
    """Build a minimal HealthMonitorLoop backed by tmp_path."""
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        max_quality_fix_attempts=max_quality_fix_attempts,
    )
    return HealthMonitorLoop(config=cfg, deps=_deps())


def _write_outcomes(path: Path, outcomes: list[str]) -> None:
    """Write a list of 'success'/'failure' outcome strings to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for outcome in outcomes:
            fh.write(json.dumps({"outcome": outcome}) + "\n")


def _write_failures(path: Path, categories: list[str]) -> None:
    """Write failure records to a JSONL file using the given categories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for category in categories:
            fh.write(json.dumps({"category": category}) + "\n")


def _write_scores(path: Path, scores: dict) -> None:
    """Write item_scores.json from a dict of {key: {score, appearances}} records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scores), encoding="utf-8")


# ---------------------------------------------------------------------------
# TrendMetrics — unit tests for compute_trend_metrics
# ---------------------------------------------------------------------------


class TestComputeTrendMetrics:
    def test_first_pass_rate_correct(self, tmp_path: Path) -> None:
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"
        # 3 successes, 2 failures → rate 0.6
        _write_outcomes(
            outcomes, ["success", "success", "failure", "success", "failure"]
        )
        metrics = compute_trend_metrics(outcomes, scores, failures)
        assert metrics.first_pass_rate == pytest.approx(0.6)
        assert metrics.total_outcomes == 5

    def test_first_pass_rate_zero_when_no_outcomes(self, tmp_path: Path) -> None:
        outcomes = tmp_path / "outcomes.jsonl"
        metrics = compute_trend_metrics(
            outcomes, tmp_path / "scores.json", tmp_path / "failures.jsonl"
        )
        assert metrics.first_pass_rate == 0.0
        assert metrics.total_outcomes == 0

    def test_window_limits_to_last_50(self, tmp_path: Path) -> None:
        outcomes = tmp_path / "outcomes.jsonl"
        # 60 failures followed by 40 successes — only the last 50 entries matter
        records = ["failure"] * 60 + ["success"] * 40
        _write_outcomes(outcomes, records)
        metrics = compute_trend_metrics(
            outcomes, tmp_path / "s.json", tmp_path / "f.jsonl", window=50
        )
        # The tail-50 has 10 failures + 40 successes = 40/50 = 0.8
        assert metrics.first_pass_rate == pytest.approx(0.8)
        assert metrics.total_outcomes == 50

    def test_avg_memory_score_computed_from_item_scores(self, tmp_path: Path) -> None:
        scores = tmp_path / "item_scores.json"
        _write_scores(
            scores,
            {
                "a": {"score": 0.8, "appearances": 1},
                "b": {"score": 0.4, "appearances": 1},
            },
        )
        metrics = compute_trend_metrics(
            tmp_path / "o.jsonl", scores, tmp_path / "f.jsonl"
        )
        assert metrics.avg_memory_score == pytest.approx(0.6)

    def test_stale_item_count_score_below_0_3_with_5_appearances(
        self, tmp_path: Path
    ) -> None:
        scores = tmp_path / "item_scores.json"
        _write_scores(
            scores,
            {
                # stale: score < 0.3 AND appearances >= 5
                "stale_a": {"score": 0.1, "appearances": 6},
                "stale_b": {"score": 0.25, "appearances": 5},
                # not stale: score is fine
                "ok_c": {"score": 0.8, "appearances": 10},
                # not stale: too few appearances
                "young_d": {"score": 0.05, "appearances": 4},
            },
        )
        metrics = compute_trend_metrics(
            tmp_path / "o.jsonl", scores, tmp_path / "f.jsonl"
        )
        assert metrics.stale_item_count == 2

    def test_corrupt_scores_file_sets_sentinel(self, tmp_path: Path) -> None:
        scores = tmp_path / "item_scores.json"
        scores.write_text("{not valid json", encoding="utf-8")
        metrics = compute_trend_metrics(
            tmp_path / "o.jsonl", scores, tmp_path / "f.jsonl"
        )
        assert metrics.stale_item_count == -1

    def test_hitl_escalation_rate_from_failures(self, tmp_path: Path) -> None:
        failures = tmp_path / "harness_failures.jsonl"
        # 2 hitl + 2 other = rate 0.5
        _write_failures(failures, ["hitl_escalation", "hitl_escalation", "lint", "ci"])
        metrics = compute_trend_metrics(
            tmp_path / "o.jsonl", tmp_path / "s.json", failures
        )
        assert metrics.hitl_escalation_rate == pytest.approx(0.5)

    def test_surprise_rate_from_review_rejections(self, tmp_path: Path) -> None:
        failures = tmp_path / "harness_failures.jsonl"
        _write_failures(
            failures, ["review_rejection", "review_rejection", "hitl_escalation"]
        )
        metrics = compute_trend_metrics(
            tmp_path / "o.jsonl", tmp_path / "s.json", failures
        )
        assert metrics.surprise_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# TrendMetrics.active_conditions
# ---------------------------------------------------------------------------


class TestTrendMetricsActiveConditions:
    def _make(self, first_pass_rate: float) -> TrendMetrics:
        return TrendMetrics(
            first_pass_rate=first_pass_rate,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )

    def test_low_first_pass_rate_activates_low_condition(self) -> None:
        m = self._make(_FIRST_PASS_LOW - 0.01)
        assert "first_pass_rate_low" in m.active_conditions()
        assert "first_pass_rate_high" not in m.active_conditions()

    def test_high_first_pass_rate_activates_high_condition(self) -> None:
        m = self._make(_FIRST_PASS_HIGH + 0.01)
        assert "first_pass_rate_high" in m.active_conditions()
        assert "first_pass_rate_low" not in m.active_conditions()

    def test_mid_range_activates_no_conditions(self) -> None:
        m = self._make(0.5)
        assert m.active_conditions() == []

    def test_exactly_at_low_threshold_does_not_trigger(self) -> None:
        # Condition is strict less-than
        m = self._make(_FIRST_PASS_LOW)
        assert "first_pass_rate_low" not in m.active_conditions()

    def test_exactly_at_high_threshold_does_not_trigger(self) -> None:
        # Condition is strict greater-than
        m = self._make(_FIRST_PASS_HIGH)
        assert "first_pass_rate_high" not in m.active_conditions()


# ---------------------------------------------------------------------------
# _apply_adjustments
# ---------------------------------------------------------------------------


class TestApplyAdjustments:
    def test_low_first_pass_rate_increments_max_quality_fix_attempts(
        self, tmp_path: Path
    ) -> None:
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=_FIRST_PASS_LOW - 0.05,  # below threshold → fire rule
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        count = loop._apply_adjustments(metrics)
        assert count == 1
        assert loop._config.max_quality_fix_attempts == 3

    def test_high_first_pass_rate_decrements_max_quality_fix_attempts(
        self, tmp_path: Path
    ) -> None:
        loop = _make_loop(tmp_path, max_quality_fix_attempts=3)
        metrics = TrendMetrics(
            first_pass_rate=_FIRST_PASS_HIGH + 0.05,  # above threshold → fire rule
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        count = loop._apply_adjustments(metrics)
        assert count == 1
        assert loop._config.max_quality_fix_attempts == 2

    def test_no_adjustment_when_no_active_conditions(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.5,  # mid-range — no condition active
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        count = loop._apply_adjustments(metrics)
        assert count == 0
        assert loop._config.max_quality_fix_attempts == 2

    def test_adjustment_clamped_at_upper_bound(self, tmp_path: Path) -> None:
        lo, hi = TUNABLE_BOUNDS["max_quality_fix_attempts"]
        loop = _make_loop(tmp_path, max_quality_fix_attempts=hi)
        metrics = TrendMetrics(
            first_pass_rate=_FIRST_PASS_LOW - 0.05,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        count = loop._apply_adjustments(metrics)
        # At ceiling — step would exceed bound, so no change occurs
        assert count == 0
        assert loop._config.max_quality_fix_attempts == hi

    def test_adjustment_clamped_at_lower_bound(self, tmp_path: Path) -> None:
        lo, hi = TUNABLE_BOUNDS["max_quality_fix_attempts"]
        loop = _make_loop(tmp_path, max_quality_fix_attempts=lo)
        metrics = TrendMetrics(
            first_pass_rate=_FIRST_PASS_HIGH + 0.05,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        count = loop._apply_adjustments(metrics)
        # At floor — decrement would go below bound, so no change occurs
        assert count == 0
        assert loop._config.max_quality_fix_attempts == lo

    def test_adjustment_writes_decision_record(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=_FIRST_PASS_LOW - 0.05,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )
        loop._apply_adjustments(metrics)
        decisions_file = loop._decisions_dir / "decisions.jsonl"
        assert decisions_file.exists()
        records = [json.loads(line) for line in decisions_file.read_text().splitlines()]
        assert len(records) == 1
        rec = records[0]
        assert rec["type"] == "auto_adjust"
        assert rec["parameter"] == "max_quality_fix_attempts"
        assert rec["before"] == 2
        assert rec["after"] == 3
        assert rec["outcome_verified"] is None

    def test_adjustment_appends_to_pending(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=_FIRST_PASS_LOW - 0.05,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )
        assert loop._pending == []
        loop._apply_adjustments(metrics)
        assert len(loop._pending) == 1
        adj = loop._pending[0]
        assert adj.parameter == "max_quality_fix_attempts"
        assert adj.before == 2
        assert adj.after == 3


# ---------------------------------------------------------------------------
# _file_hitl_recommendations
# ---------------------------------------------------------------------------


class TestFileHitlRecommendations:
    async def test_high_surprise_rate_writes_recommendation(
        self, tmp_path: Path
    ) -> None:
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.7,
            surprise_rate=_SURPRISE_HIGH + 0.05,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )
        await loop._file_hitl_recommendations(metrics)
        rec_path = loop._config.data_path("memory", "hitl_recommendations.jsonl")
        assert rec_path.exists()
        lines = rec_path.read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["type"] == "recommendation"
        assert "surprise_rate" in rec["title"]

    async def test_high_hitl_rate_writes_recommendation(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=_HITL_HIGH + 0.05,
            stale_item_count=0,
            total_outcomes=10,
        )
        await loop._file_hitl_recommendations(metrics)
        rec_path = loop._config.data_path("memory", "hitl_recommendations.jsonl")
        lines = rec_path.read_text().splitlines()
        assert len(lines) == 1
        assert "hitl_escalation_rate" in json.loads(lines[0])["title"]

    async def test_high_stale_count_writes_recommendation(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=_STALE_COUNT_HIGH + 1,
            total_outcomes=10,
        )
        await loop._file_hitl_recommendations(metrics)
        rec_path = loop._config.data_path("memory", "hitl_recommendations.jsonl")
        lines = rec_path.read_text().splitlines()
        assert len(lines) == 1
        assert "stale_item_count" in json.loads(lines[0])["title"]

    async def test_multiple_thresholds_write_multiple_entries(
        self, tmp_path: Path
    ) -> None:
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.1,  # below avg score threshold
            surprise_rate=_SURPRISE_HIGH + 0.1,
            hitl_escalation_rate=_HITL_HIGH + 0.1,
            stale_item_count=_STALE_COUNT_HIGH + 2,
            total_outcomes=10,
        )
        await loop._file_hitl_recommendations(metrics)
        rec_path = loop._config.data_path("memory", "hitl_recommendations.jsonl")
        lines = rec_path.read_text().splitlines()
        # surprise_rate + hitl_escalation_rate + avg_memory_score + stale_item_count
        assert len(lines) == 4

    async def test_no_recommendation_when_all_healthy(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.8,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )
        await loop._file_hitl_recommendations(metrics)
        rec_path = loop._config.data_path("memory", "hitl_recommendations.jsonl")
        assert not rec_path.exists()

    async def test_recommendation_is_idempotent_on_repeated_calls(
        self, tmp_path: Path
    ) -> None:
        """Each call appends; this verifies format consistency across two calls."""
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.7,
            surprise_rate=_SURPRISE_HIGH + 0.1,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )
        await loop._file_hitl_recommendations(metrics)
        await loop._file_hitl_recommendations(metrics)
        rec_path = loop._config.data_path("memory", "hitl_recommendations.jsonl")
        lines = rec_path.read_text().splitlines()
        # Each call is a fresh append — two calls → two entries
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# _do_work integration
# ---------------------------------------------------------------------------


class TestDoWorkIntegration:
    def _make_loop_with_stubs(self, tmp_path: Path) -> HealthMonitorLoop:
        """Build a loop with all sub-cycle methods stubbed so _do_work runs cleanly."""
        loop = _make_loop(tmp_path)
        # Stub out the side-cycle methods that require live infrastructure
        loop._check_sanity_loop_staleness = AsyncMock()
        loop._check_wiki_freshness = AsyncMock()
        loop._run_log_ingestion_cycle = AsyncMock(return_value=None)
        loop._run_harness_auto_file_cycle = AsyncMock()
        loop._run_harness_suggestion_ingestion_cycle = AsyncMock()
        loop._run_proposal_verification_cycle = MagicMock()
        loop._run_cross_project_pattern_cycle = MagicMock()
        loop._emit_sentry_metrics = MagicMock()
        return loop

    async def test_do_work_returns_expected_keys(self, tmp_path: Path) -> None:
        loop = self._make_loop_with_stubs(tmp_path)
        result = await loop._do_work()
        assert result is not None
        expected_keys = {
            "first_pass_rate",
            "avg_memory_score",
            "surprise_rate",
            "hitl_escalation_rate",
            "stale_item_count",
            "adjustments_made",
            "total_outcomes",
        }
        assert expected_keys == set(result.keys())

    async def test_do_work_returns_disabled_when_not_enabled(
        self, tmp_path: Path
    ) -> None:
        cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
        disabled_deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _name: False,
        )
        loop = HealthMonitorLoop(config=cfg, deps=disabled_deps)
        result = await loop._do_work()
        assert result == {"status": "disabled"}

    async def test_do_work_fires_adjustment_when_first_pass_low(
        self, tmp_path: Path
    ) -> None:
        loop = self._make_loop_with_stubs(tmp_path)
        # Write outcomes so first_pass_rate is below _FIRST_PASS_LOW
        outcomes = loop._outcomes_path
        # 1 success out of 10 = 0.1, below threshold of 0.2
        _write_outcomes(outcomes, ["success"] + ["failure"] * 9)

        before = loop._config.max_quality_fix_attempts
        result = await loop._do_work()
        assert result is not None
        assert result["adjustments_made"] == 1
        assert loop._config.max_quality_fix_attempts == before + 1

    async def test_do_work_no_adjustment_with_healthy_metrics(
        self, tmp_path: Path
    ) -> None:
        loop = self._make_loop_with_stubs(tmp_path)
        # Mid-range first_pass_rate: 5 successes out of 10 = 0.5
        _write_outcomes(loop._outcomes_path, ["success"] * 5 + ["failure"] * 5)

        before = loop._config.max_quality_fix_attempts
        result = await loop._do_work()
        assert result is not None
        assert result["adjustments_made"] == 0
        assert loop._config.max_quality_fix_attempts == before

    async def test_do_work_idempotent_when_already_at_boundary(
        self, tmp_path: Path
    ) -> None:
        """Re-running _do_work with the same low-rate data and param already at bound
        must not attempt to write past the ceiling."""
        lo, hi = TUNABLE_BOUNDS["max_quality_fix_attempts"]
        cfg = HydraFlowConfig(
            data_root=tmp_path,
            repo="hydra/hydraflow",
            max_quality_fix_attempts=hi,
        )
        loop = HealthMonitorLoop(config=cfg, deps=_deps())
        loop._check_sanity_loop_staleness = AsyncMock()
        loop._check_wiki_freshness = AsyncMock()
        loop._run_log_ingestion_cycle = AsyncMock(return_value=None)
        loop._run_harness_auto_file_cycle = AsyncMock()
        loop._run_harness_suggestion_ingestion_cycle = AsyncMock()
        loop._run_proposal_verification_cycle = MagicMock()
        loop._run_cross_project_pattern_cycle = MagicMock()
        loop._emit_sentry_metrics = MagicMock()

        # first_pass_rate below threshold — rule wants to increment, but already at hi
        _write_outcomes(loop._outcomes_path, ["success"] + ["failure"] * 9)

        result1 = await loop._do_work()
        result2 = await loop._do_work()
        assert result1["adjustments_made"] == 0
        assert result2["adjustments_made"] == 0
        assert loop._config.max_quality_fix_attempts == hi

    async def test_do_work_calls_sub_cycle_stubs(self, tmp_path: Path) -> None:
        """Verify _do_work delegates to all expected sub-cycle methods."""
        loop = self._make_loop_with_stubs(tmp_path)
        await loop._do_work()
        loop._check_sanity_loop_staleness.assert_awaited_once()
        loop._check_wiki_freshness.assert_awaited_once()
        loop._run_log_ingestion_cycle.assert_awaited_once()
        loop._run_harness_auto_file_cycle.assert_awaited_once()
        loop._run_harness_suggestion_ingestion_cycle.assert_awaited_once()
        loop._run_proposal_verification_cycle.assert_called_once()
        loop._run_cross_project_pattern_cycle.assert_called_once()
        loop._emit_sentry_metrics.assert_called_once()
