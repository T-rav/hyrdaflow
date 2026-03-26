"""Tests for the HealthMonitorLoop background worker."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from health_monitor_loop import (
    ADJUSTMENT_RULES,
    TUNABLE_BOUNDS,
    HealthMonitorLoop,
    PendingAdjustment,
    TrendMetrics,
    _load_decisions,
    _next_decision_id,
    _update_decision,
    _write_decision,
    compute_trend_metrics,
)
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    interval: int = 60,
    prs: Any | None = None,
    max_quality_fix_attempts: int = 2,
    agent_timeout: int = 300,
) -> HealthMonitorLoop:
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        health_monitor_interval=interval,
        max_quality_fix_attempts=max_quality_fix_attempts,
        agent_timeout=agent_timeout,
    )
    loop = HealthMonitorLoop(
        config=deps.config,
        deps=deps.loop_deps,
        prs=prs,
        verification_window=5,  # small for tests
    )
    return loop


def _write_outcomes(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_scores(path: Path, scores: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scores, indent=2), encoding="utf-8")


def _write_failures(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# compute_trend_metrics
# ---------------------------------------------------------------------------


class TestComputeTrendMetrics:
    """Tests for compute_trend_metrics function."""

    def test_empty_files_returns_zero_metrics(self, tmp_path: Path) -> None:
        """With no data files, all metrics are zero/empty."""
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.first_pass_rate == 0.0
        assert metrics.avg_memory_score == 0.0
        assert metrics.surprise_rate == 0.0
        assert metrics.hitl_escalation_rate == 0.0
        assert metrics.stale_item_count == 0
        assert metrics.total_outcomes == 0

    def test_first_pass_rate__all_success(self, tmp_path: Path) -> None:
        """100% success rate."""
        outcomes = [{"outcome": "success"} for _ in range(10)]
        _write_outcomes(tmp_path / "outcomes.jsonl", outcomes)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.first_pass_rate == 1.0
        assert metrics.total_outcomes == 10

    def test_first_pass_rate__mixed(self, tmp_path: Path) -> None:
        """Mixed outcomes compute correct rate."""
        outcomes = [{"outcome": "success"}] * 8 + [{"outcome": "failure"}] * 2
        _write_outcomes(tmp_path / "outcomes.jsonl", outcomes)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.first_pass_rate == pytest.approx(0.8)

    def test_first_pass_rate__windowed(self, tmp_path: Path) -> None:
        """Only the last 50 outcomes are considered."""
        outcomes = [{"outcome": "failure"}] * 60 + [{"outcome": "success"}] * 50
        _write_outcomes(tmp_path / "outcomes.jsonl", outcomes)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
            window=50,
        )
        assert metrics.first_pass_rate == 1.0
        assert metrics.total_outcomes == 50

    def test_avg_memory_score(self, tmp_path: Path) -> None:
        """Average of item scores is computed correctly."""
        scores = {
            "1": {"score": 0.8, "appearances": 3},
            "2": {"score": 0.6, "appearances": 1},
            "3": {"score": 0.4, "appearances": 2},
        }
        _write_scores(tmp_path / "item_scores.json", scores)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.avg_memory_score == pytest.approx((0.8 + 0.6 + 0.4) / 3)

    def test_stale_item_count(self, tmp_path: Path) -> None:
        """Items with score < 0.3 and appearances >= 5 count as stale."""
        scores = {
            "1": {"score": 0.25, "appearances": 5},  # stale
            "2": {"score": 0.25, "appearances": 4},  # not stale (appearances < 5)
            "3": {"score": 0.31, "appearances": 10},  # not stale (score >= 0.3)
            "4": {"score": 0.1, "appearances": 6},  # stale
        }
        _write_scores(tmp_path / "item_scores.json", scores)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.stale_item_count == 2

    def test_hitl_escalation_rate(self, tmp_path: Path) -> None:
        """HITL escalation rate from harness_failures."""
        failures = [
            {"category": "hitl_escalation"},
            {"category": "hitl_escalation"},
            {"category": "quality_gate"},
            {"category": "ci_failure"},
        ]
        _write_failures(tmp_path / "harness_failures.jsonl", failures)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.hitl_escalation_rate == pytest.approx(0.5)

    def test_surprise_rate_from_review_rejection(self, tmp_path: Path) -> None:
        """Surprise rate computed from review_rejection failures."""
        failures = [
            {"category": "review_rejection"},
            {"category": "review_rejection"},
            {"category": "ci_failure"},
            {"category": "quality_gate"},
        ]
        _write_failures(tmp_path / "harness_failures.jsonl", failures)
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        assert metrics.surprise_rate == pytest.approx(0.5)

    def test_malformed_lines_are_skipped(self, tmp_path: Path) -> None:
        """Malformed JSONL lines are silently skipped (not counted toward total)."""
        path = tmp_path / "outcomes.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"outcome": "success"}\nnot-valid-json\n{"outcome": "success"}\n',
            encoding="utf-8",
        )
        metrics = compute_trend_metrics(
            tmp_path / "outcomes.jsonl",
            tmp_path / "item_scores.json",
            tmp_path / "harness_failures.jsonl",
        )
        # Only successfully-parsed lines count: 2 success, malformed skipped
        assert metrics.total_outcomes == 2
        assert metrics.first_pass_rate == 1.0


# ---------------------------------------------------------------------------
# TrendMetrics.active_conditions
# ---------------------------------------------------------------------------


class TestTrendMetricsActiveConditions:
    """Tests for TrendMetrics.active_conditions()."""

    def test_healthy_metrics_no_conditions(self) -> None:
        """No active conditions when metrics are in healthy range."""
        metrics = TrendMetrics(
            first_pass_rate=0.75,
            avg_memory_score=0.7,
            surprise_rate=0.05,
            hitl_escalation_rate=0.1,
            stale_item_count=2,
            total_outcomes=50,
        )
        assert metrics.active_conditions() == []

    def test_first_pass_rate_low_activates_condition(self) -> None:
        """first_pass_rate < 0.2 triggers first_pass_rate_low."""
        metrics = TrendMetrics(
            first_pass_rate=0.18,
            avg_memory_score=0.6,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        assert "first_pass_rate_low" in metrics.active_conditions()

    def test_first_pass_rate_high_activates_condition(self) -> None:
        """first_pass_rate > 0.9 triggers first_pass_rate_high."""
        metrics = TrendMetrics(
            first_pass_rate=0.95,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        assert "first_pass_rate_high" in metrics.active_conditions()


# ---------------------------------------------------------------------------
# Auto-adjustment
# ---------------------------------------------------------------------------


class TestAutoAdjustment:
    """Tests for _apply_adjustments — bounds enforcement and audit trail."""

    def test_adjustment_increments_parameter_on_low_pass_rate(
        self, tmp_path: Path
    ) -> None:
        """Low first_pass_rate triggers +1 adjustment to max_quality_fix_attempts."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.15,
            avg_memory_score=0.6,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        applied = loop._apply_adjustments(metrics)
        assert applied == 1
        assert loop._config.max_quality_fix_attempts == 3

    def test_adjustment_decrements_parameter_on_high_pass_rate(
        self, tmp_path: Path
    ) -> None:
        """High first_pass_rate triggers -1 adjustment to max_quality_fix_attempts."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=3)
        metrics = TrendMetrics(
            first_pass_rate=0.95,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        applied = loop._apply_adjustments(metrics)
        assert applied == 1
        assert loop._config.max_quality_fix_attempts == 2

    def test_adjustment_respects_upper_bound(self, tmp_path: Path) -> None:
        """Parameter cannot exceed TUNABLE_BOUNDS upper limit."""
        hi = TUNABLE_BOUNDS["max_quality_fix_attempts"][1]
        loop = _make_loop(tmp_path, max_quality_fix_attempts=hi)
        metrics = TrendMetrics(
            first_pass_rate=0.1,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        loop._apply_adjustments(metrics)
        assert loop._config.max_quality_fix_attempts == hi

    def test_adjustment_respects_lower_bound(self, tmp_path: Path) -> None:
        """Parameter cannot drop below TUNABLE_BOUNDS lower limit."""
        lo = TUNABLE_BOUNDS["max_quality_fix_attempts"][0]
        loop = _make_loop(tmp_path, max_quality_fix_attempts=lo)
        metrics = TrendMetrics(
            first_pass_rate=0.99,
            avg_memory_score=0.8,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        loop._apply_adjustments(metrics)
        assert loop._config.max_quality_fix_attempts == lo

    def test_no_adjustment_when_metrics_healthy(self, tmp_path: Path) -> None:
        """No adjustment when metrics are in healthy range."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.75,
            avg_memory_score=0.7,
            surprise_rate=0.05,
            hitl_escalation_rate=0.1,
            stale_item_count=2,
            total_outcomes=50,
        )
        applied = loop._apply_adjustments(metrics)
        assert applied == 0
        assert loop._config.max_quality_fix_attempts == 2

    def test_adjustment_writes_decision_audit_record(self, tmp_path: Path) -> None:
        """An adjustment writes a record to decisions.jsonl."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.15,
            avg_memory_score=0.6,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        loop._apply_adjustments(metrics)

        decisions = _load_decisions(loop._decisions_dir)
        assert len(decisions) == 1
        d = decisions[0]
        assert d["type"] == "auto_adjust"
        assert d["parameter"] == "max_quality_fix_attempts"
        assert d["before"] == 2
        assert d["after"] == 3
        assert d["outcome_verified"] is None
        assert "reason" in d
        assert "evidence_summary" in d
        assert "timestamp" in d

    def test_adjustment_populates_pending_list(self, tmp_path: Path) -> None:
        """A successful adjustment is added to the pending verification list."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.15,
            avg_memory_score=0.6,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        loop._apply_adjustments(metrics)
        assert len(loop._pending) == 1
        adj = loop._pending[0]
        assert adj.parameter == "max_quality_fix_attempts"
        assert adj.before == 2
        assert adj.after == 3


