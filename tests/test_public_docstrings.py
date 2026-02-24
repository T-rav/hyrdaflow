"""Tests verifying that public methods in key modules have docstrings.

Ensures the API consistency requirement from issue #1067 is maintained:
every public method and function (not prefixed with ``_``) in the listed
modules must have a docstring.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Root of the source tree (one level up from tests/)
_SRC_ROOT = Path(__file__).resolve().parent.parent

# Modules that must have docstrings on all public methods/functions.
_MODULES = [
    "state.py",
    "events.py",
    "base_runner.py",
    "hitl_phase.py",
    "dashboard.py",
    "dashboard_routes.py",
    "cli.py",
    "worktree.py",
    "pr_manager.py",
    "agent.py",
    "planner.py",
    "reviewer.py",
    "hitl_runner.py",
    "orchestrator.py",
    "service_registry.py",
    "plan_phase.py",
    "implement_phase.py",
    "review_phase.py",
    "triage_phase.py",
    "phase_utils.py",
]


def _collect_public_without_docstring(filepath: Path) -> list[tuple[int, str]]:
    """Return ``(line, name)`` pairs for public functions/methods without docstrings."""
    tree = ast.parse(filepath.read_text())
    missing: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            if not ast.get_docstring(node):
                missing.append((node.lineno, node.name))
    return missing


@pytest.mark.parametrize("module", _MODULES, ids=_MODULES)
def test_all_public_methods_have_docstrings(module: str) -> None:
    """Every public method/function in *module* must have a docstring."""
    filepath = _SRC_ROOT / module
    if not filepath.exists():
        pytest.skip(f"{module} not found")
    missing = _collect_public_without_docstring(filepath)
    assert missing == [], (
        f"{module} has public methods without docstrings: "
        + ", ".join(f"{name}() at line {line}" for line, name in missing)
    )


class TestStateTrackerDocstrings:
    """Verify specific docstring content for StateTracker methods (issue #1067)."""

    def test_set_worktree_docstring_mentions_path_and_issue_number(self) -> None:
        from state import StateTracker

        doc = StateTracker.set_worktree.__doc__
        assert doc is not None
        assert "path" in doc.lower()
        assert "issue_number" in doc.lower()

    def test_get_branch_docstring_mentions_none(self) -> None:
        from state import StateTracker

        doc = StateTracker.get_branch.__doc__
        assert doc is not None
        assert "None" in doc

    def test_mark_pr_docstring_mentions_status(self) -> None:
        from state import StateTracker

        doc = StateTracker.mark_pr.__doc__
        assert doc is not None
        assert "status" in doc.lower()


class TestEventLogDocstrings:
    """Verify EventLog.path property has a docstring."""

    def test_path_property_has_docstring(self) -> None:
        from events import EventLog

        assert EventLog.path.fget is not None
        doc = EventLog.path.fget.__doc__
        assert doc is not None
        assert "path" in doc.lower()
