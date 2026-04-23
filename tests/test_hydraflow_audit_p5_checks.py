"""Tests for P5 (CI + branch protection) check functions."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p5_ci  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


# --- Workflows ------------------------------------------------------------


def test_workflows_dir_empty_fails(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert _run("P5.1", _ctx(tmp_path)).status is Status.FAIL


def test_workflows_dir_with_files_passes(tmp_path: Path) -> None:
    _write(tmp_path / ".github" / "workflows" / "ci.yml", "name: ci\n")
    assert _run("P5.1", _ctx(tmp_path)).status is Status.PASS


def test_workflow_quality_lite_detected(tmp_path: Path) -> None:
    _write(tmp_path / ".github" / "workflows" / "ci.yml", "run: make quality-lite\n")
    assert _run("P5.2", _ctx(tmp_path)).status is Status.PASS


def test_workflow_quality_lite_absent_fails(tmp_path: Path) -> None:
    _write(tmp_path / ".github" / "workflows" / "ci.yml", "run: make lint\n")
    assert _run("P5.2", _ctx(tmp_path)).status is Status.FAIL


def test_workflow_coverage_gate_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / ".github" / "workflows" / "test.yml",
        "run: pytest --cov-fail-under=70\n",
    )
    assert _run("P5.3", _ctx(tmp_path)).status is Status.PASS


# --- Hooks ----------------------------------------------------------------


def test_pre_commit_hook_missing_fails(tmp_path: Path) -> None:
    assert _run("P5.4", _ctx(tmp_path)).status is Status.FAIL


def test_pre_commit_hook_not_executable_fails(tmp_path: Path) -> None:
    _write(tmp_path / ".githooks" / "pre-commit", "#!/bin/sh\n", executable=False)
    assert _run("P5.4", _ctx(tmp_path)).status is Status.FAIL


def test_pre_commit_hook_present_and_executable_passes(tmp_path: Path) -> None:
    _write(tmp_path / ".githooks" / "pre-commit", "#!/bin/sh\n", executable=True)
    assert _run("P5.4", _ctx(tmp_path)).status is Status.PASS


def test_pre_push_hook_missing_fails(tmp_path: Path) -> None:
    assert _run("P5.8", _ctx(tmp_path)).status is Status.FAIL


def test_pre_push_hook_without_quality_lite_warns(tmp_path: Path) -> None:
    _write(tmp_path / ".githooks" / "pre-push", "#!/bin/sh\necho go\n", executable=True)
    assert _run("P5.8", _ctx(tmp_path)).status is Status.WARN


def test_pre_push_hook_with_quality_lite_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / ".githooks" / "pre-push",
        "#!/bin/sh\nmake quality-lite\n",
        executable=True,
    )
    assert _run("P5.8", _ctx(tmp_path)).status is Status.PASS


def test_self_repair_pattern_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / ".githooks" / "pre-commit",
        "#!/bin/sh\nmake lint-check || make lint-fix\n",
        executable=True,
    )
    assert _run("P5.9", _ctx(tmp_path)).status is Status.PASS


def test_self_repair_absent_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / ".githooks" / "pre-commit",
        "#!/bin/sh\nmake lint-check\n",
        executable=True,
    )
    assert _run("P5.9", _ctx(tmp_path)).status is Status.FAIL


def test_claude_md_guard_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / ".githooks" / "pre-commit",
        "#!/bin/sh\nif git diff --cached --name-status | grep '^D.*CLAUDE.md'; then exit 1; fi\n",
        executable=True,
    )
    assert _run("P5.10", _ctx(tmp_path)).status is Status.PASS


# --- Cultural + pytest config --------------------------------------------


def test_branch_protection_is_cultural_warn(tmp_path: Path) -> None:
    assert _run("P5.5", _ctx(tmp_path)).status is Status.WARN


def test_extract_ruleset_types_finds_each_type() -> None:
    from scripts.hydraflow_audit.checks.p5_ci import _extract_ruleset_types

    body = (
        '[{"type":"deletion","ruleset_id":1},'
        '{"type":"non_fast_forward","ruleset_id":1},'
        '{"type":"pull_request","parameters":{},"ruleset_id":1}]'
    )
    assert _extract_ruleset_types(body) == {
        "deletion",
        "non_fast_forward",
        "pull_request",
    }


def test_extract_ruleset_types_empty_on_empty_list() -> None:
    from scripts.hydraflow_audit.checks.p5_ci import _extract_ruleset_types

    assert _extract_ruleset_types("[]") == set()


def test_default_branch_from_origin_head_symlink(tmp_path: Path) -> None:
    """When origin/HEAD points at main, _resolve_origin_head returns 'main'."""
    from scripts.hydraflow_audit.checks.p5_ci import _resolve_origin_head

    head_dir = tmp_path / ".git" / "refs" / "remotes" / "origin"
    head_dir.mkdir(parents=True)
    (head_dir / "HEAD").write_text("ref: refs/remotes/origin/main\n", encoding="utf-8")
    assert _resolve_origin_head(tmp_path) == "main"


def test_default_branch_missing_origin_head_returns_none(tmp_path: Path) -> None:
    from scripts.hydraflow_audit.checks.p5_ci import _resolve_origin_head

    (tmp_path / ".git").mkdir()
    assert _resolve_origin_head(tmp_path) is None


def test_warnings_as_errors_configured_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        (
            "[tool.pytest.ini_options]\n"
            'filterwarnings = ["error::RuntimeWarning", "error::pytest.PytestUnraisableExceptionWarning"]\n'
        ),
    )
    assert _run("P5.7", _ctx(tmp_path)).status is Status.PASS


def test_warnings_as_errors_partial_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[tool.pytest.ini_options]\nfilterwarnings = ["error::RuntimeWarning"]\n',
    )
    result = _run("P5.7", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "PytestUnraisableExceptionWarning" in result.message


def test_warnings_as_errors_absent_fails(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    assert _run("P5.7", _ctx(tmp_path)).status is Status.FAIL


# --- Git log heuristic ---------------------------------------------------


def _git_init_with_commits(tmp_path: Path, subjects: list[str]) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t"],
        check=False,
        cwd=tmp_path,
    )
    for i, subject in enumerate(subjects):
        (tmp_path / f"f{i}.txt").write_text(subject, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, env=_git_env())
        subprocess.run(
            ["git", "commit", "-q", "-m", subject],
            cwd=tmp_path,
            check=True,
            env=_git_env(),
        )


def _git_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }


def test_git_log_passes_when_commits_have_pr_attribution(tmp_path: Path) -> None:
    _git_init_with_commits(
        tmp_path,
        [f"feat: thing {i} (#{1000 + i})" for i in range(5)],
    )
    assert _run("P5.6", _ctx(tmp_path)).status is Status.PASS


def test_git_log_warns_when_no_pr_attribution(tmp_path: Path) -> None:
    _git_init_with_commits(
        tmp_path,
        [f"direct commit {i}" for i in range(20)],
    )
    assert _run("P5.6", _ctx(tmp_path)).status is Status.WARN


def test_git_log_na_outside_repo(tmp_path: Path) -> None:
    assert _run("P5.6", _ctx(tmp_path)).status is Status.NA
