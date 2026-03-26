"""Tests for Sentry integration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Create a mock sentry_sdk module so tests work even when sentry-sdk
# is not installed in the test environment.
_mock_sentry = MagicMock()


@pytest.fixture(autouse=True)
def _ensure_sentry_module():
    """Inject a mock sentry_sdk into sys.modules for all tests."""
    had = "sentry_sdk" in sys.modules
    original = sys.modules.get("sentry_sdk")
    sys.modules["sentry_sdk"] = _mock_sentry

    # Also need sub-modules for the integrations
    sys.modules["sentry_sdk.integrations"] = MagicMock()
    sys.modules["sentry_sdk.integrations.fastapi"] = MagicMock()
    sys.modules["sentry_sdk.integrations.logging"] = MagicMock()

    _mock_sentry.reset_mock()
    yield
    if had:
        sys.modules["sentry_sdk"] = original
    else:
        sys.modules.pop("sentry_sdk", None)
    sys.modules.pop("sentry_sdk.integrations", None)
    sys.modules.pop("sentry_sdk.integrations.fastapi", None)
    sys.modules.pop("sentry_sdk.integrations.logging", None)


class TestSentryInit:
    """Tests for _init_sentry in server.py."""

    def test_noop_when_dsn_empty(self) -> None:
        """Should not call sentry_sdk.init when SENTRY_DSN is empty."""
        # Force re-import of server to pick up the mock
        sys.modules.pop("server", None)
        with patch.dict("os.environ", {"SENTRY_DSN": ""}, clear=False):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry()
            _mock_sentry.init.assert_not_called()

    def test_initializes_when_dsn_set(self) -> None:
        """Should call sentry_sdk.init with the DSN."""
        sys.modules.pop("server", None)
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry()
            _mock_sentry.init.assert_called_once()
            call_kwargs = _mock_sentry.init.call_args[1]
            assert call_kwargs["dsn"] == "https://key@sentry.io/123"


class TestScrubSensitiveData:
    """Tests for the before_send scrubber."""

    def test_scrubs_github_token(self) -> None:
        """Should redact ghp_ tokens from event data."""
        sys.modules.pop("server", None)
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry()
            before_send = _mock_sentry.init.call_args[1]["before_send"]

        event = {"message": "Token is ghp_abcdefghijklmnopqrstuvwxyz0123456789"}
        scrubbed = before_send(event, {})
        assert "ghp_" not in scrubbed["message"]
        assert "[REDACTED]" in scrubbed["message"]

    def test_scrubs_nested_dicts(self) -> None:
        """Should scrub tokens in nested structures."""
        sys.modules.pop("server", None)
        with patch.dict(
            "os.environ", {"SENTRY_DSN": "https://key@sentry.io/123"}, clear=False
        ):
            from server import _init_sentry

            _mock_sentry.init.reset_mock()
            _init_sentry()
            before_send = _mock_sentry.init.call_args[1]["before_send"]

        event = {"extra": {"token": "Bearer eyJhbGciOiJSUzI1NiJ9.test"}}
        scrubbed = before_send(event, {})
        assert "eyJ" not in str(scrubbed)


class TestCaptureIfBug:
    """Tests for capture_if_bug helper."""

    def test_captures_type_error(self) -> None:
        """TypeError should be sent to Sentry."""
        sys.modules.pop("phase_utils", None)
        from phase_utils import capture_if_bug

        _mock_sentry.capture_exception.reset_mock()
        capture_if_bug(TypeError("bad arg"))
        _mock_sentry.capture_exception.assert_called_once()

    def test_skips_runtime_error(self) -> None:
        """RuntimeError (transient) should become a breadcrumb, not a capture."""
        sys.modules.pop("phase_utils", None)
        from phase_utils import capture_if_bug

        _mock_sentry.capture_exception.reset_mock()
        _mock_sentry.add_breadcrumb.reset_mock()
        capture_if_bug(RuntimeError("network timeout"))
        _mock_sentry.capture_exception.assert_not_called()
        _mock_sentry.add_breadcrumb.assert_called_once()


class TestSentryTransactionHelper:
    """Tests for _sentry_transaction context manager in phase_utils."""

    def test_noop_when_sentry_not_available(self) -> None:
        """Should yield without error when sentry_sdk is not importable."""
        # Temporarily hide sentry_sdk from sys.modules
        sys.modules.pop("phase_utils", None)
        original = sys.modules.pop("sentry_sdk", None)
        try:
            from phase_utils import _sentry_transaction

            with _sentry_transaction("test.op", "test:name"):
                pass  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_starts_transaction_when_sentry_available(self) -> None:
        """Should call start_transaction when sentry_sdk is available."""
        sys.modules.pop("phase_utils", None)
        # Set up mock transaction context manager
        mock_txn = MagicMock()
        mock_txn.__enter__ = MagicMock(return_value=mock_txn)
        mock_txn.__exit__ = MagicMock(return_value=False)
        _mock_sentry.start_transaction.return_value = mock_txn
        _mock_sentry.start_transaction.reset_mock()

        from phase_utils import _sentry_transaction

        with _sentry_transaction("test.op", "test:name"):
            pass

        _mock_sentry.start_transaction.assert_called_once_with(
            op="test.op", name="test:name"
        )

    def test_passes_op_and_name_to_transaction(self) -> None:
        """Should pass op and name arguments through to start_transaction."""
        sys.modules.pop("phase_utils", None)
        mock_txn = MagicMock()
        mock_txn.__enter__ = MagicMock(return_value=mock_txn)
        mock_txn.__exit__ = MagicMock(return_value=False)
        _mock_sentry.start_transaction.return_value = mock_txn

        from phase_utils import _sentry_transaction

        with _sentry_transaction("pipeline.plan", "plan:#99"):
            pass

        call_kwargs = _mock_sentry.start_transaction.call_args[1]
        assert call_kwargs["op"] == "pipeline.plan"
        assert call_kwargs["name"] == "plan:#99"
