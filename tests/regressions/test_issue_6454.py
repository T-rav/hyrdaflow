"""Regression test for issue #6454.

Bug: DoltBackend constructs SQL by manual string escaping.  Several methods
(add_to_dedup_set, save_session repo param, get_session, load_sessions) only
escape single-quotes via .replace("'", "''") but do NOT escape backslashes.

In MySQL/Dolt (default sql_mode without NO_BACKSLASH_ESCAPES), \\' is an
escape sequence for a literal single-quote.  So a value containing a
backslash immediately before a quote (\\') produces a SQL literal where the
backslash-quote is consumed as an *escaped quote*, leaving the string
unterminated — causing SQL errors or, with crafted payloads, injection.

Example with add_to_dedup_set("s", "x\\' bad"):
  Buggy SQL:   VALUES ('s', 'x\\'' bad');
  MySQL reads: string = "x'" then " bad'" is dangling SQL → error/injection

  Correct SQL: VALUES ('s', 'x\\\\'' bad');
  MySQL reads: \\\\ = literal \\, '' = literal ' → string = "x\\' bad" ✓
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_ROOT))

from dolt_backend import DoltBackend  # noqa: E402


def _make_backend(tmp_path: Path) -> DoltBackend:
    """Create a DoltBackend without requiring the dolt CLI."""
    backend = object.__new__(DoltBackend)
    backend._dir = tmp_path
    backend._dolt = "/usr/bin/true"
    return backend


# A literal backslash followed by a single-quote.
# Python string: two chars — '\\' and "'"
BACKSLASH_QUOTE = "\\'"


class TestBackslashQuoteEscapingInSQL:
    """Methods that interpolate values into SQL must escape BOTH backslashes
    and single-quotes.  The bug is that several methods only double the
    quote but leave the backslash intact, producing \\' in the SQL literal
    which MySQL/Dolt interprets as an escaped quote."""

    @pytest.mark.xfail(
        reason="Regression for issue #6454 — fix not yet landed", strict=False
    )
    def test_add_to_dedup_set_escapes_backslash(self, tmp_path: Path) -> None:
        """add_to_dedup_set: value with \\' must have the backslash escaped.

        BUG: Only .replace("'", "''") is called.  The backslash is passed
        through verbatim, so the SQL contains \\' which Dolt reads as an
        escaped quote instead of a literal backslash + literal quote.
        """
        backend = _make_backend(tmp_path)
        captured: list[str] = []
        backend._sql_exec = captured.append

        payload = f"data with {BACKSLASH_QUOTE} inside"
        backend.add_to_dedup_set("test_set", payload)

        sql = captured[0]
        # Correct escaping turns \ into \\ and ' into ''
        # so the SQL fragment for the value should contain \\''.
        # With the bug, it contains \'' (backslash not doubled).
        assert "\\\\''" in sql, (
            f"add_to_dedup_set does not escape backslash before quote — "
            f"SQL injection / corruption risk.\n  Generated SQL: {sql!r}"
        )

    @pytest.mark.xfail(
        reason="Regression for issue #6454 — fix not yet landed", strict=False
    )
    def test_save_session_repo_escapes_backslash(self, tmp_path: Path) -> None:
        """save_session: repo param with \\' must have the backslash escaped.

        BUG: escaped_repo uses only .replace("'", "''") — no backslash
        handling.  A repo slug like "org/repo\\'" breaks the WHERE clause.
        """
        backend = _make_backend(tmp_path)
        captured: list[str] = []
        backend._sql_exec = captured.append

        repo = f"org/repo{BACKSLASH_QUOTE}"
        backend.save_session("sess-1", repo, '{"id": "s1"}', "active")

        sql = captured[0]
        # The repo value in SQL must have \ escaped to \\
        assert "\\\\''" in sql, (
            f"save_session does not escape backslash in repo param — "
            f"SQL corruption risk.\n  Generated SQL: {sql!r}"
        )

    @pytest.mark.xfail(
        reason="Regression for issue #6454 — fix not yet landed", strict=False
    )
    def test_get_session_escapes_backslash_in_id(self, tmp_path: Path) -> None:
        """get_session: session_id with \\' must have the backslash escaped.

        BUG: escaped uses only .replace("'", "''").
        """
        backend = _make_backend(tmp_path)
        captured: list[str] = []
        backend._sql = lambda q: (captured.append(q), '{"rows": []}')[1]

        session_id = f"sess{BACKSLASH_QUOTE}id"
        backend.get_session(session_id)

        sql = captured[0]
        assert "\\\\''" in sql, (
            f"get_session does not escape backslash in session_id — "
            f"SQL corruption risk.\n  Generated SQL: {sql!r}"
        )

    @pytest.mark.xfail(
        reason="Regression for issue #6454 — fix not yet landed", strict=False
    )
    def test_load_sessions_repo_escapes_backslash(self, tmp_path: Path) -> None:
        """load_sessions: repo filter with \\' must have the backslash escaped.

        BUG: escaped_repo uses only .replace("'", "''").
        """
        backend = _make_backend(tmp_path)
        captured: list[str] = []
        backend._sql = lambda q: (captured.append(q), '{"rows": []}')[1]

        repo = f"org/repo{BACKSLASH_QUOTE}"
        backend.load_sessions(repo=repo)

        sql = captured[0]
        assert "\\\\''" in sql, (
            f"load_sessions does not escape backslash in repo filter — "
            f"SQL corruption risk.\n  Generated SQL: {sql!r}"
        )


class TestSQLInjectionViaBackslashQuote:
    """Demonstrate that a crafted backslash-quote payload can break out of
    the SQL string literal and inject arbitrary SQL."""

    @pytest.mark.xfail(
        reason="Regression for issue #6454 — fix not yet landed", strict=False
    )
    def test_add_to_dedup_set_injection_payload(self, tmp_path: Path) -> None:
        """A value like  x\\'; DROP TABLE sessions; --  must NOT produce
        executable SQL after the value literal.

        BUG: The only-quote escaping produces:
          VALUES ('s', 'x\\''; DROP TABLE sessions; --');
        MySQL reads \\' as escaped-quote, then '' closes the string,
        leaving  ; DROP TABLE sessions; --  as executable SQL.
        """
        backend = _make_backend(tmp_path)
        captured: list[str] = []
        backend._sql_exec = captured.append

        # Payload: literal backslash + quote + injected SQL
        injection = "x\\'; DROP TABLE sessions; --"
        backend.add_to_dedup_set("test_set", injection)

        sql = captured[0]
        # The SQL must NOT contain "DROP TABLE" outside of a string literal.
        # With correct escaping, the entire payload is inside the value literal.
        # With the bug, "DROP TABLE sessions" appears as executable SQL.
        #
        # Quick check: after correct escaping, the substring '; DROP' should
        # NOT appear — the quote before DROP should be doubled ('') not raw.
        assert "'; DROP" not in sql, (
            f"SQL injection possible — payload broke out of string literal.\n"
            f"  Generated SQL: {sql!r}"
        )
