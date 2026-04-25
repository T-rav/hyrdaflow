"""Regression test for issue #6435.

Bug: Three test files import ``hindsight`` at module level (top of file).
Module-level imports of optional dependencies run at collection time — if
the package is not installed, the entire test file fails to collect and
every test in it silently disappears from the CI report.

The project convention (documented in ``docs/wiki/gotchas.md``)
requires optional-dep imports to be deferred inside test functions/methods.

This test uses AST analysis to assert the convention is followed.  It is
RED against the current (buggy) code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Optional dependencies that must never be imported at module level in tests.
OPTIONAL_DEPS = {"hindsight", "httpx"}

# Root of the tests/ directory.
TESTS_ROOT = Path(__file__).resolve().parent.parent


def _top_level_optional_imports(filepath: Path) -> list[tuple[int, str]]:
    """Return (line, module) pairs for top-level imports of optional deps.

    Only imports that appear at module scope (not inside a function, method,
    or class body) are flagged.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))

    violations: list[tuple[int, str]] = []
    for node in ast.iter_child_nodes(tree):
        # ``import foo`` form
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg in OPTIONAL_DEPS:
                    violations.append((node.lineno, alias.name))
        # ``from foo import bar`` form
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            root_pkg = node.module.split(".")[0]
            if root_pkg in OPTIONAL_DEPS:
                violations.append((node.lineno, node.module))
    return violations


# The three files cited in issue #6435.
KNOWN_VIOLATORS = [
    "test_hindsight.py",
    "test_memory_audit.py",
    "regressions/test_issue_6362.py",
]


class TestNoTopLevelOptionalImportsInTests:
    """Optional-dep imports in test files must be deferred (inside functions)."""

    @pytest.mark.parametrize(
        "relpath",
        KNOWN_VIOLATORS,
        ids=KNOWN_VIOLATORS,
    )
    @pytest.mark.xfail(reason="Regression for issue #6435 — fix not yet landed", strict=False)
    def test_known_violators_have_no_top_level_optional_imports(
        self, relpath: str
    ) -> None:
        """Each cited file must have zero top-level optional-dep imports.

        This test fails (RED) until the imports are moved inside functions.
        """
        filepath = TESTS_ROOT / relpath
        if not filepath.exists():
            pytest.skip(f"{relpath} does not exist")

        violations = _top_level_optional_imports(filepath)
        assert violations == [], (
            f"{relpath} has top-level imports of optional deps "
            f"(collection-time risk): {violations}"
        )

    @pytest.mark.xfail(reason="Regression for issue #6435 — fix not yet landed", strict=False)
    def test_no_new_top_level_optional_imports_anywhere(self) -> None:
        """Scan all test files — no new top-level optional-dep imports."""
        all_violations: list[str] = []
        for pyfile in sorted(TESTS_ROOT.rglob("*.py")):
            # Skip this file itself (it imports nothing optional).
            if pyfile == Path(__file__).resolve():
                continue
            hits = _top_level_optional_imports(pyfile)
            for lineno, mod in hits:
                rel = pyfile.relative_to(TESTS_ROOT)
                all_violations.append(f"{rel}:{lineno} — {mod}")

        assert all_violations == [], (
            "Top-level imports of optional deps found in test files "
            "(violates docs/wiki/gotchas.md):\n"
            + "\n".join(f"  • {v}" for v in all_violations)
        )
