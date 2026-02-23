"""Tests for log_context.py — log injection utilities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


from log_context import load_runtime_logs, parse_error_summary, truncate_log
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# truncate_log
# ---------------------------------------------------------------------------


class TestTruncateLog:
    """Tests for truncate_log()."""

    def test_no_truncation_under_limit(self) -> None:
        """Short text is returned unchanged."""
        text = "line 1\nline 2\nline 3"
        result = truncate_log(text, max_chars=1000)
        assert result == text

    def test_text_at_exact_limit_not_truncated(self) -> None:
        """Text exactly at the limit is returned unchanged."""
        text = "x" * 100
        result = truncate_log(text, max_chars=100)
        assert result == text

    def test_truncation_keeps_tail(self) -> None:
        """Long text is truncated from the start, keeping the tail."""
        text = "A" * 500 + "TAIL"
        result = truncate_log(text, max_chars=100)
        assert result.endswith("TAIL")
        assert len(result) <= 100

    def test_truncation_marker_present(self) -> None:
        """Truncated output starts with a marker."""
        text = "x" * 500
        result = truncate_log(text, max_chars=100)
        assert result.startswith("[Log truncated")


# ---------------------------------------------------------------------------
# load_runtime_logs
# ---------------------------------------------------------------------------


class TestLoadRuntimeLogs:
    """Tests for load_runtime_logs()."""

    def test_returns_empty_when_disabled(self, tmp_path: Path) -> None:
        """Returns empty string when inject_runtime_logs is False."""
        config = ConfigFactory.create(
            inject_runtime_logs=False,
            repo_root=tmp_path,
        )
        assert load_runtime_logs(config) == ""

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        """Returns empty string when log file doesn't exist."""
        config = ConfigFactory.create(
            inject_runtime_logs=True,
            repo_root=tmp_path,
        )
        assert load_runtime_logs(config) == ""

    def test_returns_tail_of_log(self, tmp_path: Path) -> None:
        """Returns the log content when file exists and feature is enabled."""
        log_dir = tmp_path / ".hydraflow" / "logs"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "hydraflow.log"
        log_file.write_text("line 1\nline 2\nline 3\n")

        config = ConfigFactory.create(
            inject_runtime_logs=True,
            repo_root=tmp_path,
        )
        result = load_runtime_logs(config)
        assert "line 1" in result
        assert "line 3" in result

    def test_truncates_at_max_chars(self, tmp_path: Path) -> None:
        """Large log is truncated to max_runtime_log_chars."""
        log_dir = tmp_path / ".hydraflow" / "logs"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "hydraflow.log"
        log_file.write_text("x" * 50_000)

        config = ConfigFactory.create(
            inject_runtime_logs=True,
            max_runtime_log_chars=1_000,
            repo_root=tmp_path,
        )
        result = load_runtime_logs(config)
        assert len(result) <= 1_000
        assert result.startswith("[Log truncated")

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        """Empty (or whitespace-only) file returns empty string."""
        log_dir = tmp_path / ".hydraflow" / "logs"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "hydraflow.log"
        log_file.write_text("   \n  \n")

        config = ConfigFactory.create(
            inject_runtime_logs=True,
            repo_root=tmp_path,
        )
        assert load_runtime_logs(config) == ""


# ---------------------------------------------------------------------------
# parse_error_summary
# ---------------------------------------------------------------------------


class TestParseErrorSummary:
    """Tests for parse_error_summary()."""

    def test_extracts_error_lines(self) -> None:
        """Lines containing ERROR are extracted."""
        log = "INFO: all good\n2024-01-01 ERROR: disk full\nDEBUG: trace\n"
        result = parse_error_summary(log)
        assert "ERROR: disk full" in result
        assert "INFO" not in result

    def test_extracts_exception_lines(self) -> None:
        """Lines containing EXCEPTION are extracted."""
        log = "INFO: ok\nFatal EXCEPTION in handler\nDEBUG: done\n"
        result = parse_error_summary(log)
        assert "EXCEPTION" in result

    def test_deduplicates_errors(self) -> None:
        """Repeated error lines produce a single entry."""
        log = "ERROR: timeout\nERROR: timeout\nERROR: timeout\n"
        result = parse_error_summary(log)
        assert result.count("ERROR: timeout") == 1

    def test_returns_empty_for_no_errors(self) -> None:
        """Clean log returns empty string."""
        log = "INFO: all good\nDEBUG: trace\n"
        result = parse_error_summary(log)
        assert result == ""

    def test_returns_empty_for_empty_input(self) -> None:
        """Empty input returns empty string."""
        assert parse_error_summary("") == ""
