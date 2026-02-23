"""Tests for log.py."""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Generator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from log import JSONFormatter, setup_logging

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_hydraflow_logger() -> Generator[None, None, None]:
    """Clear the hydraflow logger's handlers before and after each test."""
    logger = logging.getLogger("hydraflow")
    logger.handlers.clear()
    yield
    for handler in logger.handlers[:]:
        handler.close()
    logger.handlers.clear()


def _make_record(
    msg: str = "hello",
    level: int = logging.INFO,
    name: str = "hydraflow",
) -> logging.LogRecord:
    """Create a minimal LogRecord for testing."""
    return logging.LogRecord(
        name=name,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    """Tests for JSONFormatter."""

    def test_format_produces_valid_json_with_expected_keys(self) -> None:
        record = _make_record("test message")
        output = JSONFormatter().format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "test message"
        assert parsed["logger"] == "hydraflow"
        assert "ts" in parsed

    def test_format_includes_exception_info(self) -> None:
        record = _make_record("boom")
        try:
            raise ValueError("kaboom")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()

        output = JSONFormatter().format(record)
        parsed = json.loads(output)

        assert "exception" in parsed
        assert "kaboom" in parsed["exception"]

    def test_format_includes_extra_fields_when_set(self) -> None:
        record = _make_record()
        record.issue = 42  # type: ignore[attr-defined]
        record.worker = "w-1"  # type: ignore[attr-defined]
        record.pr = 99  # type: ignore[attr-defined]
        record.phase = "plan"  # type: ignore[attr-defined]
        record.batch = "b-1"  # type: ignore[attr-defined]

        output = JSONFormatter().format(record)
        parsed = json.loads(output)

        assert parsed["issue"] == 42
        assert parsed["worker"] == "w-1"
        assert parsed["pr"] == 99
        assert parsed["phase"] == "plan"
        assert parsed["batch"] == "b-1"

    def test_format_omits_extra_fields_when_not_set(self) -> None:
        record = _make_record()
        output = JSONFormatter().format(record)
        parsed = json.loads(output)

        for key in ("issue", "worker", "pr", "phase", "batch"):
            assert key not in parsed


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """Tests for setup_logging()."""

    def test_returns_hydraflow_logger(self) -> None:
        logger = setup_logging()
        assert logger.name == "hydraflow"

    def test_json_output_uses_json_formatter(self) -> None:
        logger = setup_logging(json_output=True)
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_plain_output_uses_plain_formatter(self) -> None:
        logger = setup_logging(json_output=False)
        assert len(logger.handlers) == 1
        assert not isinstance(logger.handlers[0].formatter, JSONFormatter)

    def test_sets_correct_level(self) -> None:
        logger = setup_logging(level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_clears_existing_handlers(self) -> None:
        setup_logging()
        logger = setup_logging()
        assert len(logger.handlers) == 1

    def test_no_log_dir_parameter(self) -> None:
        """Regression guard: log_dir must not be a parameter."""
        sig = inspect.signature(setup_logging)
        assert "log_dir" not in sig.parameters


# ---------------------------------------------------------------------------
# setup_logging — log_file (RotatingFileHandler)
# ---------------------------------------------------------------------------


class TestSetupLoggingWithFile:
    """Tests for setup_logging() with the log_file parameter."""

    def test_log_file_adds_file_handler(self, tmp_path: Path) -> None:
        """When log_file is provided, a second handler should be added."""
        logger = setup_logging(log_file=tmp_path / "test.log")
        assert len(logger.handlers) == 2

    def test_log_file_handler_is_rotating(self, tmp_path: Path) -> None:
        """The file handler should be a RotatingFileHandler."""
        logger = setup_logging(log_file=tmp_path / "test.log")
        file_handlers = [
            h for h in logger.handlers if isinstance(h, RotatingFileHandler)
        ]
        assert len(file_handlers) == 1

    def test_log_file_handler_uses_json_formatter(self, tmp_path: Path) -> None:
        """The file handler should always use JSONFormatter."""
        logger = setup_logging(log_file=tmp_path / "test.log")
        file_handler = next(
            h for h in logger.handlers if isinstance(h, RotatingFileHandler)
        )
        assert isinstance(file_handler.formatter, JSONFormatter)

    def test_log_file_handler_uses_json_even_with_plain_console(
        self, tmp_path: Path
    ) -> None:
        """File handler uses JSON even when console is plain text."""
        logger = setup_logging(json_output=False, log_file=tmp_path / "test.log")
        file_handler = next(
            h for h in logger.handlers if isinstance(h, RotatingFileHandler)
        )
        assert isinstance(file_handler.formatter, JSONFormatter)

    def test_log_file_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories should be created if they don't exist."""
        log_file = tmp_path / "nested" / "dir" / "test.log"
        setup_logging(log_file=log_file)
        assert log_file.parent.exists()

    def test_log_file_rotation_config(self, tmp_path: Path) -> None:
        """Rotation should be configured for 10 MB max, 5 backups."""
        logger = setup_logging(log_file=tmp_path / "test.log")
        file_handler = next(
            h for h in logger.handlers if isinstance(h, RotatingFileHandler)
        )
        assert file_handler.maxBytes == 10 * 1024 * 1024
        assert file_handler.backupCount == 5

    def test_log_file_none_skips_file_handler(self) -> None:
        """When log_file is None, only the console handler is added."""
        logger = setup_logging(log_file=None)
        assert len(logger.handlers) == 1

    def test_log_file_writes_json(self, tmp_path: Path) -> None:
        """The file handler should write valid JSON log lines."""
        log_file = tmp_path / "test.log"
        logger = setup_logging(log_file=log_file)
        logger.info("test message")
        for handler in logger.handlers:
            handler.flush()
        content = log_file.read_text().strip()
        parsed = json.loads(content)
        assert parsed["msg"] == "test message"
        assert parsed["level"] == "INFO"

    def test_log_file_accepts_string_path(self, tmp_path: Path) -> None:
        """log_file should accept a string path in addition to Path."""
        logger = setup_logging(log_file=str(tmp_path / "test.log"))
        assert len(logger.handlers) == 2