# ---------------------------------------------------------------------------
# Decision audit trail helpers
# ---------------------------------------------------------------------------


class TestDecisionAuditTrail:
    """Tests for decision JSONL write/read/update helpers."""

    def test_write_and_load_decision(self, tmp_path: Path) -> None:
        """Written decisions can be loaded back."""
        record = {
            "decision_id": "adj-0001",
            "type": "auto_adjust",
            "parameter": "max_quality_fix_attempts",
            "before": 2,
            "after": 3,
            "outcome_verified": None,
        }
        _write_decision(tmp_path, record)
        loaded = _load_decisions(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["decision_id"] == "adj-0001"

    def test_update_decision_outcome(self, tmp_path: Path) -> None:
        """update_decision patches a specific record by decision_id."""
        record = {
            "decision_id": "adj-0001",
            "outcome_verified": None,
        }
        _write_decision(tmp_path, record)
        _update_decision(tmp_path, "adj-0001", {"outcome_verified": "improved"})
        loaded = _load_decisions(tmp_path)
        assert loaded[0]["outcome_verified"] == "improved"

    def test_update_nonexistent_decision_is_noop(self, tmp_path: Path) -> None:
        """Updating a decision_id that doesn't exist is a no-op."""
        _write_decision(tmp_path, {"decision_id": "adj-0001", "v": 1})
        _update_decision(tmp_path, "adj-9999", {"v": 2})
        loaded = _load_decisions(tmp_path)
        assert loaded[0]["v"] == 1

    def test_decision_counter_increments(self, tmp_path: Path) -> None:
        """Sequential calls to _next_decision_id produce distinct IDs."""
        id1 = _next_decision_id(tmp_path)
        id2 = _next_decision_id(tmp_path)
        assert id1 != id2
        assert id1.startswith("adj-")
        assert id2.startswith("adj-")
        assert len(id1.split("-")[1]) == 8  # 8 hex chars from UUID
        assert len(id2.split("-")[1]) == 8

    def test_multiple_decisions_appended(self, tmp_path: Path) -> None:
        """Multiple writes produce multiple JSONL lines."""
        for i in range(3):
            _write_decision(tmp_path, {"decision_id": f"adj-{i:04d}"})
        loaded = _load_decisions(tmp_path)
        assert len(loaded) == 3


# ---------------------------------------------------------------------------
# Outcome verification
# ---------------------------------------------------------------------------


class TestOutcomeVerification:
    """Tests for _verify_pending_adjustments."""

    def _make_adj(
        self,
        tmp_path: Path,
        loop: HealthMonitorLoop,
        *,
        before: int = 2,
        after: int = 3,
        outcomes_at: int = 10,
        metric_val: float = 0.15,
    ) -> PendingAdjustment:
        decision_id = _next_decision_id(loop._decisions_dir)
        _write_decision(
            loop._decisions_dir,
            {
                "decision_id": decision_id,
                "type": "auto_adjust",
                "parameter": "max_quality_fix_attempts",
                "before": before,
                "after": after,
                "outcome_verified": None,
            },
        )
        adj = PendingAdjustment(
            decision_id=decision_id,
            parameter="max_quality_fix_attempts",
            before=before,
            after=after,
            metric_name="first_pass_rate",
            metric_value=metric_val,
            outcomes_at_adjustment=outcomes_at,
        )
        loop._pending.append(adj)
        return adj

    def test_verification_improved(self, tmp_path: Path) -> None:
        """When metric improves significantly, marks outcome as 'improved'."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=3)
        self._make_adj(tmp_path, loop, outcomes_at=5)

        # Write enough outcomes to exceed verification_window=5
        outcomes = [{"outcome": "success"}] * 12
        _write_outcomes(loop._outcomes_path, outcomes)

        # Improved first_pass_rate (was 0.15, now 0.85)
        good_metrics = TrendMetrics(
            first_pass_rate=0.85,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=12,
        )
        loop._verify_pending_adjustments(good_metrics)

        assert len(loop._pending) == 0
        decisions = _load_decisions(loop._decisions_dir)
        assert decisions[-1]["outcome_verified"] == "improved"

    def test_verification_reverted(self, tmp_path: Path) -> None:
        """When metric worsens, reverts the adjustment and marks 'reverted'."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=3)
        self._make_adj(tmp_path, loop, before=2, after=3, outcomes_at=5)

        outcomes = [{"outcome": "failure"}] * 12
        _write_outcomes(loop._outcomes_path, outcomes)

        # Worsened first_pass_rate (was 0.15, now 0.0 — clearly worse)
        bad_metrics = TrendMetrics(
            first_pass_rate=0.0,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=12,
        )
        loop._verify_pending_adjustments(bad_metrics)

        # Parameter reverted
        assert loop._config.max_quality_fix_attempts == 2
        decisions = _load_decisions(loop._decisions_dir)
        assert decisions[-1]["outcome_verified"] == "reverted"

    def test_verification_neutral(self, tmp_path: Path) -> None:
        """When metric does not change significantly, marks as 'neutral'."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=3)
        self._make_adj(tmp_path, loop, outcomes_at=5, metric_val=0.15)

        outcomes = [{"outcome": "success"}] * 4 + [{"outcome": "failure"}] * 8
        _write_outcomes(loop._outcomes_path, outcomes)

        # Similar first_pass_rate (was 0.15, now 0.18 — slightly better but not enough)
        neutral_metrics = TrendMetrics(
            first_pass_rate=0.18,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=12,
        )
        loop._verify_pending_adjustments(neutral_metrics)

        assert loop._config.max_quality_fix_attempts == 3  # unchanged
        decisions = _load_decisions(loop._decisions_dir)
        assert decisions[-1]["outcome_verified"] == "neutral"

    def test_pending_not_verified_before_window(self, tmp_path: Path) -> None:
        """Pending adjustment stays pending until verification_window is reached."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=3)
        self._make_adj(tmp_path, loop, outcomes_at=10)

        # Only 3 new outcomes (window=5, needs 5+)
        outcomes = [{"outcome": "success"}] * 13  # total=13, since_adj=3
        _write_outcomes(loop._outcomes_path, outcomes)

        metrics = TrendMetrics(
            first_pass_rate=0.8,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=13,
        )
        loop._verify_pending_adjustments(metrics)

        # Still pending — not enough new outcomes
        assert len(loop._pending) == 1
        decisions = _load_decisions(loop._decisions_dir)
        assert decisions[-1]["outcome_verified"] is None


# ---------------------------------------------------------------------------
# HITL recommendations
# ---------------------------------------------------------------------------


class TestHITLRecommendations:
    """Tests for _file_hitl_recommendations — writes to JSONL, not GitHub."""

    def _load_recs(self, tmp_path: Path) -> list[dict]:
        import json

        # Use the loop config data_path directly
        path = (
            tmp_path / "repo" / ".hydraflow" / "memory" / "hitl_recommendations.jsonl"
        )
        if not path.exists():
            return []
        return [
            json.loads(l) for l in path.read_text().strip().splitlines() if l.strip()
        ]

    @pytest.mark.asyncio
    async def test_writes_rec_for_high_surprise_rate(self, tmp_path: Path) -> None:
        """High surprise_rate writes a recommendation to JSONL."""
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.7,
            surprise_rate=0.5,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        await loop._file_hitl_recommendations(metrics)

        recs = self._load_recs(tmp_path)
        assert len(recs) >= 1
        assert any("surprise_rate" in r["title"] for r in recs)

    @pytest.mark.asyncio
    async def test_writes_rec_for_high_hitl_rate(self, tmp_path: Path) -> None:
        """High hitl_escalation_rate writes a recommendation."""
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.7,
            surprise_rate=0.0,
            hitl_escalation_rate=0.5,
            stale_item_count=0,
            total_outcomes=50,
        )
        await loop._file_hitl_recommendations(metrics)

        recs = self._load_recs(tmp_path)
        assert any("hitl_escalation_rate" in r["title"] for r in recs)

    @pytest.mark.asyncio
    async def test_no_rec_for_healthy_metrics(self, tmp_path: Path) -> None:
        """Healthy metrics produce no recommendations."""
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.75,
            avg_memory_score=0.7,
            surprise_rate=0.05,
            hitl_escalation_rate=0.1,
            stale_item_count=2,
            total_outcomes=50,
        )
        await loop._file_hitl_recommendations(metrics)

        recs = self._load_recs(tmp_path)
        assert len(recs) == 0

    @pytest.mark.asyncio
    async def test_writes_rec_for_low_avg_score(self, tmp_path: Path) -> None:
        """Low avg_memory_score writes a recommendation."""
        loop = _make_loop(tmp_path)
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.2,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=50,
        )
        await loop._file_hitl_recommendations(metrics)

        recs = self._load_recs(tmp_path)
        assert any("avg_memory_score" in r["title"] for r in recs)


