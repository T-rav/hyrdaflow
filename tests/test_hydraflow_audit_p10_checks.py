"""Tests for P10 (TDD discipline) check functions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p10_tdd  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- P10.1 ----------------------------------------------------------------


def test_claude_md_tdd_reference_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "CLAUDE.md",
        "Use test-first discipline via the superpowers:test-driven-development skill.\n",
    )
    assert _run("P10.1", _ctx(tmp_path)).status is Status.PASS


def test_claude_md_without_tdd_warns(tmp_path: Path) -> None:
    _write(tmp_path / "CLAUDE.md", "Nothing about testing.\n")
    assert _run("P10.1", _ctx(tmp_path)).status is Status.WARN


# --- P10.2 ----------------------------------------------------------------


def test_every_module_has_test_passes(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "foo.py", "def f(): pass\n")
    _write(tmp_path / "tests" / "test_foo.py", "def test_f(): pass\n")
    assert _run("P10.2", _ctx(tmp_path)).status is Status.PASS


def test_orphan_modules_warn(tmp_path: Path) -> None:
    for i in range(10):
        _write(tmp_path / "src" / f"m{i}.py", "def f(): pass\n")
    # Only one test file for ten modules → 90% orphan → WARN.
    _write(tmp_path / "tests" / "test_m0.py", "def test_f(): pass\n")
    assert _run("P10.2", _ctx(tmp_path)).status is Status.WARN


def test_na_without_src(tmp_path: Path) -> None:
    assert _run("P10.2", _ctx(tmp_path)).status is Status.NA


# --- P10.3 (git log) ------------------------------------------------------


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def _git_init(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)


def _git_commit(tmp_path: Path, subject: str, files: dict[str, str]) -> None:
    for rel, content in files.items():
        _write(tmp_path / rel, content)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, env=_git_env())
    subprocess.run(
        ["git", "commit", "-q", "-m", subject],
        cwd=tmp_path,
        check=True,
        env=_git_env(),
    )


def test_fix_with_regression_test_passes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _git_commit(tmp_path, "feat: seed", {"README.md": "x\n"})
    _git_commit(
        tmp_path,
        "fix: handle null input",
        {
            "src/a.py": "def f(): return 1\n",
            "tests/regressions/test_null_input.py": "def test_x(): pass\n",
        },
    )
    assert _run("P10.3", _ctx(tmp_path)).status is Status.PASS


def test_fix_without_regression_test_warns(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _git_commit(tmp_path, "feat: seed", {"README.md": "x\n"})
    _git_commit(tmp_path, "fix: typo", {"src/a.py": "def f(): return 1\n"})
    assert _run("P10.3", _ctx(tmp_path)).status is Status.WARN


def test_no_fix_commits_passes(tmp_path: Path) -> None:
    _git_init(tmp_path)
    _git_commit(tmp_path, "feat: initial", {"README.md": "x\n"})
    assert _run("P10.3", _ctx(tmp_path)).status is Status.PASS


def test_na_outside_git(tmp_path: Path) -> None:
    assert _run("P10.3", _ctx(tmp_path)).status is Status.NA


# --- P10.4 ----------------------------------------------------------------


def test_behavioural_test_names_pass(tmp_path: Path) -> None:
    body = "\n".join(f"def test_handles_case_{i}_when_x(): pass" for i in range(20))
    _write(tmp_path / "tests" / "test_behaviour.py", body)
    assert _run("P10.4", _ctx(tmp_path)).status is Status.PASS


def test_implementation_named_tests_warn(tmp_path: Path) -> None:
    # Single-word test names (no `_when_` etc.) are the implementation-named shape.
    body = "\n".join(f"def test_handler{i}(): pass" for i in range(20))
    _write(tmp_path / "tests" / "test_impl.py", body)
    assert _run("P10.4", _ctx(tmp_path)).status is Status.WARN


# --- P10.5 ----------------------------------------------------------------


def test_tests_mostly_single_assert_pass(tmp_path: Path) -> None:
    body = "\n".join(f"def test_x{i}():\n    assert True" for i in range(20))
    _write(tmp_path / "tests" / "test_a.py", body)
    assert _run("P10.5", _ctx(tmp_path)).status is Status.PASS


def test_many_multi_assert_tests_warn(tmp_path: Path) -> None:
    body = "\n".join(
        f"def test_x{i}():\n    assert True\n    assert True\n    assert True\n    assert True"
        for i in range(20)
    )
    _write(tmp_path / "tests" / "test_a.py", body)
    assert _run("P10.5", _ctx(tmp_path)).status is Status.WARN
