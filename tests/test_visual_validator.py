"""Tests for visual validation flake mitigation and retry thresholds."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from models import (
    VisualFailureClass,
    VisualScreenResult,
    VisualScreenVerdict,
    VisualValidationReport,
)
from tests.helpers import ConfigFactory
from visual_validator import (
    VisualValidator,
    apply_thresholds,
    classify_failure,
    is_transient,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any):  # noqa: ANN202
    """Create a config with visual validation enabled and zero retry delay."""
    defaults = {
        "visual_validation_enabled": True,
        "visual_max_retries": 2,
        "visual_retry_delay": 0.0,
        "visual_warn_threshold": 0.05,
        "visual_fail_threshold": 0.15,
    }
    defaults.update(overrides)
    return ConfigFactory.create(**defaults)


# ---------------------------------------------------------------------------
# Unit tests: classify_failure
# ---------------------------------------------------------------------------


class TestClassifyFailure:
    def test_timeout_error_classified_as_timeout(self) -> None:
        error = TimeoutError("timed out")

        result = classify_failure(error)

        assert result == VisualFailureClass.TIMEOUT

    def test_connection_error_classified_as_infra(self) -> None:
        error = ConnectionError("connection refused")

        result = classify_failure(error)

        assert result == VisualFailureClass.INFRA_FAILURE

    def test_os_error_classified_as_infra(self) -> None:
        error = OSError("disk full")

        result = classify_failure(error)

        assert result == VisualFailureClass.INFRA_FAILURE

    def test_generic_error_classified_as_capture_error(self) -> None:
        error = RuntimeError("screenshot failed")

        result = classify_failure(error)

        assert result == VisualFailureClass.CAPTURE_ERROR

    def test_value_error_classified_as_capture_error(self) -> None:
        error = ValueError("bad data")

        result = classify_failure(error)

        assert result == VisualFailureClass.CAPTURE_ERROR


# ---------------------------------------------------------------------------
# Unit tests: apply_thresholds
# ---------------------------------------------------------------------------


class TestApplyThresholds:
    def test_below_warn_is_pass(self) -> None:
        verdict = apply_thresholds(0.01, warn_threshold=0.05, fail_threshold=0.15)

        assert verdict == VisualScreenVerdict.PASS

    def test_zero_diff_is_pass(self) -> None:
        verdict = apply_thresholds(0.0, warn_threshold=0.05, fail_threshold=0.15)

        assert verdict == VisualScreenVerdict.PASS

    def test_at_warn_threshold_is_warn(self) -> None:
        verdict = apply_thresholds(0.05, warn_threshold=0.05, fail_threshold=0.15)

        assert verdict == VisualScreenVerdict.WARN

    def test_between_warn_and_fail_is_warn(self) -> None:
        verdict = apply_thresholds(0.10, warn_threshold=0.05, fail_threshold=0.15)

        assert verdict == VisualScreenVerdict.WARN

    def test_at_fail_threshold_is_fail(self) -> None:
        verdict = apply_thresholds(0.15, warn_threshold=0.05, fail_threshold=0.15)

        assert verdict == VisualScreenVerdict.FAIL

    def test_above_fail_threshold_is_fail(self) -> None:
        verdict = apply_thresholds(0.50, warn_threshold=0.05, fail_threshold=0.15)

        assert verdict == VisualScreenVerdict.FAIL


# ---------------------------------------------------------------------------
# Unit tests: is_transient
# ---------------------------------------------------------------------------


class TestIsTransient:
    def test_infra_failure_is_transient(self) -> None:
        result = VisualScreenResult(
            screen_name="test",
            failure_class=VisualFailureClass.INFRA_FAILURE,
        )

        assert is_transient(result) is True

    def test_timeout_is_transient(self) -> None:
        result = VisualScreenResult(
            screen_name="test",
            failure_class=VisualFailureClass.TIMEOUT,
        )

        assert is_transient(result) is True

    def test_capture_error_is_transient(self) -> None:
        result = VisualScreenResult(
            screen_name="test",
            failure_class=VisualFailureClass.CAPTURE_ERROR,
        )

        assert is_transient(result) is True

    def test_visual_diff_is_not_transient(self) -> None:
        result = VisualScreenResult(
            screen_name="test",
            failure_class=VisualFailureClass.VISUAL_DIFF,
        )

        assert is_transient(result) is False

    def test_no_failure_class_is_not_transient(self) -> None:
        result = VisualScreenResult(screen_name="test")

        assert is_transient(result) is False


# ---------------------------------------------------------------------------
# Unit tests: VisualScreenResult model
# ---------------------------------------------------------------------------


class TestVisualScreenResult:
    def test_minimal_instantiation(self) -> None:
        result = VisualScreenResult(screen_name="homepage")

        assert result.screen_name == "homepage"
        assert result.diff_ratio == 0.0
        assert result.verdict == VisualScreenVerdict.PASS
        assert result.failure_class is None
        assert result.error == ""
        assert result.retries_used == 0

    def test_full_instantiation(self) -> None:
        result = VisualScreenResult(
            screen_name="dashboard",
            diff_ratio=0.12,
            verdict=VisualScreenVerdict.WARN,
            failure_class=VisualFailureClass.VISUAL_DIFF,
            error="pixel mismatch",
            retries_used=1,
        )

        assert result.screen_name == "dashboard"
        assert result.diff_ratio == 0.12
        assert result.verdict == VisualScreenVerdict.WARN
        assert result.failure_class == VisualFailureClass.VISUAL_DIFF
        assert result.error == "pixel mismatch"
        assert result.retries_used == 1


# ---------------------------------------------------------------------------
# Unit tests: VisualValidationReport model
# ---------------------------------------------------------------------------


class TestVisualValidationReport:
    def test_empty_report_defaults(self) -> None:
        report = VisualValidationReport()

        assert report.screens == []
        assert report.overall_verdict == VisualScreenVerdict.PASS
        assert report.total_retries == 0
        assert report.infra_failures == 0
        assert report.visual_diffs == 0
        assert report.has_failures is False
        assert report.has_warnings is False

    def test_has_failures_when_fail(self) -> None:
        report = VisualValidationReport(overall_verdict=VisualScreenVerdict.FAIL)

        assert report.has_failures is True
        assert report.has_warnings is True

    def test_has_warnings_when_warn(self) -> None:
        report = VisualValidationReport(overall_verdict=VisualScreenVerdict.WARN)

        assert report.has_failures is False
        assert report.has_warnings is True

    def test_format_summary_empty(self) -> None:
        report = VisualValidationReport()

        summary = report.format_summary()

        assert "Visual Validation Report" in summary
        assert "PASS" in summary

    def test_format_summary_with_screens(self) -> None:
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="login",
                    diff_ratio=0.02,
                    verdict=VisualScreenVerdict.PASS,
                ),
                VisualScreenResult(
                    screen_name="dashboard",
                    diff_ratio=0.20,
                    verdict=VisualScreenVerdict.FAIL,
                    failure_class=VisualFailureClass.VISUAL_DIFF,
                    retries_used=2,
                    error="large mismatch",
                ),
            ],
            overall_verdict=VisualScreenVerdict.FAIL,
            total_retries=2,
            visual_diffs=1,
        )

        summary = report.format_summary()

        assert "login" in summary
        assert "dashboard" in summary
        assert "FAIL" in summary
        assert "2 retries" in summary
        assert "large mismatch" in summary
        assert "visual_diff" in summary

    def test_format_summary_singular_retry(self) -> None:
        report = VisualValidationReport(
            screens=[
                VisualScreenResult(
                    screen_name="page",
                    diff_ratio=0.10,
                    verdict=VisualScreenVerdict.WARN,
                    retries_used=1,
                ),
            ],
            overall_verdict=VisualScreenVerdict.WARN,
            total_retries=1,
        )

        summary = report.format_summary()

        assert "(1 retry)" in summary
        assert "1 retries" not in summary


# ---------------------------------------------------------------------------
# Unit tests: Config thresholds
# ---------------------------------------------------------------------------


class TestVisualConfigFields:
    def test_default_values(self) -> None:
        config = ConfigFactory.create()

        assert config.visual_validation_enabled is True
        assert config.visual_max_retries == 2
        assert config.visual_retry_delay == 0.0  # test factory default
        assert config.visual_warn_threshold == 0.05
        assert config.visual_fail_threshold == 0.15

    def test_fail_threshold_must_exceed_warn(self) -> None:
        # Arrange / Act / Assert
        with pytest.raises(ValidationError, match="visual_fail_threshold"):
            ConfigFactory.create(
                visual_warn_threshold=0.10,
                visual_fail_threshold=0.10,
            )

    def test_fail_threshold_below_warn_rejected(self) -> None:
        # Arrange / Act / Assert
        with pytest.raises(ValidationError, match="visual_fail_threshold"):
            ConfigFactory.create(
                visual_warn_threshold=0.20,
                visual_fail_threshold=0.10,
            )

    def test_valid_custom_thresholds(self) -> None:
        config = ConfigFactory.create(
            visual_warn_threshold=0.01,
            visual_fail_threshold=0.02,
        )

        assert config.visual_warn_threshold == 0.01
        assert config.visual_fail_threshold == 0.02

    def test_env_override_visual_max_retries(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_VISUAL_MAX_RETRIES", "4")

        config = ConfigFactory.create()

        assert config.visual_max_retries == 4

    def test_env_override_visual_warn_threshold(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_VISUAL_WARN_THRESHOLD", "0.08")

        config = ConfigFactory.create()

        assert config.visual_warn_threshold == pytest.approx(0.08)

    def test_env_override_visual_fail_threshold(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_VISUAL_FAIL_THRESHOLD", "0.30")

        config = ConfigFactory.create()

        assert config.visual_fail_threshold == pytest.approx(0.30)

    def test_env_override_invalid_threshold_combination_reverts_fail_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should revert visual_fail_threshold to default when env overrides produce warn >= fail.

        The Pydantic field_validator only fires at model construction; env overrides use
        object.__setattr__ and bypass it.  _apply_env_overrides must enforce the invariant
        itself and revert to the default (0.15) when it would be violated.
        """
        # Arrange — warn=0.20 > fail=0.10 after env override
        monkeypatch.setenv("HYDRAFLOW_VISUAL_WARN_THRESHOLD", "0.20")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_FAIL_THRESHOLD", "0.10")

        config = ConfigFactory.create()

        # Assert — fail_threshold must be reverted so the invariant holds
        assert config.visual_fail_threshold > config.visual_warn_threshold

    def test_env_override_only_fail_bad_preserves_warn(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should preserve a valid warn override when only fail violates the invariant.

        When warn=0.02 is valid and fail=0.01 only causes a violation because
        fail < warn, the revert should only reset fail_threshold to 0.15 and
        leave the valid warn=0.02 intact.
        """
        # Arrange — warn=0.02 (valid), fail=0.01 (< warn → violates invariant)
        monkeypatch.setenv("HYDRAFLOW_VISUAL_WARN_THRESHOLD", "0.02")
        monkeypatch.setenv("HYDRAFLOW_VISUAL_FAIL_THRESHOLD", "0.01")

        config = ConfigFactory.create()

        # Assert — warn is preserved; fail is reverted to default (0.15 > 0.02)
        assert config.visual_warn_threshold == pytest.approx(0.02)
        assert config.visual_fail_threshold == pytest.approx(0.15)
        assert config.visual_fail_threshold > config.visual_warn_threshold

    def test_env_override_out_of_bounds_warn_is_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_VISUAL_WARN_THRESHOLD", "1.5")

        config = ConfigFactory.create()

        # Assert — invalid value is rejected; field stays at default
        assert config.visual_warn_threshold == pytest.approx(0.05)

    def test_env_override_visual_max_retries_above_le_is_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_VISUAL_MAX_RETRIES", "99")

        config = ConfigFactory.create()

        # Assert — out-of-bounds value is rejected; field stays at default
        assert config.visual_max_retries == 2

    def test_env_override_visual_max_retries_negative_is_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_VISUAL_MAX_RETRIES", "-1")

        config = ConfigFactory.create()

        # Assert — out-of-bounds value is rejected; field stays at default
        assert config.visual_max_retries == 2


# ---------------------------------------------------------------------------
# Integration tests: VisualValidator
# ---------------------------------------------------------------------------


class TestVisualValidatorEmptyScreens:
    @pytest.mark.asyncio
    async def test_empty_screens_returns_passing_report(self) -> None:
        config = _make_config()
        validator = VisualValidator(config)

        async def check_fn(name: str) -> VisualScreenResult:
            raise AssertionError("Should not be called")

        report = await validator.validate_screens([], check_fn)

        assert report.overall_verdict == VisualScreenVerdict.PASS
        assert report.screens == []
        assert report.total_retries == 0


class TestVisualValidatorPassingScreens:
    @pytest.mark.asyncio
    async def test_all_screens_pass(self) -> None:
        config = _make_config()
        validator = VisualValidator(config)

        async def check_fn(name: str) -> VisualScreenResult:
            return VisualScreenResult(screen_name=name, diff_ratio=0.01)

        report = await validator.validate_screens(["a", "b"], check_fn)

        assert report.overall_verdict == VisualScreenVerdict.PASS
        assert len(report.screens) == 2
        assert all(s.verdict == VisualScreenVerdict.PASS for s in report.screens)
        assert report.total_retries == 0


class TestVisualValidatorWarnScreen:
    @pytest.mark.asyncio
    async def test_warn_screen_produces_warn_overall(self) -> None:
        config = _make_config()
        validator = VisualValidator(config)

        async def check_fn(name: str) -> VisualScreenResult:
            ratio = 0.10 if name == "dashboard" else 0.01
            return VisualScreenResult(screen_name=name, diff_ratio=ratio)

        report = await validator.validate_screens(["login", "dashboard"], check_fn)

        assert report.overall_verdict == VisualScreenVerdict.WARN
        dashboard = next(s for s in report.screens if s.screen_name == "dashboard")
        assert dashboard.verdict == VisualScreenVerdict.WARN


class TestVisualValidatorFailScreen:
    @pytest.mark.asyncio
    async def test_fail_screen_produces_fail_overall(self) -> None:
        config = _make_config()
        validator = VisualValidator(config)

        async def check_fn(name: str) -> VisualScreenResult:
            return VisualScreenResult(screen_name=name, diff_ratio=0.25)

        report = await validator.validate_screens(["page"], check_fn)

        assert report.overall_verdict == VisualScreenVerdict.FAIL
        assert report.screens[0].verdict == VisualScreenVerdict.FAIL


class TestVisualValidatorRetryTransient:
    @pytest.mark.asyncio
    async def test_retries_on_timeout_then_succeeds(self) -> None:
        config = _make_config(visual_max_retries=2)
        validator = VisualValidator(config)
        call_count = 0

        async def check_fn(name: str) -> VisualScreenResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("timed out")
            return VisualScreenResult(screen_name=name, diff_ratio=0.01)

        report = await validator.validate_screens(["page"], check_fn)

        assert report.overall_verdict == VisualScreenVerdict.PASS
        assert report.total_retries == 1
        assert report.screens[0].retries_used == 1

    @pytest.mark.asyncio
    async def test_retries_exhausted_returns_fail(self) -> None:
        config = _make_config(visual_max_retries=2)
        validator = VisualValidator(config)

        async def check_fn(name: str) -> VisualScreenResult:
            raise ConnectionError("service down")

        report = await validator.validate_screens(["page"], check_fn)

        assert report.overall_verdict == VisualScreenVerdict.FAIL
        assert report.total_retries == 2
        assert report.screens[0].retries_used == 2
        assert report.screens[0].failure_class == VisualFailureClass.INFRA_FAILURE
        assert report.infra_failures == 1

    @pytest.mark.asyncio
    async def test_no_retry_for_visual_diff(self) -> None:
        config = _make_config(visual_max_retries=3)
        validator = VisualValidator(config)
        call_count = 0

        async def check_fn(name: str) -> VisualScreenResult:
            nonlocal call_count
            call_count += 1
            return VisualScreenResult(
                screen_name=name,
                diff_ratio=0.30,
                verdict=VisualScreenVerdict.FAIL,
                failure_class=VisualFailureClass.VISUAL_DIFF,
            )

        report = await validator.validate_screens(["page"], check_fn)

        assert call_count == 1  # No retries
        assert report.total_retries == 0
        assert report.visual_diffs == 1

    @pytest.mark.asyncio
    async def test_zero_max_retries_no_retry(self) -> None:
        config = _make_config(visual_max_retries=0)
        validator = VisualValidator(config)
        call_count = 0

        async def check_fn(name: str) -> VisualScreenResult:
            nonlocal call_count
            call_count += 1
            raise TimeoutError("timed out")

        report = await validator.validate_screens(["page"], check_fn)

        assert call_count == 1
        assert report.total_retries == 0
        assert report.screens[0].failure_class == VisualFailureClass.TIMEOUT

    @pytest.mark.asyncio
    async def test_retry_with_capture_error(self) -> None:
        config = _make_config(visual_max_retries=1)
        validator = VisualValidator(config)
        call_count = 0

        async def check_fn(name: str) -> VisualScreenResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("screenshot capture failed")
            return VisualScreenResult(screen_name=name, diff_ratio=0.0)

        report = await validator.validate_screens(["page"], check_fn)

        assert call_count == 2
        assert report.overall_verdict == VisualScreenVerdict.PASS
        assert report.total_retries == 1


class TestVisualValidatorMultipleScreens:
    @pytest.mark.asyncio
    async def test_mixed_verdicts_worst_case_wins(self) -> None:
        config = _make_config()
        validator = VisualValidator(config)
        ratios = {"pass_screen": 0.01, "warn_screen": 0.08, "fail_screen": 0.20}

        async def check_fn(name: str) -> VisualScreenResult:
            return VisualScreenResult(screen_name=name, diff_ratio=ratios[name])

        report = await validator.validate_screens(list(ratios.keys()), check_fn)

        assert report.overall_verdict == VisualScreenVerdict.FAIL
        verdicts = {s.screen_name: s.verdict for s in report.screens}
        assert verdicts["pass_screen"] == VisualScreenVerdict.PASS
        assert verdicts["warn_screen"] == VisualScreenVerdict.WARN
        assert verdicts["fail_screen"] == VisualScreenVerdict.FAIL

    @pytest.mark.asyncio
    async def test_infra_failure_counted_separately(self) -> None:
        config = _make_config(visual_max_retries=0)
        validator = VisualValidator(config)

        async def check_fn(name: str) -> VisualScreenResult:
            if name == "infra":
                raise ConnectionError("network down")
            return VisualScreenResult(
                screen_name=name,
                diff_ratio=0.20,
                verdict=VisualScreenVerdict.FAIL,
                failure_class=VisualFailureClass.VISUAL_DIFF,
            )

        report = await validator.validate_screens(["infra", "visual"], check_fn)

        assert report.infra_failures == 1
        assert report.visual_diffs == 1


class TestVisualValidatorReturnedResult:
    @pytest.mark.asyncio
    async def test_returned_infra_failure_triggers_retry(self) -> None:
        config = _make_config(visual_max_retries=1)
        validator = VisualValidator(config)
        call_count = 0

        async def check_fn(name: str) -> VisualScreenResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return VisualScreenResult(
                    screen_name=name,
                    failure_class=VisualFailureClass.INFRA_FAILURE,
                    verdict=VisualScreenVerdict.FAIL,
                    error="service unavailable",
                )
            return VisualScreenResult(screen_name=name, diff_ratio=0.02)

        report = await validator.validate_screens(["page"], check_fn)

        assert call_count == 2
        assert report.overall_verdict == VisualScreenVerdict.PASS
        assert report.total_retries == 1


# ---------------------------------------------------------------------------
# VisualFailureClass enum values
# ---------------------------------------------------------------------------


class TestVisualFailureClassEnum:
    def test_all_members_present(self) -> None:
        members = set(VisualFailureClass)

        assert VisualFailureClass.INFRA_FAILURE in members
        assert VisualFailureClass.VISUAL_DIFF in members
        assert VisualFailureClass.TIMEOUT in members
        assert VisualFailureClass.CAPTURE_ERROR in members
        assert len(members) == 4

    def test_string_values(self) -> None:
        assert VisualFailureClass.INFRA_FAILURE.value == "infra_failure"
        assert VisualFailureClass.VISUAL_DIFF.value == "visual_diff"
        assert VisualFailureClass.TIMEOUT.value == "timeout"
        assert VisualFailureClass.CAPTURE_ERROR.value == "capture_error"


# ---------------------------------------------------------------------------
# VisualScreenVerdict enum values
# ---------------------------------------------------------------------------


class TestVisualScreenVerdictEnum:
    def test_all_members_present(self) -> None:
        members = set(VisualScreenVerdict)
        assert len(members) == 3
        assert VisualScreenVerdict.PASS in members
        assert VisualScreenVerdict.WARN in members
        assert VisualScreenVerdict.FAIL in members