# ---------------------------------------------------------------------------
# Sentry metric emission
# ---------------------------------------------------------------------------


class TestSentryMetricEmission:
    """Tests for _emit_sentry_metrics."""

    def test_emits_all_four_measurements(self) -> None:
        """All four Sentry measurements are set when sentry_sdk is available."""
        mock_sentry = MagicMock()
        metrics = TrendMetrics(
            first_pass_rate=0.75,
            avg_memory_score=0.65,
            surprise_rate=0.1,
            hitl_escalation_rate=0.05,
            stale_item_count=3,
            total_outcomes=50,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            HealthMonitorLoop._emit_sentry_metrics(metrics)

        calls = {c[0][0]: c[0][1] for c in mock_sentry.set_measurement.call_args_list}
        assert "memory.avg_score" in calls
        assert "memory.first_pass_rate" in calls
        assert "memory.surprise_rate" in calls
        assert "memory.stale_items" in calls
        assert calls["memory.avg_score"] == pytest.approx(0.65)
        assert calls["memory.first_pass_rate"] == pytest.approx(0.75)
        assert calls["memory.surprise_rate"] == pytest.approx(0.1)
        assert calls["memory.stale_items"] == pytest.approx(3.0)

    def test_no_error_when_sentry_unavailable(self) -> None:
        """ImportError from sentry_sdk is silently handled."""
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )
        import sys

        original = sys.modules.pop("sentry_sdk", None)
        try:
            # Should not raise
            HealthMonitorLoop._emit_sentry_metrics(metrics)
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original


