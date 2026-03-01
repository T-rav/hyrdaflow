"""Tests for src/visual_diff.py — visual regression diff engine."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from models import (
    FailureCategory,
    ScreenResult,
    ScreenVerdict,
    VisualReport,
)
from visual_diff import (
    _count_diff_bytes,
    _load_image_bytes,
    compare_screen,
    run_visual_diff,
    write_visual_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Minimal valid PNG: 8-byte header + 13-byte IHDR data (4-byte len, 4-byte type,
# 13-byte data, 4-byte CRC) + IEND chunk.
_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _make_png(width: int = 2, height: int = 2, body: bytes = b"") -> bytes:
    """Build a minimal PNG-like byte string with a valid IHDR."""
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr_len = struct.pack(">I", len(ihdr_data))
    ihdr_crc = b"\x00\x00\x00\x00"
    iend = b"\x00\x00\x00\x00IEND\xaeB`\x82"
    return _PNG_HEADER + ihdr_len + b"IHDR" + ihdr_data + ihdr_crc + body + iend


def _write_png(path: Path, width: int = 2, height: int = 2, body: bytes = b"") -> Path:
    """Write a minimal PNG to *path* and return the path."""
    path.write_bytes(_make_png(width, height, body))
    return path


# ---------------------------------------------------------------------------
# ScreenVerdict enum
# ---------------------------------------------------------------------------


class TestScreenVerdict:
    """Tests for the ScreenVerdict enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ScreenVerdict.PASS, "pass"),
            (ScreenVerdict.WARN, "warn"),
            (ScreenVerdict.FAIL, "fail"),
            (ScreenVerdict.ERROR, "error"),
        ],
    )
    def test_enum_values(self, member: ScreenVerdict, expected_value: str) -> None:
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(ScreenVerdict.PASS, str)

    def test_all_members_present(self) -> None:
        assert len(ScreenVerdict) == 4

    def test_lookup_by_value(self) -> None:
        assert ScreenVerdict("fail") is ScreenVerdict.FAIL


# ---------------------------------------------------------------------------
# FailureCategory enum
# ---------------------------------------------------------------------------


