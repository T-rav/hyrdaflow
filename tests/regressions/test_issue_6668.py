"""Regression test for issue #6668.

Bug: ``tests/regressions/test_issue_6376.py`` and
``tests/regressions/test_issue_6381.py`` import ``httpx`` at module level
(top of file).  The project convention (``docs/wiki/gotchas.md``)
requires optional dependencies to be imported *inside* test functions, not at
module level.  Top-level imports run at collection time — if ``httpx`` is
absent the entire file fails to collect, silently hiding every test from CI.

This test parses the AST of the two offending files and asserts that no
top-level ``import httpx`` (or ``from httpx import …``) statement exists.
It is expected to be **RED** until the imports are moved inside functions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Optional deps that must NOT appear at module level in test files.
OPTIONAL_DEPS = {"httpx", "hindsight"}

REGRESSIONS_DIR = Path(__file__).resolve().parent

# The two files called out in issue #6668.
OFFENDING_FILES = [
    REGRESSIONS_DIR / "test_issue_6376.py",
    REGRESSIONS_DIR / "test_issue_6381.py",
]


def _top_level_optional_imports(filepath: Path) -> list[tuple[int, str]]:
    """Return (lineno, module) for every top-level import of an optional dep."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    violations: list[tuple[int, str]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in OPTIONAL_DEPS:
                    violations.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in OPTIONAL_DEPS:
                violations.append((node.lineno, node.module))
    return violations


@pytest.mark.parametrize(
    "filepath",
    OFFENDING_FILES,
    ids=[p.name for p in OFFENDING_FILES],
)
@pytest.mark.xfail(reason="Regression for issue #6668 — fix not yet landed", strict=False)
def test_no_top_level_httpx_import(filepath: Path) -> None:
    """Each regression test file must defer optional-dep imports to inside
    the test functions that use them — never at module level."""
    violations = _top_level_optional_imports(filepath)
    assert violations == [], (
        f"{filepath.name} has top-level imports of optional deps "
        f"(convention: docs/wiki/gotchas.md):\n"
        + "\n".join(f"  line {line}: import {mod}" for line, mod in violations)
    )