# ---------------------------------------------------------------------------
# Integration: _do_work
# ---------------------------------------------------------------------------


class TestDoWork:
    """Integration tests for the full _do_work cycle."""

    @pytest.mark.asyncio
    async def test_do_work_returns_stats_dict(self, tmp_path: Path) -> None:
        """_do_work returns a dict with expected keys."""
        loop = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result is not None
        assert "first_pass_rate" in result
        assert "avg_memory_score" in result
        assert "surprise_rate" in result
        assert "hitl_escalation_rate" in result
        assert "stale_item_count" in result
        assert "adjustments_made" in result
        assert "total_outcomes" in result

    @pytest.mark.asyncio
    async def test_do_work_applies_adjustment_on_low_pass_rate(
        self, tmp_path: Path
    ) -> None:
        """_do_work auto-adjusts config when first_pass_rate is low."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        # Write outcomes with very low pass rate
        outcomes = [{"outcome": "failure"}] * 45 + [{"outcome": "success"}] * 5
        _write_outcomes(loop._outcomes_path, outcomes)

        result = await loop._do_work()
        assert result is not None
        assert result["adjustments_made"] == 1
        assert loop._config.max_quality_fix_attempts == 3

    @pytest.mark.asyncio
    async def test_do_work_no_adjustment_on_healthy_metrics(
        self, tmp_path: Path
    ) -> None:
        """_do_work makes no adjustment when metrics are in healthy range."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        outcomes = [{"outcome": "success"}] * 40 + [{"outcome": "failure"}] * 10
        _write_outcomes(loop._outcomes_path, outcomes)

        result = await loop._do_work()
        assert result is not None
        assert result["adjustments_made"] == 0
        assert loop._config.max_quality_fix_attempts == 2

    @pytest.mark.asyncio
    async def test_do_work_runs_full_loop(self, tmp_path: Path) -> None:
        """Loop executes a cycle and status callback is called."""
        deps = make_bg_loop_deps(tmp_path, health_monitor_interval=60)
        loop = HealthMonitorLoop(
            config=deps.config,
            deps=deps.loop_deps,
        )

        # Execute one cycle directly (without the full run loop)
        await loop._execute_cycle()

        deps.status_cb.assert_called()

    @pytest.mark.asyncio
    async def test_do_work_runs_log_ingestion_when_log_dir_exists(
        self, tmp_path: Path
    ) -> None:
        """_do_work runs log ingestion when a logs directory exists."""
        loop = _make_loop(tmp_path)
        # Create the expected logs directory
        log_dir = loop._config.data_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        with patch(
            "health_monitor_loop.HealthMonitorLoop._emit_sentry_metrics"
        ) as mock_emit:
            result = await loop._do_work()

        assert result is not None
        # _emit_sentry_metrics should have been called with log pattern params
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args[1]
        assert "log_patterns_total" in call_kwargs
        assert "log_patterns_novel" in call_kwargs
        assert "log_patterns_escalating" in call_kwargs

    @pytest.mark.asyncio
    async def test_do_work_skips_log_ingestion_when_no_log_dir(
        self, tmp_path: Path
    ) -> None:
        """_do_work silently skips log ingestion when log dir doesn't exist."""
        loop = _make_loop(tmp_path)
        # Ensure no logs dir exists
        log_dir = loop._config.data_root / "logs"
        assert not log_dir.exists()

        # Should not raise; log_patterns_* default to 0
        with patch(
            "health_monitor_loop.HealthMonitorLoop._emit_sentry_metrics"
        ) as mock_emit:
            result = await loop._do_work()

        assert result is not None
        call_kwargs = mock_emit.call_args[1]
        assert call_kwargs.get("log_patterns_total", 0) == 0

    def test_last_log_scan_initialized_to_none(self, tmp_path: Path) -> None:
        """_last_log_scan attribute is initialized to None in __init__."""
        loop = _make_loop(tmp_path)
        assert loop._last_log_scan is None


