"""Regression test for issue #6379.

Bug: ``_write_decision()`` in ``health_monitor_loop.py`` has no error
handling around the file-open/write call.  Any ``OSError`` (disk full,
permission denied, missing path after mkdir race) propagates uncaught.
Because ``_write_decision`` is called during the health-monitor decision
logic, a write failure aborts the entire health-monitor work cycle.

Expected behaviour after fix:
  - ``_write_decision()`` catches ``OSError``, logs a warning, and
    returns without raising.
  - The health monitor loop cycle continues even when a single decision
    write fails.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from health_monitor_loop import _write_decision  # noqa: E402


class TestWriteDecisionOSError:
    """_write_decision must not raise on OSError — it should log and return."""

    def test_write_decision_survives_permission_error(self, tmp_path: Path) -> None:
        """Simulate a permission error on file open.

        After fix, _write_decision should catch OSError and return None
        without raising.
        """
        decisions_dir = tmp_path / "decisions"
        record = {"decision_id": "adj-test0001", "action": "increase", "param": "max_quality_fix_attempts"}

        def _boom(*args, **kwargs):
            raise PermissionError("Permission denied: decisions.jsonl")

        # mkdir succeeds, but the file open raises PermissionError (an OSError subclass)
        with patch.object(Path, "open", _boom):
            # Current code: raises PermissionError (BUG — test is RED)
            # Fixed code: catches OSError, logs warning, returns None
            result = _write_decision(decisions_dir, record)

        # _write_decision should return None without raising
        assert result is None

    def test_write_decision_survives_oserror_disk_full(self, tmp_path: Path) -> None:
        """Simulate a disk-full OSError during write.

        After fix, _write_decision should catch OSError and return None.
        """
        decisions_dir = tmp_path / "decisions"
        record = {"decision_id": "adj-test0002", "action": "decrease"}

        def _boom(*args, **kwargs):
            raise OSError(28, "No space left on device")

        with patch.object(Path, "open", _boom):
            result = _write_decision(decisions_dir, record)

        assert result is None

    def test_write_decision_does_not_abort_caller(self, tmp_path: Path) -> None:
        """Verify that a failing _write_decision does not raise into the caller.

        This is the core acceptance criterion: the health monitor loop cycle
        must continue even when a single decision write fails.
        """
        decisions_dir = tmp_path / "decisions"
        record = {"decision_id": "adj-test0003", "action": "noop"}

        def _boom(*args, **kwargs):
            raise OSError(5, "I/O error")

        with patch.object(Path, "open", _boom):
            # If _write_decision raises, this pytest.raises will NOT catch it
            # (because we expect it NOT to raise).  The test fails if it raises.
            try:
                _write_decision(decisions_dir, record)
            except OSError:
                pytest.fail(
                    "_write_decision raised OSError instead of catching it — "
                    "health monitor loop cycle would be aborted (issue #6379)"
                )
