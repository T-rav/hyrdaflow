"""Tests for confidence calibration store and weight adjustment."""

from __future__ import annotations

from pathlib import Path

from confidence import ConfidenceWeights
from confidence_calibration import (
    CalibrationStore,
    DecisionOutcome,
    calibrate_weights,
    compute_outcome_correct,
)
from release_decision import ReleaseAction


def _make_outcome(
    *,
    pr: int = 1,
    action: ReleaseAction = ReleaseAction.AUTO_MERGE,
    confidence: float = 0.85,
    risk: float = 0.1,
    verification_passed: bool | None = None,
    was_reverted: bool = False,
    caused_hitl: bool = False,
    was_reworked: bool = False,
) -> DecisionOutcome:
    return DecisionOutcome(
        issue_number=pr,
        pr_number=pr,
        action=action,
        confidence_score=confidence,
        confidence_rank="high" if confidence >= 0.8 else "medium",
        risk_score=risk,
        risk_level="low" if risk < 0.25 else "medium",
        mode="observe",
        verification_passed=verification_passed,
        was_reverted=was_reverted,
        caused_hitl=caused_hitl,
        was_reworked=was_reworked,
    )


class TestComputeOutcomeCorrect:
    def test_clean_merge_is_correct(self) -> None:
        o = _make_outcome(verification_passed=True)
        assert compute_outcome_correct(o) is True

    def test_reverted_auto_merge_is_wrong(self) -> None:
        o = _make_outcome(was_reverted=True)
        assert compute_outcome_correct(o) is False

    def test_hitl_auto_merge_is_wrong(self) -> None:
        o = _make_outcome(caused_hitl=True)
        assert compute_outcome_correct(o) is False

    def test_reworked_auto_merge_is_wrong(self) -> None:
        o = _make_outcome(was_reworked=True)
        assert compute_outcome_correct(o) is False

    def test_held_and_bad_outcome_is_correct(self) -> None:
        o = _make_outcome(
            action=ReleaseAction.HOLD_FOR_REVIEW,
            was_reverted=True,
        )
        assert compute_outcome_correct(o) is True

    def test_held_clean_outcome_is_too_conservative(self) -> None:
        o = _make_outcome(
            action=ReleaseAction.HOLD_FOR_REVIEW,
            verification_passed=True,
        )
        assert compute_outcome_correct(o) is False

    def test_no_data_returns_none(self) -> None:
        o = _make_outcome()
        assert compute_outcome_correct(o) is None

    def test_verification_failed_auto_merge_is_wrong(self) -> None:
        o = _make_outcome(verification_passed=False)
        assert compute_outcome_correct(o) is False


