"""Tests for models — validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import (
    CodeScanningAlert,
    HITLResult,
    LoopResult,
    PRInfo,
    ReviewResult,
    WorkerResult,
)
from tests.conftest import ReviewResultFactory, WorkerResultFactory


class TestWorkerResultValidators:
    """Tests for WorkerResult field constraints and descriptions."""

    def test_duration_seconds_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="duration_seconds"):
            WorkerResultFactory.create(
                use_defaults=True, issue_number=1, branch="b", duration_seconds=-1.0
            )

    def test_commits_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="commits"):
            WorkerResultFactory.create(
                use_defaults=True, issue_number=1, branch="b", commits=-1
            )

    def test_quality_fix_attempts_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="quality_fix_attempts"):
            WorkerResultFactory.create(
                use_defaults=True,
                issue_number=1,
                branch="b",
                quality_fix_attempts=-1,
            )

    def test_pre_quality_review_attempts_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="pre_quality_review_attempts"):
            WorkerResultFactory.create(
                use_defaults=True,
                issue_number=1,
                branch="b",
                pre_quality_review_attempts=-1,
            )

    def test_ge0_fields_accept_zero(self) -> None:
        result = WorkerResultFactory.create(
            use_defaults=True,
            issue_number=1,
            branch="b",
            duration_seconds=0.0,
            commits=0,
            quality_fix_attempts=0,
            pre_quality_review_attempts=0,
        )
        assert result.duration_seconds == pytest.approx(0.0)
        assert result.commits == 0
        assert result.quality_fix_attempts == 0
        assert result.pre_quality_review_attempts == 0

    def test_field_descriptions_present(self) -> None:
        fields = WorkerResult.model_fields
        for name, info in fields.items():
            assert info.description, f"WorkerResult.{name} missing description"


class TestHITLResultValidators:
    """Tests for HITLResult field constraints and descriptions."""

    def test_duration_seconds_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="duration_seconds"):
            HITLResult(issue_number=1, duration_seconds=-1.0)

    def test_duration_seconds_accepts_zero(self) -> None:
        result = HITLResult(issue_number=1, duration_seconds=0.0)
        assert result.duration_seconds == pytest.approx(0.0)

    def test_field_descriptions_present(self) -> None:
        fields = HITLResult.model_fields
        for name, info in fields.items():
            assert info.description, f"HITLResult.{name} missing description"


class TestReviewResultValidators:
    """Tests for ReviewResult field constraints and descriptions."""

    def test_duration_seconds_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="duration_seconds"):
            ReviewResultFactory.create(
                pr_number=1, issue_number=1, duration_seconds=-1.0
            )

    def test_ci_fix_attempts_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="ci_fix_attempts"):
            ReviewResultFactory.create(pr_number=1, issue_number=1, ci_fix_attempts=-1)

    def test_ge0_fields_accept_zero(self) -> None:
        result = ReviewResultFactory.create(
            pr_number=1, issue_number=1, duration_seconds=0.0, ci_fix_attempts=0
        )
        assert result.duration_seconds == pytest.approx(0.0)
        assert result.ci_fix_attempts == 0

    def test_field_descriptions_present(self) -> None:
        fields = ReviewResult.model_fields
        for name, info in fields.items():
            assert info.description, f"ReviewResult.{name} missing description"


class TestPRInfoDescriptions:
    """Tests for PRInfo field descriptions."""

    def test_field_descriptions_present(self) -> None:
        fields = PRInfo.model_fields
        for name, info in fields.items():
            assert info.description, f"PRInfo.{name} missing description"


# ---------------------------------------------------------------------------
# LoopResult
# ---------------------------------------------------------------------------


class TestLoopResult:
    """Tests for the LoopResult dataclass."""

    def test_loop_result_defaults_attempts_to_zero(self) -> None:
        result = LoopResult(passed=True, summary="OK")
        assert result.passed is True
        assert result.summary == "OK"
        assert result.attempts == 0

    def test_with_attempts(self) -> None:
        result = LoopResult(passed=False, summary="failed", attempts=3)
        assert result.passed is False
        assert result.summary == "failed"
        assert result.attempts == 3

    def test_loop_result_is_immutable(self) -> None:
        result = LoopResult(passed=True, summary="OK")
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]

    def test_loop_result_equal_when_fields_match(self) -> None:
        a = LoopResult(passed=True, summary="OK", attempts=1)
        b = LoopResult(passed=True, summary="OK", attempts=1)
        assert a == b

    def test_loop_result_not_equal_when_passed_differs(self) -> None:
        a = LoopResult(passed=True, summary="OK")
        b = LoopResult(passed=False, summary="OK")
        assert a != b


# ---------------------------------------------------------------------------
# CodeScanningAlert
# ---------------------------------------------------------------------------


class TestCodeScanningAlert:
    """Tests for the CodeScanningAlert model."""

    def test_construct_with_all_fields(self):
        alert = CodeScanningAlert(
            number=1,
            severity="error",
            security_severity="high",
            path="src/db.js",
            start_line=42,
            rule="js/sql-injection",
            message="SQL injection vulnerability",
        )
        assert alert.number == 1
        assert alert.severity == "error"
        assert alert.security_severity == "high"
        assert alert.path == "src/db.js"
        assert alert.start_line == 42
        assert alert.rule == "js/sql-injection"
        assert alert.message == "SQL injection vulnerability"

    def test_construct_with_defaults(self):
        alert = CodeScanningAlert()
        assert alert.number is None
        assert alert.severity is None
        assert alert.security_severity is None
        assert alert.path is None
        assert alert.start_line is None
        assert alert.rule is None
        assert alert.message is None

    def test_model_validate_from_dict(self):
        raw = {
            "number": 3,
            "severity": "warning",
            "path": "foo.py",
            "start_line": 10,
            "rule": "py/unused-import",
            "message": "Unused import",
        }
        alert = CodeScanningAlert.model_validate(raw)
        assert alert.number == 3
        assert alert.path == "foo.py"
        assert alert.security_severity is None

    def test_frozen_immutability(self):
        alert = CodeScanningAlert(severity="error")
        with pytest.raises(ValidationError):
            alert.severity = "warning"  # type: ignore[misc]

    def test_ignores_unknown_fields(self):
        raw = {"severity": "error", "extra_field": "ignored"}
        alert = CodeScanningAlert.model_validate(raw)
        assert alert.severity == "error"
        assert not hasattr(alert, "extra_field")
