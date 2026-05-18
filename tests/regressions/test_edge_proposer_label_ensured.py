"""Regression: a missing PR label must not crash bot-PR loops.

Observed in production (server.log 2026-05-13): ``EdgeProposerLoop`` opened a
PR with ``--label hydraflow-ul-edges``, but the label did not exist on the
repo. ``gh pr create`` returned rc=1 (``could not add label: ... not found``),
which propagated as ``RuntimeError`` and crashed the loop iteration.

The contract for ``auto_pr.open_automated_pr_async``: when ``labels`` are
supplied, ensure each one exists on the repo (idempotent ``gh label create
--force``) before ``gh pr create``. A failure to ensure one label must NOT
fail the whole PR — log a warning, drop that label, continue.
"""

from __future__ import annotations

import subprocess as _sp
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest


def _stub(
    gh_handler: Callable[[tuple[str, ...]], str | None] | None = None,
    on_cmd: Callable[[tuple[str, ...]], None] | None = None,
    fail_on: Callable[[tuple[str, ...]], str | None] | None = None,
) -> Callable[..., Awaitable[str]]:
    """Stub that intercepts every `gh` call (label + pr) for tests."""

    async def fake_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del gh_token, timeout, runner
        if on_cmd is not None:
            on_cmd(cmd)
        if fail_on is not None:
            err = fail_on(cmd)
            if err is not None:
                raise RuntimeError(err)
        if cmd[:3] == ("gh", "label", "create"):
            if gh_handler is not None:
                stdout = gh_handler(cmd)
                if stdout is None:
                    raise RuntimeError(f"gh label create failed: {cmd}")
                return stdout
            return ""
        if cmd[:2] == ("gh", "pr") and gh_handler is not None:
            stdout = gh_handler(cmd)
            if stdout is None:
                raise RuntimeError(f"gh command failed: {cmd}")
            return stdout.strip()
        try:
            return _sp.run(  # noqa: S603
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except _sp.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    return fake_run


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    """A bare-bones repo + origin remote that auto_pr can push to."""
    origin = tmp_path / "origin.git"
    _sp.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    work = tmp_path / "work"
    _sp.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    _sp.run(
        ["git", "-C", str(work), "config", "user.email", "t@example.com"],
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "-C", str(work), "config", "user.name", "Tester"],
        check=True,
        capture_output=True,
    )
    (work / "README.md").write_text("init\n")
    _sp.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    _sp.run(
        ["git", "-C", str(work), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "-C", str(work), "remote", "add", "origin", str(origin)],
        check=True,
        capture_output=True,
    )
    _sp.run(
        ["git", "-C", str(work), "push", "-u", "origin", "main"],
        check=True,
        capture_output=True,
    )
    return work


@pytest.mark.asyncio
async def test_labels_ensured_before_pr_create(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gh label create --force NAME` must run for each label before `gh pr create`."""
    from auto_pr import open_automated_pr_async

    calls: list[tuple[str, ...]] = []

    def gh_handler(cmd: tuple[str, ...]) -> str:
        if cmd[:3] == ("gh", "pr", "create"):
            return "https://github.com/x/y/pull/9\n"
        return ""

    def on_cmd(cmd: tuple[str, ...]) -> None:
        if cmd[0] == "gh":
            calls.append(cmd)

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _stub(gh_handler=gh_handler, on_cmd=on_cmd),
    )

    target = local_repo / "note.txt"
    target.write_text("hi\n")
    result = await open_automated_pr_async(
        repo_root=local_repo,
        branch="t/labels",
        files=[target],
        pr_title="t",
        pr_body="b",
        auto_merge=False,
        labels=["hydraflow-ul-edges", "another-label"],
    )

    assert result.status == "opened", result.error

    label_indices = [
        i for i, c in enumerate(calls) if c[:3] == ("gh", "label", "create")
    ]
    pr_create_idx = next(
        i for i, c in enumerate(calls) if c[:3] == ("gh", "pr", "create")
    )
    assert len(label_indices) >= 2, (
        f"expected at least 2 `gh label create` calls, got {len(label_indices)}: {calls}"
    )
    assert all(i < pr_create_idx for i in label_indices), (
        "all label-create calls must precede pr create"
    )
    label_names = {c[3] for c in calls if c[:3] == ("gh", "label", "create")}
    assert label_names == {"hydraflow-ul-edges", "another-label"}


@pytest.mark.asyncio
async def test_label_ensure_failure_does_not_abort_pr(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If `gh label create` fails for one label, the PR opens without it."""
    from auto_pr import open_automated_pr_async

    pr_create_cmds: list[tuple[str, ...]] = []

    def gh_handler(cmd: tuple[str, ...]) -> str:
        if cmd[:3] == ("gh", "pr", "create"):
            pr_create_cmds.append(cmd)
            return "https://github.com/x/y/pull/10\n"
        return ""

    def fail_on(cmd: tuple[str, ...]) -> str | None:
        if cmd[:3] == ("gh", "label", "create") and "broken-label" in cmd:
            return "label create denied"
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _stub(gh_handler=gh_handler, fail_on=fail_on),
    )

    target = local_repo / "note.txt"
    target.write_text("hi\n")
    result = await open_automated_pr_async(
        repo_root=local_repo,
        branch="t/labels-partial",
        files=[target],
        pr_title="t",
        pr_body="b",
        auto_merge=False,
        labels=["broken-label", "good-label"],
    )

    assert result.status == "opened", result.error
    assert len(pr_create_cmds) == 1
    pr_cmd = pr_create_cmds[0]
    assert "good-label" in pr_cmd
    assert "broken-label" not in pr_cmd
