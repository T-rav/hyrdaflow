"""Regression test for issue #6696.

Bug: HarnessInsightStore.load_recent() catches bare ``Exception`` on malformed
JSONL lines and logs a warning, but does NOT include ``exc_info=True``.  This
means the Pydantic ValidationError detail (which field failed, what the actual
value was) is silently dropped from logs — identical class of bug to #6627.

Additionally, the ``except Exception`` clause is too broad; it should be
narrowed to ``(json.JSONDecodeError, ValueError, ValidationError)``.

These tests assert that the warning log records carry ``exc_info`` so that the
full traceback appears in structured logging output.  They will FAIL (RED)
against the current code because ``exc_info=True`` is missing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_insights import HarnessInsightStore


class TestIssue6696ExcInfoOnMalformedHarnessRecords:
    """Warning logs for malformed harness records must include exc_info."""

    def _make_store(self, tmp_path: Path) -> HarnessInsightStore:
        """Create a minimal HarnessInsightStore pointing at *tmp_path*."""
        return HarnessInsightStore(tmp_path)

    @pytest.mark.xfail(
        reason="Regression for issue #6696 — fix not yet landed", strict=False
    )
    def test_load_recent_includes_exc_info_on_malformed_line(
        self, tmp_path: Path, caplog: logging.LogRecord
    ) -> None:
        """load_recent() should pass exc_info=True when logging a malformed record.

        Currently FAILS because line 266 omits ``exc_info=True``.
        """
        failures = tmp_path / "harness_failures.jsonl"
        # Write a line that is valid JSON but missing required fields so
        # Pydantic validation raises a ValidationError.
        failures.write_text('{"not_a_valid_field": true}\n')

        store = self._make_store(tmp_path)

        with caplog.at_level(logging.DEBUG, logger="hydraflow.harness_insights"):
            result = store.load_recent(n=10)

        # The malformed line is skipped — empty list returned.
        assert result == []

        # A warning should have been emitted for the malformed line.
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "Expected at least one warning about the malformed record"
        )

        # BUG: exc_info is not set, so the Pydantic ValidationError traceback
        # is lost.  The fix should add ``exc_info=True`` to the logger.warning
        # call so that ``record.exc_info`` is a non-None tuple.
        malformed_warning = warning_records[0]
        assert malformed_warning.exc_info is not None, (
            "logger.warning() was called without exc_info=True — "
            "the Pydantic ValidationError traceback is lost (issue #6696)"
        )
        # exc_info should be a (type, value, traceback) tuple
        assert malformed_warning.exc_info[0] is not None, (
            "exc_info tuple has None exception type — "
            "expected the Pydantic ValidationError class"
        )

    @pytest.mark.xfail(
        reason="Regression for issue #6696 — fix not yet landed", strict=False
    )
    def test_unexpected_exception_type_is_not_swallowed(self, tmp_path: Path) -> None:
        """An unexpected exception (e.g. OSError) should NOT be caught.

        The current code catches bare ``Exception``, silently swallowing
        errors that are *not* parse-related.  After the fix, only
        json.JSONDecodeError, ValueError, and ValidationError should be
        caught; anything else should propagate.

        Currently FAILS because ``except Exception`` catches everything.
        """
        failures = tmp_path / "harness_failures.jsonl"
        # Write a valid-looking line so we get into the parse loop.
        failures.write_text('{"issue_number": 1}\n')

        store = self._make_store(tmp_path)

        # Patch FailureRecord.model_validate_json to raise an unexpected error
        # (e.g. an OSError that should NOT be caught by the handler).
        with patch(
            "harness_insights.FailureRecord.model_validate_json",
            side_effect=OSError("disk on fire"),
        ):
            # After the fix, OSError should propagate because it's not a
            # parse error. The current buggy code swallows it.
            try:
                store.load_recent(n=10)
                swallowed = True
            except OSError:
                swallowed = False

        assert not swallowed, (
            "OSError was silently swallowed by 'except Exception' — "
            "only parse errors should be caught (issue #6696)"
        )
