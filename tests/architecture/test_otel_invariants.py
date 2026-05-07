"""Architecture tests enforcing OTel invariants across the codebase.

These tests catch future drift: if someone removes a decorator, adds a
bare asyncio.create_task in an instrumented file, sets hf.* directly
without going through add_hf_context, or adds a fake without a parallel
unit test file — these tests fail before the change merges.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"


def _has_decorator_named(node, *needles: str) -> bool:
    """Return True if any decorator on `node` contains one of `needles`."""
    for d in node.decorator_list:
        text = ast.unparse(d)
        if any(n in text for n in needles):
            return True
    return False


def test_base_runner_execute_is_decorated():
    """BaseRunner._execute must carry @runner_span()."""
    f = SRC / "base_runner.py"
    tree = ast.parse(f.read_text())
    found = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name == "_execute"
            and _has_decorator_named(node, "runner_span")
        ):
            found = True
            break
    assert found, "BaseRunner._execute must be decorated with @runner_span()"


def test_base_loop_execute_cycle_is_decorated():
    """BaseBackgroundLoop._execute_cycle (or _do_work) must carry @loop_span()."""
    f = SRC / "base_background_loop.py"
    tree = ast.parse(f.read_text())
    found = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name in ("_do_work", "_execute_cycle", "_run_tick")
            and _has_decorator_named(node, "loop_span")
        ):
            found = True
            break
    assert found, (
        "BaseBackgroundLoop._do_work/_execute_cycle/_run_tick must be "
        "decorated with @loop_span()"
    )


def test_pr_manager_methods_are_decorated():
    """PRManager port methods (create_pr/merge_pr/create_issue/push_branch) must
    carry @port_span(...)."""
    f = SRC / "pr_manager.py"
    tree = ast.parse(f.read_text())
    decorated: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name in ("create_pr", "merge_pr", "create_issue", "push_branch")
            and _has_decorator_named(node, "port_span")
        ):
            decorated.add(node.name)
    expected = {"create_pr", "merge_pr", "create_issue", "push_branch"}
    missing = expected - decorated
    assert not missing, (
        f"PRManager methods missing @port_span: {missing}; decorated: {decorated}"
    )


def test_workspace_methods_are_decorated():
    """At least one WorkspaceManager method (create or merge_main) must carry
    @port_span()."""
    f = SRC / "workspace.py"
    tree = ast.parse(f.read_text())
    decorated: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name in ("create", "merge_main", "destroy", "reset_to_main")
            and _has_decorator_named(node, "port_span")
        ):
            decorated.add(node.name)
    assert decorated, "WorkspaceManager has no @port_span-decorated port methods"


def test_no_bare_create_task_in_instrumented_files():
    """Instrumented files must not call asyncio.create_task without storing the
    reference. Bare create_task breaks OTel context propagation across tasks
    (see docs/wiki/gotchas.md).

    A "bare" call is one whose return value is not assigned to anything.
    """
    instrumented = [
        SRC / "base_runner.py",
        SRC / "base_background_loop.py",
        SRC / "pr_manager.py",
        SRC / "workspace.py",
        SRC / "events.py",
    ]
    offenders: list[tuple[str, int]] = []
    for f in instrumented:
        if not f.exists():
            continue
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            # An ast.Expr wrapping a Call whose function ends in "create_task"
            # is a bare call (return value discarded).
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                # Match asyncio.create_task or just create_task
                if isinstance(call.func, ast.Attribute):
                    if call.func.attr == "create_task":
                        offenders.append((f.name, node.lineno))
                elif isinstance(call.func, ast.Name) and call.func.id == "create_task":
                    offenders.append((f.name, node.lineno))
    assert not offenders, (
        f"Bare asyncio.create_task() in instrumented files breaks OTel "
        f"context propagation. Store the task reference. Offenders: {offenders}"
    )


def test_hf_attrs_only_set_via_helper():
    """No file outside src/telemetry/ should call span.set_attribute('hf.*', ...)
    directly — all hf.* attrs must go through add_hf_context.

    Exception: tests are allowed to set hf.* directly for assertions.
    """
    offenders: list[tuple[str, int, str]] = []
    for f in SRC.rglob("*.py"):
        if "telemetry" in f.parts:
            continue
        text = f.read_text()
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if "set_attribute" in stripped and '"hf.' in stripped:
                offenders.append((str(f.relative_to(SRC)), i, stripped))
    assert not offenders, (
        "hf.* attributes must be set via add_hf_context, not span.set_attribute. "
        f"Offenders: {offenders}"
    )


def test_new_fakes_have_unit_tests():
    """Any src/mockworld/fakes/fake_*.py file added after the OTel phase must have
    a parallel tests/test_fake_*.py unit test file.

    Pre-existing fakes that shipped without unit tests are grandfathered in;
    only fake_honeycomb.py (added in OTel Phase A Task 8) is actively required.
    """
    fakes_dir = REPO_ROOT / "src" / "mockworld" / "fakes"
    tests_dir = REPO_ROOT / "tests"
    if not fakes_dir.exists():
        return

    # Pre-existing fakes that were shipped before the OTel phase without unit
    # tests. Grandfathered: do not add new entries here for new fakes.
    grandfathered: set[str] = {
        "fake_beads.py",
        "fake_clock.py",
        "fake_docker.py",
        "fake_fs.py",
        "fake_git.py",
        "fake_github.py",
        "fake_http.py",
        "fake_llm.py",
        "fake_sentry.py",
        "fake_subprocess_runner.py",
        "fake_wiki_compiler.py",
        "fake_workspace.py",
    }

    missing: list[str] = []
    for fake_file in fakes_dir.glob("fake_*.py"):
        if fake_file.name in grandfathered:
            continue
        unit_test = tests_dir / f"test_{fake_file.stem}.py"
        if not unit_test.exists():
            missing.append(fake_file.name)
    assert not missing, f"Fakes missing parallel unit test files: {missing}"