# ---------------------------------------------------------------------------
# Sentry log pattern metrics
# ---------------------------------------------------------------------------


class TestSentryLogPatternMetrics:
    """Tests for log-pattern parameters in _emit_sentry_metrics."""

    def test_emits_log_pattern_measurements(self) -> None:
        """Log pattern Sentry measurements are emitted when provided."""
        mock_sentry = MagicMock()
        metrics = TrendMetrics(
            first_pass_rate=0.75,
            avg_memory_score=0.65,
            surprise_rate=0.1,
            hitl_escalation_rate=0.05,
            stale_item_count=3,
            total_outcomes=50,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            HealthMonitorLoop._emit_sentry_metrics(
                metrics,
                log_patterns_total=10,
                log_patterns_novel=3,
                log_patterns_escalating=1,
            )

        calls = {c[0][0]: c[0][1] for c in mock_sentry.set_measurement.call_args_list}
        assert calls.get("memory.log_patterns_total") == pytest.approx(10)
        assert calls.get("memory.log_patterns_novel") == pytest.approx(3)
        assert calls.get("memory.log_patterns_escalating") == pytest.approx(1)

    def test_log_pattern_params_default_to_zero(self) -> None:
        """Log pattern params default to 0 when not provided."""
        mock_sentry = MagicMock()
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=10,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            HealthMonitorLoop._emit_sentry_metrics(metrics)

        calls = {c[0][0]: c[0][1] for c in mock_sentry.set_measurement.call_args_list}
        assert calls.get("memory.log_patterns_total") == pytest.approx(0)
        assert calls.get("memory.log_patterns_novel") == pytest.approx(0)
        assert calls.get("memory.log_patterns_escalating") == pytest.approx(0)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfigAdditions:
    """Tests for config field additions."""

    def test_health_monitor_interval_default(self, tmp_path: Path) -> None:
        """health_monitor_interval defaults to 7200."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path)
        assert config.health_monitor_interval == 7200

    def test_health_monitor_interval_override(self, tmp_path: Path) -> None:
        """health_monitor_interval can be overridden."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(repo_root=tmp_path, health_monitor_interval=300)
        assert config.health_monitor_interval == 300

    def test_loop_get_default_interval_uses_config(self, tmp_path: Path) -> None:
        """_get_default_interval returns config.health_monitor_interval."""
        loop = _make_loop(tmp_path, interval=1800)
        assert loop._get_default_interval() == 1800


# ---------------------------------------------------------------------------
# TUNABLE_BOUNDS and ADJUSTMENT_RULES sanity
# ---------------------------------------------------------------------------


class TestConstantsSanity:
    """Basic sanity checks for module-level constants."""

    def test_tunable_bounds_all_valid(self) -> None:
        """All TUNABLE_BOUNDS entries have lo < hi."""
        for param, (lo, hi) in TUNABLE_BOUNDS.items():
            assert lo < hi, f"{param}: lo={lo} >= hi={hi}"

    def test_adjustment_rules_reference_known_parameters(self) -> None:
        """All ADJUSTMENT_RULES reference parameters in TUNABLE_BOUNDS."""
        for _condition, param, _step in ADJUSTMENT_RULES:
            assert param in TUNABLE_BOUNDS, f"Unknown parameter: {param}"


# ---------------------------------------------------------------------------
# Sentry breadcrumbs and expanded metrics
# ---------------------------------------------------------------------------


class TestSentryBreadcrumbs:
    """Tests for Sentry breadcrumb emission on auto-adjustment and HITL filing."""

    def test_apply_adjustments_emits_breadcrumb(self, tmp_path: Path) -> None:
        """_apply_adjustments adds a breadcrumb when sentry_sdk is available."""
        mock_sentry = MagicMock()
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.1,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            loop._apply_adjustments(metrics)

        mock_sentry.add_breadcrumb.assert_called_once()
        call_kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert call_kwargs["category"] == "memory.auto_adjust"
        assert call_kwargs["level"] == "warning"
        data = call_kwargs["data"]
        assert data["parameter"] == "max_quality_fix_attempts"
        assert data["before"] == 2
        assert data["after"] == 3

    def test_apply_adjustments_no_breadcrumb_when_sentry_unavailable(
        self, tmp_path: Path
    ) -> None:
        """_apply_adjustments does not raise when sentry_sdk is missing."""
        loop = _make_loop(tmp_path, max_quality_fix_attempts=2)
        metrics = TrendMetrics(
            first_pass_rate=0.1,
            avg_memory_score=0.5,
            surprise_rate=0.0,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        original = sys.modules.pop("sentry_sdk", None)
        try:
            loop._apply_adjustments(metrics)  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    @pytest.mark.asyncio
    async def test_file_hitl_recommendations_emits_capture_message(
        self, tmp_path: Path
    ) -> None:
        """_file_hitl_recommendations calls capture_message for each HITL issue filed."""
        mock_sentry = MagicMock()
        mock_prs = MagicMock()
        mock_prs.create_issue = AsyncMock(return_value=42)
        loop = _make_loop(tmp_path)
        loop._prs = mock_prs

        # High surprise_rate triggers a recommendation
        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.6,
            surprise_rate=0.99,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            await loop._file_hitl_recommendations(metrics)

        mock_sentry.capture_message.assert_called()
        call_args = mock_sentry.capture_message.call_args
        assert "surprise_rate" in call_args[0][0]
        assert call_args[1]["level"] == "warning"

    @pytest.mark.asyncio
    async def test_file_hitl_no_capture_message_when_sentry_unavailable(
        self, tmp_path: Path
    ) -> None:
        """_file_hitl_recommendations does not raise when sentry_sdk is missing."""
        mock_prs = MagicMock()
        mock_prs.create_issue = AsyncMock(return_value=1)
        loop = _make_loop(tmp_path)
        loop._prs = mock_prs

        metrics = TrendMetrics(
            first_pass_rate=0.5,
            avg_memory_score=0.6,
            surprise_rate=0.99,
            hitl_escalation_rate=0.0,
            stale_item_count=0,
            total_outcomes=20,
        )
        original = sys.modules.pop("sentry_sdk", None)
        try:
            await loop._file_hitl_recommendations(metrics)  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_emit_sentry_metrics_includes_knowledge_gaps_and_adjustments(
        self,
    ) -> None:
        """_emit_sentry_metrics emits memory.knowledge_gaps and memory.auto_adjustments."""
        mock_sentry = MagicMock()
        metrics = TrendMetrics(
            first_pass_rate=0.8,
            avg_memory_score=0.7,
            surprise_rate=0.05,
            hitl_escalation_rate=0.0,
            stale_item_count=1,
            total_outcomes=30,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            HealthMonitorLoop._emit_sentry_metrics(
                metrics, gap_count=4, adjustment_count=2
            )

        calls = {c[0][0]: c[0][1] for c in mock_sentry.set_measurement.call_args_list}
        assert calls.get("memory.knowledge_gaps") == 4
        assert calls.get("memory.auto_adjustments") == 2

    def test_emit_sentry_metrics_defaults_to_zero_counts(self) -> None:
        """_emit_sentry_metrics defaults gap_count and adjustment_count to 0."""
        mock_sentry = MagicMock()
        metrics = TrendMetrics(
            first_pass_rate=0.8,
            avg_memory_score=0.7,
            surprise_rate=0.05,
            hitl_escalation_rate=0.0,
            stale_item_count=1,
            total_outcomes=30,
        )

        with patch.dict("sys.modules", {"sentry_sdk": mock_sentry}):
            HealthMonitorLoop._emit_sentry_metrics(metrics)

        calls = {c[0][0]: c[0][1] for c in mock_sentry.set_measurement.call_args_list}
        assert calls.get("memory.knowledge_gaps") == 0
        assert calls.get("memory.auto_adjustments") == 0
