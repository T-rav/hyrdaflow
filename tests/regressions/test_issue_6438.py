"""Regression test for issue #6438.

Bug: Three places in source use ``if not self._x`` to guard Optional-typed
attributes instead of ``if self._x is None``.  The falsy form can
short-circuit on a non-None but falsy value — most dangerously on
``unittest.mock.Mock(spec=...)`` objects that implement ``__bool__``.

Locations:
  - ``src/pr_unsticker.py:480`` — ``if not self._hitl_runner:``
  - ``src/sentry_loop.py:74``   — ``if not self._store:``
  - ``src/dolt_backend.py:42``  — ``if not self._dolt:``

Convention: ``docs/wiki/gotchas.md`` — "Falsy checks on optional
objects".

This test is RED against the current (buggy) code.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_falsy_guards(filepath: Path, attr_names: set[str]) -> list[tuple[int, str]]:
    """Return ``(lineno, attr)`` for ``if not self.<attr>:`` guard patterns.

    Matches ``If`` nodes whose test is ``UnaryOp(Not, Attribute(Name('self'), attr))``
    where *attr* is one of the given names.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # Match: ``not self.<attr>``
        if (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and isinstance(test.operand, ast.Attribute)
            and isinstance(test.operand.value, ast.Name)
            and test.operand.value.id == "self"
            and test.operand.attr in attr_names
        ):
            violations.append((node.lineno, test.operand.attr))
    return violations


# ---------------------------------------------------------------------------
# AST tests — detect the bad pattern in each cited file
# ---------------------------------------------------------------------------

_KNOWN_VIOLATIONS = [
    ("pr_unsticker.py", {"_hitl_runner"}),
    ("sentry_loop.py", {"_store"}),
    ("dolt_backend.py", {"_dolt"}),
]


class TestFalsyGuardsOnOptionalAttributes:
    """``if not self._x`` on Optional-typed attrs must be ``if self._x is None``."""

    @pytest.mark.parametrize(
        ("filename", "attrs"),
        _KNOWN_VIOLATIONS,
        ids=[f[0] for f in _KNOWN_VIOLATIONS],
    )
    def test_no_falsy_guard_on_optional_attr(
        self, filename: str, attrs: set[str]
    ) -> None:
        filepath = SRC_ROOT / filename
        if not filepath.exists():
            pytest.skip(f"{filename} does not exist")

        violations = _find_falsy_guards(filepath, attrs)
        assert violations == [], (
            f"{filename} uses 'if not self.<attr>' instead of 'is None' "
            f"(violates avoided-patterns.md): {violations}"
        )


# ---------------------------------------------------------------------------
# Behavioral test — prove that a falsy mock silently skips a code path
# ---------------------------------------------------------------------------


class TestFalsyMockSkipsCodePath:
    """Demonstrate the real-world impact: a Mock(spec=...) that is falsy
    causes ``if not self._x`` to skip the code path even though the
    attribute is not None."""

    def test_sentry_loop_exists_in_local_cache_skips_on_falsy_store(self) -> None:
        """SentryLoop._exists_in_local_cache returns False immediately when
        ``self._store`` is a falsy Mock, even though it is not None and
        has a valid ``_issue_cache``.

        Expected (correct): the method should consult the store.
        Actual (buggy): the ``if not self._store`` guard fires and returns
        False without checking.
        """
        from sentry_loop import SentryLoop

        # Build a mock store that is non-None but falsy.
        mock_store = MagicMock()
        mock_store.__bool__ = lambda _self: False  # falsy!
        # Use a MagicMock for _issue_cache so we can track .values() calls.
        mock_cache = MagicMock()
        mock_cache.values.return_value = []  # empty cache → no match
        mock_store._issue_cache = mock_cache

        # Construct a minimal SentryLoop with our falsy store.
        loop = object.__new__(SentryLoop)
        loop._store = mock_store

        # The store is definitely not None …
        assert loop._store is not None

        # … so _exists_in_local_cache should consult it and return False
        # (empty cache → no match), NOT short-circuit on the falsy guard.
        # With the bug, the method hits ``if not self._store: return False``
        # — correct result but wrong reason (never checked the cache).
        _result = loop._exists_in_local_cache("test-sentry-id")

        # The result is False either way (empty cache), but the store's
        # _issue_cache must have been consulted for the logic to be correct.
        assert mock_cache.values.called, (
            "SentryLoop._exists_in_local_cache did not consult store._issue_cache — "
            "the 'if not self._store' guard short-circuited on a falsy (but non-None) "
            "mock.  Should use 'if self._store is None:' instead."
        )
