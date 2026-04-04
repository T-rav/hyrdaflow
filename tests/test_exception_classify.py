"""Tests for the exception_classify cross-cutting utility module."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from exception_classify import (
    LIKELY_BUG_EXCEPTIONS,
    capture_if_bug,
    is_likely_bug,
    reraise_on_credit_or_bug,
)


class TestIsLikelyBug:
    """Tests for is_likely_bug()."""

    def test_returns_true_for_type_error(self) -> None:
        assert is_likely_bug(TypeError("oops")) is True

    def test_returns_true_for_key_error(self) -> None:
        assert is_likely_bug(KeyError("missing")) is True

    def test_returns_true_for_attribute_error(self) -> None:
        assert is_likely_bug(AttributeError("no attr")) is True

    def test_returns_true_for_value_error(self) -> None:
        assert is_likely_bug(ValueError("bad value")) is True

    def test_returns_true_for_index_error(self) -> None:
        assert is_likely_bug(IndexError("out of range")) is True

    def test_returns_true_for_not_implemented_error(self) -> None:
        assert is_likely_bug(NotImplementedError()) is True

    def test_returns_false_for_runtime_error(self) -> None:
        assert is_likely_bug(RuntimeError("transient")) is False

    def test_returns_false_for_os_error(self) -> None:
        assert is_likely_bug(OSError("disk full")) is False

    def test_returns_false_for_timeout_error(self) -> None:
        assert is_likely_bug(TimeoutError("timed out")) is False

    def test_likely_bug_exceptions_tuple_has_expected_types(self) -> None:
        expected = {
            TypeError,
            KeyError,
            AttributeError,
            ValueError,
            IndexError,
            NotImplementedError,
        }
        assert set(LIKELY_BUG_EXCEPTIONS) == expected


class TestReraiseOnCreditOrBug:
    """Tests for reraise_on_credit_or_bug — now in exception_classify."""

    def test_reraises_credit_exhausted_error(self) -> None:
        from subprocess_util import CreditExhaustedError

        with pytest.raises(CreditExhaustedError):
            try:
                raise CreditExhaustedError("out of credits")
            except Exception as exc:
                reraise_on_credit_or_bug(exc)

    def test_reraises_authentication_error(self) -> None:
        from subprocess_util import AuthenticationError

        with pytest.raises(AuthenticationError):
            try:
                raise AuthenticationError("bad token")
            except Exception as exc:
                reraise_on_credit_or_bug(exc)

    def test_reraises_type_error(self) -> None:
        with pytest.raises(TypeError):
            try:
                raise TypeError("bad type")
            except Exception as exc:
                reraise_on_credit_or_bug(exc)

    def test_reraises_key_error(self) -> None:
        with pytest.raises(KeyError):
            try:
                raise KeyError("missing key")
            except Exception as exc:
                reraise_on_credit_or_bug(exc)

    def test_does_not_reraise_runtime_error(self) -> None:
        handled = False
        try:
            raise RuntimeError("transient")
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            handled = True
        assert handled

    def test_does_not_reraise_os_error(self) -> None:
        handled = False
        try:
            raise OSError("disk full")
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            handled = True
        assert handled

    def test_does_not_reraise_generic_exception(self) -> None:
        handled = False
        try:
            raise Exception("generic")
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            handled = True
        assert handled


class TestCaptureIfBug:
    """Tests for capture_if_bug — Sentry integration."""

    def test_captures_bug_exception(self) -> None:
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            exc = TypeError("oops")
            capture_if_bug(exc)
            mock_sdk.capture_exception.assert_called_once_with(exc)

    def test_adds_breadcrumb_for_transient(self) -> None:
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            exc = RuntimeError("transient")
            capture_if_bug(exc, issue=42)
            mock_sdk.add_breadcrumb.assert_called_once()
            call_kwargs = mock_sdk.add_breadcrumb.call_args[1]
            assert call_kwargs["category"] == "transient_error"
            assert call_kwargs["data"] == {"issue": 42}

    def test_noop_when_sentry_not_installed(self) -> None:
        """Should not raise when sentry_sdk is not available."""
        # Remove sentry_sdk temporarily if present
        original = sys.modules.get("sentry_sdk")
        sys.modules["sentry_sdk"] = None  # type: ignore[assignment]
        try:
            capture_if_bug(TypeError("oops"))  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original
            else:
                sys.modules.pop("sentry_sdk", None)


class TestBackwardCompatibility:
    """Ensure phase_utils re-exports still work."""

    def test_phase_utils_reexports_is_likely_bug(self) -> None:
        from phase_utils import is_likely_bug as phase_is_likely_bug

        assert phase_is_likely_bug is is_likely_bug

    def test_phase_utils_reexports_likely_bug_exceptions(self) -> None:
        from phase_utils import LIKELY_BUG_EXCEPTIONS as phase_tuple

        assert phase_tuple is LIKELY_BUG_EXCEPTIONS

    def test_phase_utils_reexports_reraise_on_credit_or_bug(self) -> None:
        from phase_utils import (
            reraise_on_credit_or_bug as phase_reraise,
        )

        assert phase_reraise is reraise_on_credit_or_bug

    def test_phase_utils_reexports_capture_if_bug(self) -> None:
        from phase_utils import capture_if_bug as phase_capture

        assert phase_capture is capture_if_bug