class TestCalibrationStore:
    def test_record_and_load(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        o = _make_outcome(pr=42)
        store.record_outcome(o)

        loaded = store.load_outcomes()
        assert len(loaded) == 1
        assert loaded[0].pr_number == 42

    def test_load_empty(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        assert store.load_outcomes() == []

    def test_multiple_records(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        for i in range(5):
            store.record_outcome(_make_outcome(pr=i + 1))

        loaded = store.load_outcomes()
        assert len(loaded) == 5

    def test_update_outcome(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        store.record_outcome(_make_outcome(pr=42))

        updated = store.update_outcome(42, verification_passed=True)
        assert updated is True

        loaded = store.load_outcomes()
        assert loaded[0].verification_passed is True
        assert loaded[0].outcome_correct is True

    def test_update_nonexistent_returns_false(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        store.record_outcome(_make_outcome(pr=42))

        updated = store.update_outcome(999, verification_passed=True)
        assert updated is False

    def test_update_reverted(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        store.record_outcome(_make_outcome(pr=42))

        store.update_outcome(42, was_reverted=True)
        loaded = store.load_outcomes()
        assert loaded[0].was_reverted is True
        assert loaded[0].outcome_correct is False

    def test_outcomes_with_judgement(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        store.record_outcome(_make_outcome(pr=1))  # no judgement
        o2 = _make_outcome(pr=2, verification_passed=True)
        o2.outcome_correct = True
        store.record_outcome(o2)

        judged = store.outcomes_with_judgement()
        assert len(judged) == 1
        assert judged[0].pr_number == 2

    def test_load_limit(self, tmp_path: Path) -> None:
        store = CalibrationStore(tmp_path / "outcomes.jsonl")
        for i in range(10):
            store.record_outcome(_make_outcome(pr=i + 1))

        loaded = store.load_outcomes(limit=3)
        assert len(loaded) == 3
        # Should be the last 3
        assert loaded[0].pr_number == 8


class TestCalibrateWeights:
    def _make_judged_outcomes(
        self,
        correct: int = 18,
        false_positive: int = 1,
        false_negative: int = 1,
    ) -> list[DecisionOutcome]:
        outcomes: list[DecisionOutcome] = []
        for i in range(correct):
            o = _make_outcome(pr=i + 1, verification_passed=True)
            o.outcome_correct = True
            outcomes.append(o)
        for i in range(false_positive):
            o = _make_outcome(
                pr=correct + i + 1,
                action=ReleaseAction.AUTO_MERGE,
                was_reverted=True,
            )
            o.outcome_correct = False
            outcomes.append(o)
        for i in range(false_negative):
            o = _make_outcome(
                pr=correct + false_positive + i + 1,
                action=ReleaseAction.HOLD_FOR_REVIEW,
                verification_passed=True,
            )
            o.outcome_correct = False
            outcomes.append(o)
        return outcomes

    def test_insufficient_samples_no_change(self) -> None:
        weights = ConfidenceWeights()
        outcomes = self._make_judged_outcomes(correct=5)
        new_weights, stats = calibrate_weights(weights, outcomes, min_samples=20)
        assert new_weights == weights
        assert stats["adjusted"] is False
        assert "insufficient" in stats.get("skipped_reason", "")

    def test_balanced_outcomes_no_adjustment(self) -> None:
        weights = ConfidenceWeights()
        outcomes = self._make_judged_outcomes(
            correct=20, false_positive=0, false_negative=0
        )
        new_weights, stats = calibrate_weights(weights, outcomes, min_samples=20)
        assert stats["adjusted"] is False

    def test_false_positives_tighten(self) -> None:
        weights = ConfidenceWeights()
        outcomes = self._make_judged_outcomes(
            correct=15, false_positive=5, false_negative=0
        )
        new_weights, stats = calibrate_weights(weights, outcomes, min_samples=20)
        assert stats["adjusted"] is True
        assert stats["adjustment_direction"] == "tighten"

    def test_false_negatives_loosen(self) -> None:
        weights = ConfidenceWeights()
        outcomes = self._make_judged_outcomes(
            correct=15, false_positive=0, false_negative=5
        )
        new_weights, stats = calibrate_weights(weights, outcomes, min_samples=20)
        assert stats["adjusted"] is True
        assert stats["adjustment_direction"] == "loosen"

    def test_anti_reinforcement(self) -> None:
        weights = ConfidenceWeights()
        # 90% auto-merge with some false positives
        outcomes: list[DecisionOutcome] = []
        for i in range(18):
            o = _make_outcome(pr=i + 1, action=ReleaseAction.AUTO_MERGE)
            o.outcome_correct = True
            outcomes.append(o)
        for i in range(2):
            o = _make_outcome(
                pr=20 + i, action=ReleaseAction.AUTO_MERGE, was_reverted=True
            )
            o.outcome_correct = False
            outcomes.append(o)

        new_weights, stats = calibrate_weights(weights, outcomes, min_samples=20)
        assert stats.get("anti_reinforcement") is True

    def test_weights_clamped(self) -> None:
        # Start with weights near the floor
        weights = ConfidenceWeights(
            complexity=0.05,
            plan_quality=0.05,
            delta_fidelity=0.05,
            review_clean=0.05,
            ci_clean=0.05,
            visual_clean=0.05,
            escalation_free=0.05,
            security_clean=0.05,
            history=0.05,
            rework_penalty=0.05,
        )
        outcomes = self._make_judged_outcomes(correct=15, false_positive=5)
        new_weights, _ = calibrate_weights(weights, outcomes, min_samples=20)
        data = new_weights.model_dump()
        for val in data.values():
            assert val >= 0.05
            assert val <= 0.40

    def test_max_adjustment_bounded(self) -> None:
        weights = ConfidenceWeights()
        original = weights.model_dump()
        outcomes = self._make_judged_outcomes(correct=10, false_positive=10)
        new_weights, _ = calibrate_weights(
            weights, outcomes, min_samples=20, max_adjustment=0.01
        )
        new_data = new_weights.model_dump()
        for key in original:
            diff = abs(new_data[key] - original[key])
            assert diff <= 0.01 + 1e-9  # float tolerance
