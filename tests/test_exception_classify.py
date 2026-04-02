"""Tests for the exception_classify cross-cutting utility module."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from exception_classify import LIKELY_BUG_EXCEPTIONS, is_likely_bug


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


class TestBackwardCompatibility:
    """Ensure phase_utils re-exports still work."""

    def test_phase_utils_reexports_is_likely_bug(self) -> None:
        from phase_utils import is_likely_bug as phase_is_likely_bug

        assert phase_is_likely_bug is is_likely_bug

    def test_phase_utils_reexports_likely_bug_exceptions(self) -> None:
        from phase_utils import LIKELY_BUG_EXCEPTIONS as phase_tuple

        assert phase_tuple is LIKELY_BUG_EXCEPTIONS
