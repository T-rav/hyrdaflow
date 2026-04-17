"""Regression test for issue #6418.

Bug: ``BaseBackgroundLoop._record_last_run`` wraps the timestamp write in
``except Exception: pass`` (line 244), silently swallowing disk-full,
permission, and other I/O errors.  ``_should_run_catchup`` similarly uses
``except Exception: return False`` (line 233) with no logging.

When these operations fail persistently, catchup detection is silently
broken — every restart triggers unnecessary API calls, and operators have
zero visibility into the root cause.

Expected behaviour after fix:
  - Timestamp write/read failures produce at least a ``logger.debug()`` entry.
  - The loop still never crashes on timestamp write/read failure.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------


class _StubLoop(BaseBackgroundLoop):
    """Minimal concrete subclass so we can test the base-class methods."""

    async def _do_work(self) -> dict[str, Any] | None:
        return None

    def _get_default_interval(self) -> int:
        return 600


def _make_loop(tmp_path: Path) -> _StubLoop:
    """Build a _StubLoop whose data_root points at *tmp_path*."""
    config = HydraFlowConfig(data_root=tmp_path, repo="owner/repo")
    deps = LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
    )
    return _StubLoop(worker_name="test_worker", config=config, deps=deps)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _caplog_at_debug(caplog):  # type: ignore[no-untyped-def]
    """Ensure caplog captures DEBUG-level records for the background-loop logger."""
    with caplog.at_level(logging.DEBUG, logger="hydraflow.base_background_loop"):
        yield caplog


# ---------------------------------------------------------------------------
# Tests for _record_last_run
# ---------------------------------------------------------------------------


class TestRecordLastRunLogsWriteFailures:
    """_record_last_run must log when the timestamp write fails."""

    def test_logs_debug_on_permission_error(
        self, tmp_path: Path, caplog: object
    ) -> None:
        """When write_text raises PermissionError, a debug log must appear.

        Current code: bare ``pass`` -> no log -> test FAILS (RED).
        """
        loop = _make_loop(tmp_path)

        # Make the memory directory exist but force write_text to fail
        ts_path = tmp_path / "memory" / ".test_worker_last_run"
        ts_path.parent.mkdir(parents=True, exist_ok=True)

        with (
            patch.object(
                Path, "write_text", side_effect=PermissionError("read-only filesystem")
            ),
            _caplog_at_debug(caplog) as log,  # type: ignore[arg-type]
        ):
            loop._record_last_run()

        # Key assertion: a debug-level log must have been emitted
        failure_logs = [
            r
            for r in log.records
            if r.levelno == logging.DEBUG and "test_worker" in r.message.lower()
        ]
        assert failure_logs, (
            "_record_last_run swallowed a PermissionError with no logging. "
            "Expected a debug-level log mentioning the worker name."
        )

    def test_logs_debug_on_oserror(self, tmp_path: Path, caplog: object) -> None:
        """When write_text raises OSError (disk full), a debug log must appear.

        Current code: bare ``pass`` -> no log -> test FAILS (RED).
        """
        loop = _make_loop(tmp_path)

        with (
            patch.object(
                Path, "write_text", side_effect=OSError("No space left on device")
            ),
            _caplog_at_debug(caplog) as log,  # type: ignore[arg-type]
        ):
            loop._record_last_run()

        failure_logs = [
            r
            for r in log.records
            if r.levelno == logging.DEBUG and "test_worker" in r.message.lower()
        ]
        assert failure_logs, (
            "_record_last_run swallowed an OSError with no logging. "
            "Expected a debug-level log mentioning the worker name."
        )

    def test_write_errors_never_propagate(self, tmp_path: Path) -> None:
        """Confirm that timestamp write errors are still swallowed (not raised).

        This test should be GREEN on current code — it documents the
        non-propagation contract that must be preserved by the fix.
        """
        loop = _make_loop(tmp_path)

        with patch.object(Path, "write_text", side_effect=PermissionError("read-only")):
            # Must not raise
            loop._record_last_run()


# ---------------------------------------------------------------------------
# Tests for _should_run_catchup
# ---------------------------------------------------------------------------


class TestShouldRunCatchupLogsReadFailures:
    """_should_run_catchup must log when the timestamp read fails."""

    def test_logs_debug_on_corrupt_timestamp(
        self, tmp_path: Path, caplog: object
    ) -> None:
        """When fromisoformat raises ValueError (corrupt file), a debug log must appear.

        Current code: bare ``return False`` -> no log -> test FAILS (RED).
        """
        loop = _make_loop(tmp_path)

        # Write a corrupt timestamp
        ts_path = tmp_path / "memory" / ".test_worker_last_run"
        ts_path.parent.mkdir(parents=True, exist_ok=True)
        ts_path.write_text("NOT-A-VALID-TIMESTAMP")

        with _caplog_at_debug(caplog) as log:  # type: ignore[arg-type]
            result = loop._should_run_catchup()

        # Should return False (no crash)
        assert result is False

        # Key assertion: a debug-level log must have been emitted
        failure_logs = [
            r
            for r in log.records
            if r.levelno == logging.DEBUG and "test_worker" in r.message.lower()
        ]
        assert failure_logs, (
            "_should_run_catchup swallowed a ValueError with no logging. "
            "Expected a debug-level log mentioning the worker name."
        )

    def test_logs_debug_on_permission_error(
        self, tmp_path: Path, caplog: object
    ) -> None:
        """When read_text raises PermissionError, a debug log must appear.

        Current code: bare ``return False`` -> no log -> test FAILS (RED).
        """
        loop = _make_loop(tmp_path)

        # Create the file so exists() returns True, then fail on read
        ts_path = tmp_path / "memory" / ".test_worker_last_run"
        ts_path.parent.mkdir(parents=True, exist_ok=True)
        ts_path.write_text("2026-01-01T00:00:00+00:00")

        with (
            patch.object(
                Path, "read_text", side_effect=PermissionError("no read access")
            ),
            _caplog_at_debug(caplog) as log,  # type: ignore[arg-type]
        ):
            result = loop._should_run_catchup()

        assert result is False

        failure_logs = [
            r
            for r in log.records
            if r.levelno == logging.DEBUG and "test_worker" in r.message.lower()
        ]
        assert failure_logs, (
            "_should_run_catchup swallowed a PermissionError with no logging. "
            "Expected a debug-level log mentioning the worker name."
        )

    def test_read_errors_never_propagate(self, tmp_path: Path) -> None:
        """Confirm that timestamp read errors are still swallowed (not raised).

        This test should be GREEN on current code — it documents the
        non-propagation contract that must be preserved by the fix.
        """
        loop = _make_loop(tmp_path)

        ts_path = tmp_path / "memory" / ".test_worker_last_run"
        ts_path.parent.mkdir(parents=True, exist_ok=True)
        ts_path.write_text("NOT-A-VALID-TIMESTAMP")

        # Must not raise
        result = loop._should_run_catchup()
        assert result is False
