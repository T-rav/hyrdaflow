"""Regression test for issue #6415.

Bug: ``capture_if_bug`` in ``exception_classify.py`` catches all exceptions
from ``sentry_sdk`` with a bare ``except Exception: pass`` (line 47-48).

When the Sentry SDK itself fails (import error, connection failure, invalid
DSN, SDK bug), the error is completely swallowed with no logging.  Operators
have no way to know Sentry is broken until they notice missing alerts.

Expected behaviour after fix:
  - Sentry SDK errors produce a ``logger.debug()`` log entry.
  - Application behaviour is unchanged (Sentry errors never propagate).

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from exception_classify import capture_if_bug


class TestCaptureIfBugLogsSentryFailures:
    """capture_if_bug must log when sentry_sdk raises internally."""

    def test_logs_debug_when_sentry_capture_exception_fails(
        self, caplog: object
    ) -> None:
        """When sentry_sdk.capture_exception raises, a debug log must appear.

        Current code: bare ``pass`` -> no log -> test FAILS (RED).
        """
        mock_sdk = MagicMock()
        mock_sdk.capture_exception.side_effect = RuntimeError("Sentry DSN invalid")

        with (
            patch.dict("sys.modules", {"sentry_sdk": mock_sdk}),
            caplog_at_debug(caplog) as log,  # type: ignore[arg-type]
        ):
            # Should not raise — Sentry errors must be swallowed
            capture_if_bug(TypeError("application bug"))

        # The key assertion: a debug-level log must have been emitted
        sentry_failure_logs = [
            r
            for r in log.records
            if r.levelno == logging.DEBUG and "sentry" in r.message.lower()
        ]
        assert sentry_failure_logs, (
            "capture_if_bug swallowed a Sentry SDK error with no logging. "
            "Expected a debug-level log mentioning 'sentry'."
        )

    def test_logs_debug_when_sentry_add_breadcrumb_fails(self, caplog: object) -> None:
        """When sentry_sdk.add_breadcrumb raises, a debug log must appear."""
        mock_sdk = MagicMock()
        mock_sdk.add_breadcrumb.side_effect = ConnectionError("Sentry unreachable")

        with (
            patch.dict("sys.modules", {"sentry_sdk": mock_sdk}),
            caplog_at_debug(caplog) as log,  # type: ignore[arg-type]
        ):
            capture_if_bug(RuntimeError("transient failure"))

        sentry_failure_logs = [
            r
            for r in log.records
            if r.levelno == logging.DEBUG and "sentry" in r.message.lower()
        ]
        assert sentry_failure_logs, (
            "capture_if_bug swallowed a Sentry SDK error with no logging. "
            "Expected a debug-level log mentioning 'sentry'."
        )

    def test_sentry_errors_never_propagate(self) -> None:
        """Confirm that Sentry SDK errors are still swallowed (not raised).

        This test should be GREEN on current code — it documents the
        non-propagation contract that must be preserved by the fix.
        """
        mock_sdk = MagicMock()
        mock_sdk.capture_exception.side_effect = RuntimeError("SDK exploded")

        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            # Must not raise
            capture_if_bug(TypeError("application bug"))


# -- helpers -----------------------------------------------------------------

import contextlib  # noqa: E402


@contextlib.contextmanager
def caplog_at_debug(caplog):  # type: ignore[no-untyped-def]
    """Ensure caplog captures DEBUG-level records for exception_classify."""
    with caplog.at_level(logging.DEBUG, logger="exception_classify"):
        yield caplog
