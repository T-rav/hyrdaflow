"""Regression tests for issue #3040: inline imports must not shadow module-level bindings.

Scans source files for function-body imports that re-import a name already
available at module level.  This catches the pattern where a developer adds
``from foo import bar`` inside a function body even though ``bar`` is already
imported at the top of the file.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

# Files that were fixed in issue #3040.  The parametrised test below guards
# *only* these files against regressions; violations introduced in other files
# will not be caught here.
_FIXED_FILES = [
    "events.py",
    "dashboard_routes/_routes.py",
    "pr_manager.py",
    "pr_unsticker.py",
    "triage_phase.py",
    "acceptance_criteria.py",
]


def _module_level_names(tree: ast.Module) -> set[str]:
    """Return names imported unconditionally at module level.

    Only bare ``import`` / ``from … import`` statements that are direct
    children of the module are collected.  Conditional blocks (including
    ``if TYPE_CHECKING:`` and platform/version guards) are intentionally
    skipped: their imports may not run at runtime, so a function-body
    re-import of the same name could be a legitimate fallback rather than
    a shadow import.
    """
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _inline_shadow_imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Find function-body imports that shadow a module-level name.

    Returns a list of ``(line_number, imported_name)`` pairs.
    """
    top_names = _module_level_names(tree)
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    name = alias.asname or alias.name
                    if name in top_names:
                        violations.append((child.lineno, name))
    return violations


@pytest.mark.parametrize("rel_path", _FIXED_FILES)
def test_no_inline_shadow_imports(rel_path: str) -> None:
    """Files fixed in #3040 must not regress with new inline shadow imports."""
    path = SRC_DIR / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} not found")
    tree = ast.parse(path.read_text())
    violations = _inline_shadow_imports(tree)
    if violations:
        detail = "\n".join(f"  line {line}: {name}" for line, name in violations)
        msg = textwrap.dedent(f"""\
            {rel_path} has inline imports that shadow module-level bindings:
            {detail}
            Move these to module level or remove the duplicates.""")
        pytest.fail(msg)


class TestAppendJsonlModuleLevelImport:
    """Verify events.py uses append_jsonl from the module-level import."""

    def test_append_jsonl_in_module_namespace(self) -> None:
        """append_jsonl should be importable from events' module scope."""
        import events

        assert hasattr(events, "append_jsonl"), (
            "events.py should import append_jsonl at module level"
        )

    def test_event_log_writes_jsonl(self, tmp_path: Path) -> None:
        """EventLog should successfully persist events via append_jsonl."""
        from events import EventLog

        log_path = tmp_path / "test.jsonl"
        event_log = EventLog(log_path)
        # Drive through the public synchronous path to confirm append_jsonl
        # is reachable from the module-level binding rather than an inline import.
        event_log._append_sync('{"test": true}')

        assert log_path.exists()
        assert '{"test": true}' in log_path.read_text()
