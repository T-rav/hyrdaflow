"""Tests for the Swamp-lifecycle Pydantic models.

Covers #6421 (PlanReview / PlanFinding / PlanFindingSeverity), #6424
(ReproductionResult / ReproductionOutcome), and #6423 (RouteBackRecord).

Per CLAUDE.md → Avoided Patterns: when adding fields to these models,
update this test file alongside the change. Exact-match serialization
checks live here so silent regressions during unrelated refactors get
caught at CI time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import (
    PlanFinding,
    PlanFindingSeverity,
    PlanReview,
    ReproductionOutcome,
    ReproductionResult,
    RouteBackRecord,
)

# ---------------------------------------------------------------------------
# PlanFindingSeverity (#6421)
# ---------------------------------------------------------------------------


class TestPlanFindingSeverity:
    def test_all_severities_present(self) -> None:
        assert PlanFindingSeverity.CRITICAL == "critical"
        assert PlanFindingSeverity.HIGH == "high"
        assert PlanFindingSeverity.MEDIUM == "medium"
        assert PlanFindingSeverity.LOW == "low"
        assert PlanFindingSeverity.INFO == "info"

    def test_serializes_as_string_value(self) -> None:
        finding = PlanFinding(
            severity=PlanFindingSeverity.CRITICAL,
            dimension="correctness",
            description="missing edge case",
        )
        dumped = finding.model_dump()
        assert dumped["severity"] == "critical"


# ---------------------------------------------------------------------------
# PlanFinding (#6421)
# ---------------------------------------------------------------------------


class TestPlanFinding:
    def test_required_fields(self) -> None:
        finding = PlanFinding(
            severity=PlanFindingSeverity.HIGH,
            dimension="test_strategy",
            description="no test for the error path",
        )
        assert finding.suggestion == ""

    def test_with_suggestion(self) -> None:
        finding = PlanFinding(
            severity=PlanFindingSeverity.MEDIUM,
            dimension="convention",
            description="adds Pydantic field without test update",
            suggestion="Update tests/test_models.py exact-match assertions",
        )
        assert "tests/test_models.py" in finding.suggestion

    def test_serialization_round_trip(self) -> None:
        original = PlanFinding(
            severity=PlanFindingSeverity.CRITICAL,
            dimension="correctness",
            description="ignores reproduction reference",
            suggestion="Reference tests/regressions/test_issue_42.py",
        )
        dumped = original.model_dump()
        rebuilt = PlanFinding.model_validate(dumped)
        assert rebuilt == original


# ---------------------------------------------------------------------------
# PlanReview (#6421)
# ---------------------------------------------------------------------------


class TestPlanReview:
    def test_clean_review_passes(self) -> None:
        review = PlanReview(issue_number=42, success=True)
        assert review.is_clean is True
        assert review.has_blocking_findings is False

    def test_critical_finding_blocks_advance(self) -> None:
        review = PlanReview(
            issue_number=42,
            success=True,
            findings=[
                PlanFinding(
                    severity=PlanFindingSeverity.CRITICAL,
                    dimension="correctness",
                    description="logic is wrong",
                )
            ],
        )
        assert review.has_blocking_findings is True
        assert review.is_clean is False

    def test_high_finding_also_blocks_advance(self) -> None:
        review = PlanReview(
            issue_number=42,
            success=True,
            findings=[
                PlanFinding(
                    severity=PlanFindingSeverity.HIGH,
                    dimension="test_strategy",
                    description="no regression test",
                )
            ],
        )
        assert review.has_blocking_findings is True
        assert review.is_clean is False

    def test_medium_finding_does_not_block(self) -> None:
        review = PlanReview(
            issue_number=42,
            success=True,
            findings=[
                PlanFinding(
                    severity=PlanFindingSeverity.MEDIUM,
                    dimension="scope_creep",
                    description="adds an unrelated refactor",
                )
            ],
        )
        assert review.has_blocking_findings is False
        assert review.is_clean is True

    def test_failed_review_is_not_clean(self) -> None:
        review = PlanReview(issue_number=42, success=False, error="boom")
        assert review.is_clean is False

    def test_default_plan_version_is_one(self) -> None:
        review = PlanReview(issue_number=42, success=True)
        assert review.plan_version == 1

    def test_default_instantiation_has_expected_keys(self) -> None:
        """A PlanReview built with only required fields must serialize
        with the same key set as a fully-explicit instance — guards
        against default_factory regressions where adding a field with
        a broken default lambda would only be caught by explicit-value
        tests, never by the default path.
        """
        default_dump = PlanReview(issue_number=42, success=True).model_dump()
        explicit_dump = PlanReview(
            issue_number=42,
            plan_version=1,
            success=True,
            findings=[],
            summary="",
            transcript="",
            duration_seconds=0.0,
            error=None,
        ).model_dump()
        assert set(default_dump.keys()) == set(explicit_dump.keys())
        assert default_dump["issue_number"] == 42
        assert default_dump["findings"] == []
        assert default_dump["plan_version"] == 1
        assert default_dump["error"] is None

    def test_serialization_includes_all_fields(self) -> None:
        review = PlanReview(
            issue_number=42,
            plan_version=2,
            success=True,
            summary="reviewed v2",
            transcript="...",
            duration_seconds=12.5,
            findings=[
                PlanFinding(
                    severity=PlanFindingSeverity.LOW,
                    dimension="convention",
                    description="minor",
                )
            ],
        )
        dumped = review.model_dump()
        assert set(dumped.keys()) == {
            "issue_number",
            "plan_version",
            "success",
            "findings",
            "summary",
            "transcript",
            "duration_seconds",
            "error",
        }
        assert dumped["plan_version"] == 2
        assert len(dumped["findings"]) == 1


# ---------------------------------------------------------------------------
# ReproductionOutcome / ReproductionResult (#6424)
# ---------------------------------------------------------------------------


class TestReproductionOutcome:
    def test_all_outcomes_present(self) -> None:
        assert ReproductionOutcome.SUCCESS == "success"
        assert ReproductionOutcome.PARTIAL == "partial"
        assert ReproductionOutcome.UNABLE == "unable"


class TestReproductionResult:
    def test_success_outcome_with_test(self) -> None:
        result = ReproductionResult(
            issue_number=42,
            outcome=ReproductionOutcome.SUCCESS,
            test_path="tests/regressions/test_issue_42.py",
            failing_output="AssertionError: expected 1, got 0",
            confidence=0.95,
        )
        assert result.outcome == "success"
        assert result.test_path.endswith("test_issue_42.py")

    def test_partial_outcome_with_script(self) -> None:
        result = ReproductionResult(
            issue_number=42,
            outcome=ReproductionOutcome.PARTIAL,
            repro_script="curl -X POST .../endpoint",
            confidence=0.6,
        )
        assert result.outcome == "partial"
        assert result.test_path == ""
        assert "curl" in result.repro_script

    def test_unable_outcome_records_investigation(self) -> None:
        result = ReproductionResult(
            issue_number=42,
            outcome=ReproductionOutcome.UNABLE,
            investigation="Could not reproduce — issue body lacks stack trace",
            confidence=0.0,
        )
        assert result.outcome == "unable"
        assert "stack trace" in result.investigation

    def test_confidence_above_one_raises(self) -> None:
        """Pydantic ValidationError fires when confidence > 1.

        Uses pytest.raises so a future change that drops the bound is
        an immediate failure rather than a silent green test (the
        previous try/except form would pass with zero assertions if
        the constructor stopped raising).
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="less than or equal to 1"):
            ReproductionResult(
                issue_number=42,
                outcome=ReproductionOutcome.SUCCESS,
                confidence=1.5,
            )

    def test_confidence_below_zero_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            ReproductionResult(
                issue_number=42,
                outcome=ReproductionOutcome.SUCCESS,
                confidence=-0.1,
            )

    def test_serialization_round_trip(self) -> None:
        original = ReproductionResult(
            issue_number=42,
            outcome=ReproductionOutcome.SUCCESS,
            test_path="tests/regressions/test_issue_42.py",
            failing_output="boom",
            confidence=0.9,
        )
        rebuilt = ReproductionResult.model_validate(original.model_dump())
        assert rebuilt == original


