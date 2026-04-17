"""Regression test for issue #6363.

Several background loops use ``logger.exception`` for transient operational
failures (network errors, disk I/O, subprocess crashes) instead of
``logger.warning``.  Per ``docs/agents/sentry.md``, ``logger.exception`` (and
``logger.error``) should be reserved for real code bugs so that Sentry stays
signal-rich.

This test inspects the AST of each offending call-site and asserts that the
logging call is **not** ``logger.exception``.  It will fail (RED) until the
fix lands.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

# Each entry: (file relative to src/, line number, snippet for context)
SITES = [
    ("orchestrator.py", 608, "Pipeline stats emission failed"),
    ("stale_issue_loop.py", 69, "Failed to fetch issues for stale check"),
    ("stale_issue_loop.py", 133, "Failed to close stale issue"),
    ("memory.py", 183, "Failed to write tribal memory to JSONL"),
    ("memory.py", 451, "Error routing ADR candidate from memory issue"),
    ("code_grooming_loop.py", 104, "Code grooming audit failed"),
]


def _find_logger_exception_calls(source: str) -> dict[int, str]:
    """Return {lineno: first-string-arg} for every ``logger.exception(...)`` call."""
    tree = ast.parse(source)
    results: dict[int, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match logger.exception(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "exception"
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
        ):
            # Extract the first string argument for identification
            first_arg = ""
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                first_arg = node.args[0].value
            results[node.lineno] = first_arg
    return results


@pytest.mark.parametrize(
    "rel_path,expected_line,snippet",
    SITES,
    ids=[f"{p}:{ln}" for p, ln, _ in SITES],
)
def test_no_logger_exception_for_transient_failures(
    rel_path: str, expected_line: int, snippet: str
) -> None:
    """Assert that the identified call-site does NOT use logger.exception.

    The fix should replace each ``logger.exception(...)`` with
    ``logger.warning(..., exc_info=True)``.
    """
    filepath = SRC / rel_path
    assert filepath.exists(), f"Source file not found: {filepath}"

    source = filepath.read_text()
    exception_calls = _find_logger_exception_calls(source)

    # Check whether there is a logger.exception call at (or near) the expected
    # line whose message matches the snippet.  We allow ±3 lines of drift in
    # case minor edits shift the line number.
    matching_lines = [
        ln
        for ln, msg in exception_calls.items()
        if abs(ln - expected_line) <= 3 and snippet in msg
    ]

    assert not matching_lines, (
        f"{rel_path}:{matching_lines[0]} still uses logger.exception() for a "
        f"transient/operational failure (matched: {snippet!r}).  "
        f"Per docs/agents/sentry.md this should be logger.warning(..., exc_info=True)."
    )
