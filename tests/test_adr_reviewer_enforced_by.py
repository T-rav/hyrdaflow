"""Tests for the Enforced-by injector in the ADR council writer.

Closes the gap where bot-authored ADRs flipped to Accepted without
an ``**Enforced by:**`` line, which would then fail
``tests/test_adr_enforcement.py`` on the next CI run.
"""

from __future__ import annotations

from adr_reviewer import _ensure_enforced_by_line


def test_injects_placeholder_when_absent() -> None:
    content = (
        "# ADR-0099: Test ADR\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-04-24\n\n"
        "## Context\n\nSomething.\n"
    )
    result = _ensure_enforced_by_line(content)
    assert "**Enforced by:** (none)" in result
    # Must land directly under Status, not elsewhere
    status_idx = result.index("**Status:**")
    enforced_idx = result.index("**Enforced by:**")
    date_idx = result.index("**Date:**")
    assert status_idx < enforced_idx < date_idx


def test_preserves_existing_enforced_by() -> None:
    """If the author already provided a line, don't overwrite it."""
    content = (
        "# ADR-0099: Test\n\n"
        "**Status:** Accepted\n"
        "**Enforced by:** tests/test_foo.py\n"
        "**Date:** 2026-04-24\n\n"
        "## Context\n\nYes.\n"
    )
    result = _ensure_enforced_by_line(content)

    assert "**Enforced by:** tests/test_foo.py" in result
    assert "(none)" not in result
    # Only one Enforced-by line, not two.
    assert result.count("**Enforced by:**") == 1


def test_no_status_line_leaves_content_untouched() -> None:
    """Malformed ADR (no Status line) shouldn't crash — just pass through."""
    content = "# ADR-0099: Malformed\n\nNo status line present.\n"
    result = _ensure_enforced_by_line(content)
    assert result == content
