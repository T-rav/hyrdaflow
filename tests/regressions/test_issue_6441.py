"""Regression test for issue #6441.

trace_rollup.write_phase_rollup swallows malformed-trace exception without
exc_info=True, making the actual parse error (JSON decode, Pydantic validation,
file read error) invisible in logs.

This test confirms that when a malformed subprocess trace file is encountered,
the warning log includes exc_info so engineers can see the stack trace.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from trace_rollup import write_phase_rollup  # noqa: E402


class TestIssue6441MalformedTraceExcInfoLogged:
    """write_phase_rollup must log exc_info when skipping malformed traces."""

    def test_malformed_trace_warning_includes_exc_info(self, tmp_path: Path) -> None:
        """When a subprocess trace file contains invalid JSON, the warning log
        for skipping it must include exc_info=True so the parse error is visible."""
        # Arrange — create a malformed subprocess trace file
        config = MagicMock()
        config.data_root = tmp_path

        run_dir = tmp_path / "traces" / "42" / "implement" / "run-1"
        run_dir.mkdir(parents=True)
        malformed_file = run_dir / "subprocess-0.json"
        malformed_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

        # Act — capture log records
        logger = logging.getLogger("hydraflow.trace_rollup")
        with _capture_log_records(logger) as records:
            result = write_phase_rollup(
                config=config, issue_number=42, phase="implement", run_id=1
            )

        # Assert — the function returns None (no valid traces)
        assert result is None

        # Assert — a warning was emitted for the malformed file
        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert len(warnings) == 1, (
            f"Expected 1 warning, got {len(warnings)}: {warnings}"
        )
        assert "malformed subprocess trace" in warnings[0].getMessage().lower()

        # Assert — the warning includes exception info (the bug: exc_info is missing)
        assert warnings[0].exc_info is not None, (
            "Warning for malformed trace must include exc_info so the parse error "
            "is visible in logs. Currently exc_info is None — the exception is swallowed."
        )
        assert warnings[0].exc_info[1] is not None, (
            "exc_info tuple must contain the actual exception instance"
        )


class _capture_log_records:
    """Context manager that captures LogRecord objects from a logger."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.records: list[logging.LogRecord] = []
        self._handler = logging.Handler()
        self._handler.emit = self.records.append  # type: ignore[assignment]

    def __enter__(self) -> list[logging.LogRecord]:
        self.logger.addHandler(self._handler)
        self._original_level = self.logger.level
        self.logger.setLevel(logging.DEBUG)
        return self.records

    def __exit__(self, *exc: object) -> None:
        self.logger.removeHandler(self._handler)
        self.logger.setLevel(self._original_level)