# ---------------------------------------------------------------------------
# RouteBackRecord (#6423)
# ---------------------------------------------------------------------------


class TestRouteBackRecord:
    def test_required_fields(self) -> None:
        record = RouteBackRecord(
            issue_number=42,
            from_stage="ready",
            to_stage="plan",
            reason="adversarial review found critical gaps",
        )
        assert record.feedback_context == ""
        assert record.timestamp  # auto-populated

    def test_with_feedback_context(self) -> None:
        record = RouteBackRecord(
            issue_number=42,
            from_stage="ready",
            to_stage="plan",
            reason="missing reproduction reference",
            feedback_context="Reference tests/regressions/test_issue_42.py",
        )
        assert "test_issue_42.py" in record.feedback_context

    def test_serialization_round_trip(self) -> None:
        original = RouteBackRecord(
            issue_number=42,
            from_stage="review",
            to_stage="ready",
            reason="implementation incomplete",
            feedback_context="add the missing handler",
        )
        rebuilt = RouteBackRecord.model_validate(original.model_dump())
        assert rebuilt == original

    def test_serialization_keys_exact(self) -> None:
        record = RouteBackRecord(
            issue_number=42,
            from_stage="ready",
            to_stage="plan",
            reason="critical findings",
        )
        dumped = record.model_dump()
        assert set(dumped.keys()) == {
            "issue_number",
            "from_stage",
            "to_stage",
            "reason",
            "feedback_context",
            "timestamp",
        }
