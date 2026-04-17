"""Regression test for issue #6446.

RetrospectiveQueue.load (line 71-72) catches exceptions from corrupt JSONL
lines but logs them via ``logger.debug(...)`` **without** ``exc_info=True``.
This means the actual parse error (Pydantic validation error, JSON syntax
error, etc.) is silently swallowed — operators cannot determine *why* a
queue line was skipped.

This test confirms that when a corrupt line triggers an exception during
load, the debug log record includes ``exc_info`` so the exception details
are visible in log output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retrospective_queue import RetrospectiveQueue  # noqa: E402


class TestIssue6446CorruptLineExcInfo:
    """load() must include exc_info when logging corrupt queue lines."""

    def test_corrupt_json_line_log_includes_exc_info(self, tmp_path: Path) -> None:
        """When a JSONL line is corrupt (invalid JSON), the debug log for
        the skipped line must include exc_info=True so the parse error
        is visible.

        BUG: Currently logger.debug(...) on line 72 omits exc_info,
        so the exception type and message are silently lost.
        """
        queue_file = tmp_path / "retro_queue.jsonl"
        queue_file.write_text("this is not valid json\n")

        queue = RetrospectiveQueue(queue_file)

        # Capture log records from the retrospective_queue logger
        target_logger = logging.getLogger("hydraflow.retrospective_queue")
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = records.append  # type: ignore[assignment]
        target_logger.addHandler(handler)
        original_level = target_logger.level
        target_logger.setLevel(logging.DEBUG)

        try:
            result = queue.load()
        finally:
            target_logger.removeHandler(handler)
            target_logger.setLevel(original_level)

        # The corrupt line should be skipped — result is empty
        assert result == [], f"Expected empty list for corrupt input, got {result}"

        # A debug log should have been emitted for the corrupt line
        debug_records = [r for r in records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1, (
            "Expected at least 1 DEBUG log for the corrupt queue line, "
            f"but got {len(debug_records)}."
        )

        # The critical assertion: exc_info must be present so the parse
        # error is diagnosable from logs alone
        corrupt_record = debug_records[0]
        assert (
            corrupt_record.exc_info is not None
            and corrupt_record.exc_info[1] is not None
        ), (
            "DEBUG log for corrupt queue line must include exc_info=True "
            "so the parse error (JSON syntax error, Pydantic validation error) "
            "is visible in production logs. Currently the exception is silently "
            "swallowed with no diagnostic information."
        )

    def test_pydantic_validation_error_log_includes_exc_info(
        self, tmp_path: Path
    ) -> None:
        """When a JSONL line is valid JSON but fails Pydantic validation,
        the debug log must also include exc_info.

        BUG: Same root cause — exc_info is missing from the debug call.
        """
        queue_file = tmp_path / "retro_queue.jsonl"
        # Valid JSON but invalid QueueItem (missing required 'kind' field)
        queue_file.write_text('{"id": "abc123"}\n')

        queue = RetrospectiveQueue(queue_file)

        target_logger = logging.getLogger("hydraflow.retrospective_queue")
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = records.append  # type: ignore[assignment]
        target_logger.addHandler(handler)
        original_level = target_logger.level
        target_logger.setLevel(logging.DEBUG)

        try:
            result = queue.load()
        finally:
            target_logger.removeHandler(handler)
            target_logger.setLevel(original_level)

        assert result == [], f"Expected empty list for invalid QueueItem, got {result}"

        debug_records = [r for r in records if r.levelno == logging.DEBUG]
        assert len(debug_records) >= 1, (
            "Expected at least 1 DEBUG log for the invalid queue line."
        )

        corrupt_record = debug_records[0]
        assert (
            corrupt_record.exc_info is not None
            and corrupt_record.exc_info[1] is not None
        ), (
            "DEBUG log for Pydantic validation failure must include exc_info=True "
            "so the specific validation error is visible in logs. Currently the "
            "exception details are silently lost."
        )