class TestFailureCategory:
    """Tests for the FailureCategory enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (FailureCategory.NONE, "none"),
            (FailureCategory.THRESHOLD_EXCEEDED, "threshold_exceeded"),
            (FailureCategory.MISSING_BASELINE, "missing_baseline"),
            (FailureCategory.IMAGE_LOAD_ERROR, "image_load_error"),
            (FailureCategory.SIZE_MISMATCH, "size_mismatch"),
            (FailureCategory.BUDGET_EXCEEDED, "budget_exceeded"),
        ],
    )
    def test_enum_values(self, member: FailureCategory, expected_value: str) -> None:
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(FailureCategory.NONE, str)

    def test_all_members_present(self) -> None:
        assert len(FailureCategory) == 6


# ---------------------------------------------------------------------------
# ScreenResult model
# ---------------------------------------------------------------------------


class TestScreenResult:
    """Tests for the ScreenResult model."""

    def test_minimal_instantiation(self) -> None:
        result = ScreenResult(
            screen_name="home",
            verdict=ScreenVerdict.PASS,
        )
        assert result.screen_name == "home"
        assert result.verdict == ScreenVerdict.PASS
        assert result.diff_ratio == 0.0
        assert result.changed_pixels == 0
        assert result.total_pixels == 0
        assert result.error_message == ""

    def test_full_instantiation(self) -> None:
        result = ScreenResult(
            screen_name="dashboard",
            verdict=ScreenVerdict.FAIL,
            diff_ratio=0.05,
            changed_pixels=500,
            total_pixels=10000,
            baseline_path="/a/baseline.png",
            candidate_path="/a/candidate.png",
            diff_path="/a/diff.png",
            artifact_bytes=1024,
            runtime_seconds=0.5,
            error_message="threshold exceeded",
        )
        assert result.diff_ratio == 0.05
        assert result.changed_pixels == 500
        assert result.artifact_bytes == 1024
        assert result.runtime_seconds == 0.5

    def test_model_dump(self) -> None:
        result = ScreenResult(
            screen_name="login",
            verdict=ScreenVerdict.WARN,
            diff_ratio=0.007,
        )
        data = result.model_dump()
        assert data["screen_name"] == "login"
        assert data["verdict"] == "warn"
        assert data["diff_ratio"] == 0.007


# ---------------------------------------------------------------------------
# VisualReport model
# ---------------------------------------------------------------------------


class TestVisualReport:
    """Tests for the VisualReport model."""

    def test_default_instantiation(self) -> None:
        report = VisualReport()
        assert report.version == "1.0"
        assert report.aggregate_verdict == ScreenVerdict.PASS
        assert report.screens == []
        assert report.total_screens == 0
        assert report.diff_threshold == 0.01
        assert report.warn_threshold == 0.005
        assert report.retry_count == 0
        assert report.failure_category == FailureCategory.NONE

    def test_is_pass_property(self) -> None:
        report = VisualReport(aggregate_verdict=ScreenVerdict.PASS)
        assert report.is_pass is True
        assert report.is_fail is False

    def test_is_fail_property_fail(self) -> None:
        report = VisualReport(aggregate_verdict=ScreenVerdict.FAIL)
        assert report.is_fail is True
        assert report.is_pass is False

    def test_is_fail_property_error(self) -> None:
        report = VisualReport(aggregate_verdict=ScreenVerdict.ERROR)
        assert report.is_fail is True
        assert report.is_pass is False

    def test_warn_is_neither_pass_nor_fail(self) -> None:
        report = VisualReport(aggregate_verdict=ScreenVerdict.WARN)
        assert report.is_pass is False
        assert report.is_fail is False

    def test_is_error_property(self) -> None:
        report = VisualReport(aggregate_verdict=ScreenVerdict.ERROR)
        assert report.is_error is True
        report_pass = VisualReport(aggregate_verdict=ScreenVerdict.PASS)
        assert report_pass.is_error is False
        report_fail = VisualReport(aggregate_verdict=ScreenVerdict.FAIL)
        assert report_fail.is_error is False

    def test_model_dump_serialization(self) -> None:
        report = VisualReport(
            aggregate_verdict=ScreenVerdict.PASS,
            total_screens=2,
            passed=2,
            diff_threshold=0.01,
        )
        data = report.model_dump()
        assert data["aggregate_verdict"] == "pass"
        assert data["total_screens"] == 2
        assert data["version"] == "1.0"


# ---------------------------------------------------------------------------
# _load_image_bytes
# ---------------------------------------------------------------------------


class TestLoadImageBytes:
    """Tests for the _load_image_bytes helper."""

    def test_valid_png(self, tmp_path: Path) -> None:
        png = _write_png(tmp_path / "test.png", width=10, height=20)
        result = _load_image_bytes(png)
        assert result is not None
        data, w, h = result
        assert w == 10
        assert h == 20
        assert len(data) > 0

    def test_non_png_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_bytes(b"not a png file")
        assert _load_image_bytes(path) is None

    def test_missing_file(self, tmp_path: Path) -> None:
        assert _load_image_bytes(tmp_path / "missing.png") is None

    def test_truncated_png(self, tmp_path: Path) -> None:
        path = tmp_path / "truncated.png"
        path.write_bytes(_PNG_HEADER + b"\x00")
        assert _load_image_bytes(path) is None


# ---------------------------------------------------------------------------
# _count_diff_bytes
# ---------------------------------------------------------------------------


class TestCountDiffBytes:
    """Tests for the _count_diff_bytes helper."""

    def test_identical_bytes(self) -> None:
        assert _count_diff_bytes(b"hello", b"hello") == 0

    def test_all_different(self) -> None:
        assert _count_diff_bytes(b"\x00\x00", b"\xff\xff") == 2

    def test_different_lengths(self) -> None:
        # 1 differing byte + 3 excess bytes in longer input.
        assert _count_diff_bytes(b"\x00", b"\xff\xaa\xbb\xcc") == 4

    def test_empty_inputs(self) -> None:
        assert _count_diff_bytes(b"", b"") == 0


# ---------------------------------------------------------------------------
# compare_screen
# ---------------------------------------------------------------------------


class TestCompareScreen:
    """Tests for the compare_screen function."""

    def test_identical_screens_pass(self, tmp_path: Path) -> None:
        baseline = _write_png(tmp_path / "baseline.png")
        candidate = _write_png(tmp_path / "candidate.png")
        result = compare_screen(
            "home",
            baseline,
            candidate,
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=5_000_000,
        )
        assert result.verdict == ScreenVerdict.PASS
        assert result.diff_ratio == 0.0
        assert result.screen_name == "home"
        assert result.runtime_seconds >= 0.0

    def test_missing_baseline_returns_error(self, tmp_path: Path) -> None:
        candidate = _write_png(tmp_path / "candidate.png")
        result = compare_screen(
            "home",
            tmp_path / "missing.png",
            candidate,
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=5_000_000,
        )
        assert result.verdict == ScreenVerdict.ERROR
        assert "baseline" in result.error_message.lower()

    def test_missing_candidate_returns_error(self, tmp_path: Path) -> None:
        baseline = _write_png(tmp_path / "baseline.png")
        result = compare_screen(
            "home",
            baseline,
            tmp_path / "missing.png",
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=5_000_000,
        )
        assert result.verdict == ScreenVerdict.ERROR
        assert "candidate" in result.error_message.lower()

    def test_size_mismatch_returns_fail(self, tmp_path: Path) -> None:
        baseline = _write_png(tmp_path / "baseline.png", width=10, height=10)
        candidate = _write_png(tmp_path / "candidate.png", width=20, height=20)
        result = compare_screen(
            "home",
            baseline,
            candidate,
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=5_000_000,
        )
        assert result.verdict == ScreenVerdict.FAIL
        assert result.diff_ratio == 1.0
        assert "size mismatch" in result.error_message.lower()

    def test_budget_exceeded_returns_error(self, tmp_path: Path) -> None:
        baseline = _write_png(tmp_path / "baseline.png")
        candidate = _write_png(tmp_path / "candidate.png")
        result = compare_screen(
            "home",
            baseline,
            candidate,
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=1,  # tiny budget
        )
        assert result.verdict == ScreenVerdict.ERROR
        assert "budget" in result.error_message.lower()

    def test_diff_above_threshold_fails(self, tmp_path: Path) -> None:
        baseline = _write_png(tmp_path / "baseline.png", body=b"\x00" * 100)
        candidate = _write_png(tmp_path / "candidate.png", body=b"\xff" * 100)
        result = compare_screen(
            "home",
            baseline,
            candidate,
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=5_000_000,
        )
        assert result.verdict == ScreenVerdict.FAIL
        assert result.diff_ratio > 0.0

    def test_diff_in_warn_range(self, tmp_path: Path) -> None:
        # Create images with small but detectable differences.
        body_a = b"\x00" * 200
        body_b = b"\x00" * 199 + b"\x01"
        baseline = _write_png(tmp_path / "baseline.png", body=body_a)
        candidate = _write_png(tmp_path / "candidate.png", body=body_b)
        result = compare_screen(
            "home",
            baseline,
            candidate,
            diff_threshold=0.5,
            warn_threshold=0.001,
            budget_bytes=5_000_000,
        )
        assert result.verdict == ScreenVerdict.WARN

    def test_records_artifact_bytes(self, tmp_path: Path) -> None:
        baseline = _write_png(tmp_path / "baseline.png")
        candidate = _write_png(tmp_path / "candidate.png")
        result = compare_screen(
            "home",
            baseline,
            candidate,
            diff_threshold=0.01,
            warn_threshold=0.005,
            budget_bytes=5_000_000,
        )
        assert result.artifact_bytes > 0


# ---------------------------------------------------------------------------
# run_visual_diff
# ---------------------------------------------------------------------------


class TestRunVisualDiff:
    """Tests for the run_visual_diff function."""

    def test_all_pass(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "screen1.png")
        _write_png(baseline_dir / "screen2.png")
        _write_png(candidate_dir / "screen1.png")
        _write_png(candidate_dir / "screen2.png")

        report = run_visual_diff(baseline_dir, candidate_dir)
        assert report.aggregate_verdict == ScreenVerdict.PASS
        assert report.total_screens == 2
        assert report.passed == 2
        assert report.warned == 0
        assert report.failed == 0
        assert report.errored == 0
        assert report.is_pass is True
        assert report.failure_category == FailureCategory.NONE
        assert report.generated_at != ""

    def test_one_fail(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "ok.png")
        _write_png(candidate_dir / "ok.png")
        _write_png(baseline_dir / "bad.png", body=b"\x00" * 100)
        _write_png(candidate_dir / "bad.png", body=b"\xff" * 100)

        report = run_visual_diff(baseline_dir, candidate_dir)
        assert report.aggregate_verdict == ScreenVerdict.FAIL
        assert report.is_fail is True
        assert report.failed >= 1
        assert report.failure_category == FailureCategory.THRESHOLD_EXCEEDED

    def test_error_takes_precedence(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "missing_candidate.png")
        # No matching candidate — triggers ERROR.

        report = run_visual_diff(baseline_dir, candidate_dir)
        assert report.aggregate_verdict == ScreenVerdict.ERROR
        assert report.errored >= 1
        assert report.is_fail is True

    def test_empty_baseline_dir(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()

        report = run_visual_diff(baseline_dir, candidate_dir)
        # No baseline PNGs → treated as ERROR so callers cannot silently pass
        # a misconfigured environment where screenshots were never captured.
        assert report.aggregate_verdict == ScreenVerdict.ERROR
        assert report.is_fail is True
        assert report.total_screens == 0
        assert report.failure_category == FailureCategory.MISSING_BASELINE

    def test_max_screens_limit(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        for i in range(10):
            _write_png(baseline_dir / f"screen{i:02d}.png")
            _write_png(candidate_dir / f"screen{i:02d}.png")

        report = run_visual_diff(
            baseline_dir,
            candidate_dir,
            max_screens=3,
        )
        assert report.total_screens == 3

    def test_telemetry_fields(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "s.png")
        _write_png(candidate_dir / "s.png")

        report = run_visual_diff(baseline_dir, candidate_dir)
        assert report.total_runtime_seconds >= 0.0
        assert report.total_artifact_bytes >= 0
        assert report.retry_count == 0
        assert report.diff_threshold == 0.01
        assert report.warn_threshold == 0.005

    def test_retry_count_propagated(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "s.png")
        _write_png(candidate_dir / "s.png")

        report = run_visual_diff(baseline_dir, candidate_dir, retry_count=3)
        assert report.retry_count == 3

    def test_custom_thresholds(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "s.png")
        _write_png(candidate_dir / "s.png")

        report = run_visual_diff(
            baseline_dir,
            candidate_dir,
            diff_threshold=0.05,
            warn_threshold=0.02,
        )
        assert report.diff_threshold == 0.05
        assert report.warn_threshold == 0.02

    def test_warn_aggregate(self, tmp_path: Path) -> None:
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        # Create a small diff that falls between warn and fail thresholds.
        body_a = b"\x00" * 200
        body_b = b"\x00" * 199 + b"\x01"
        _write_png(baseline_dir / "s.png", body=body_a)
        _write_png(candidate_dir / "s.png", body=body_b)

        report = run_visual_diff(
            baseline_dir,
            candidate_dir,
            diff_threshold=0.5,
            warn_threshold=0.001,
        )
        assert report.aggregate_verdict == ScreenVerdict.WARN
        assert report.warned >= 1

    def test_error_budget_exceeded_classification(self, tmp_path: Path) -> None:
        """ERROR from budget exceeded → failure_category = BUDGET_EXCEEDED."""
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        _write_png(baseline_dir / "s.png")
        _write_png(candidate_dir / "s.png")

        report = run_visual_diff(
            baseline_dir,
            candidate_dir,
            budget_bytes=1,  # forces budget-exceeded ERROR on every screen
        )
        assert report.aggregate_verdict == ScreenVerdict.ERROR
        assert report.failure_category == FailureCategory.BUDGET_EXCEEDED

    def test_error_missing_baseline_classification(self, tmp_path: Path) -> None:
        """ERROR from unreadable baseline → failure_category = MISSING_BASELINE."""
        baseline_dir = tmp_path / "baseline"
        candidate_dir = tmp_path / "candidate"
        baseline_dir.mkdir()
        candidate_dir.mkdir()
        # Write a file that has valid PNG header but is too short to parse.
        bad_baseline = baseline_dir / "s.png"
        bad_baseline.write_bytes(_PNG_HEADER + b"\x00")  # truncated, < 24 bytes
        _write_png(candidate_dir / "s.png")

        report = run_visual_diff(baseline_dir, candidate_dir)
        assert report.aggregate_verdict == ScreenVerdict.ERROR
        assert report.failure_category == FailureCategory.MISSING_BASELINE


# ---------------------------------------------------------------------------
# write_visual_report
# ---------------------------------------------------------------------------


class TestWriteVisualReport:
    """Tests for the write_visual_report function."""

    def test_creates_file(self, tmp_path: Path) -> None:
        report = VisualReport(
            aggregate_verdict=ScreenVerdict.PASS,
            total_screens=1,
            passed=1,
        )
        output = tmp_path / "reports" / "visual_report.json"
        result_path = write_visual_report(report, output)
        assert result_path == output
        assert output.exists()

    def test_valid_json(self, tmp_path: Path) -> None:
        report = VisualReport(
            aggregate_verdict=ScreenVerdict.FAIL,
            total_screens=2,
            failed=1,
            passed=1,
            screens=[
                ScreenResult(
                    screen_name="home",
                    verdict=ScreenVerdict.PASS,
                ),
                ScreenResult(
                    screen_name="login",
                    verdict=ScreenVerdict.FAIL,
                    diff_ratio=0.05,
                ),
            ],
        )
        output = tmp_path / "visual_report.json"
        write_visual_report(report, output)
        data = json.loads(output.read_text())
        assert data["aggregate_verdict"] == "fail"
        assert len(data["screens"]) == 2
        assert data["screens"][0]["screen_name"] == "home"
        assert data["screens"][1]["diff_ratio"] == 0.05

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        report = VisualReport()
        output = tmp_path / "a" / "b" / "c" / "report.json"
        write_visual_report(report, output)
        assert output.exists()


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestVisualValidationConfig:
    """Tests for visual validation config fields."""

    def test_defaults(self, tmp_path: Path) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.visual_validation_enabled is False
        assert cfg.visual_diff_threshold == 0.01
        assert cfg.visual_warn_threshold == 0.005
        assert cfg.visual_max_screens == 20
        assert cfg.visual_per_screen_budget_bytes == 5_000_000

    def test_visual_reports_dir(self, tmp_path: Path) -> None:
        from config import HydraFlowConfig

        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.visual_reports_dir == cfg.data_root / "visual-reports"

    def test_env_override_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_VISUAL_VALIDATION_ENABLED", "true")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.visual_validation_enabled is True

    def test_env_override_diff_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_VISUAL_DIFF_THRESHOLD", "0.05")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.visual_diff_threshold == 0.05

    def test_env_override_max_screens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_VISUAL_MAX_SCREENS", "50")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.visual_max_screens == 50

    def test_env_override_budget_bytes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config import HydraFlowConfig

        monkeypatch.setenv("HYDRAFLOW_VISUAL_PER_SCREEN_BUDGET_BYTES", "1000000")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.visual_per_screen_budget_bytes == 1_000_000

    def test_threshold_validation_bounds(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                visual_diff_threshold=1.5,
            )

    def test_max_screens_min_bound(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from config import HydraFlowConfig

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                visual_max_screens=0,
            )

    def test_warn_threshold_must_be_less_than_diff_threshold(
        self, tmp_path: Path
    ) -> None:
        from pydantic import ValidationError

        from config import HydraFlowConfig

        # warn == diff → WARN verdict is unreachable, must be rejected.
        with pytest.raises(ValidationError, match="strictly less than"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                visual_warn_threshold=0.01,
                visual_diff_threshold=0.01,
            )

        # warn > diff → also invalid.
        with pytest.raises(ValidationError, match="strictly less than"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                visual_warn_threshold=0.05,
                visual_diff_threshold=0.01,
            )
