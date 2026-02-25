"""Tests for log_context.py — log injection utilities."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


from log_context import load_runtime_logs, truncate_log
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

    def test_truncation_when_marker_exceeds_budget(self) -> None:
        """When max_chars is tiny, output is a clipped marker."""
        text = "x" * 500
        result = truncate_log(text, max_chars=10)
        assert len(result) == 10
        assert result == "[Log trunc"


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

    def test_returns_empty_on_oserror(self, tmp_path: Path) -> None:
        """OSError reading the log file returns empty string."""
        log_dir = tmp_path / ".hydraflow" / "logs"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "hydraflow.log"
        log_file.write_text("some content")

        config = ConfigFactory.create(
            inject_runtime_logs=True,
            repo_root=tmp_path,
        )
        with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
            assert load_runtime_logs(config) == ""
