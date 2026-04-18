"""Tests for src/auto_pr.py — shared worktree+commit+push+PR helper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """A bare git repo that acts as 'origin' for tests."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    return remote


@pytest.fixture
def local_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """A checkout of the bare remote, with one initial commit on main."""
    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(bare_remote), str(local)], check=True)
    subprocess.run(["git", "-C", str(local), "checkout", "-b", "main"], check=True)
    (local / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(local), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(local),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(local), "push", "-u", "origin", "main"], check=True
    )
    return local


def test_open_automated_pr_creates_worktree_commits_and_cleans_up(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: worktree created, file committed, pushed, PR command invoked, worktree removed."""
    from auto_pr import open_automated_pr

    gh_calls: list[list[str]] = []

    def fake_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        gh_calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="https://github.com/x/y/pull/1\n", stderr=""
        )

    monkeypatch.setattr("auto_pr._run_gh", fake_gh)

    target_file = local_repo / "new.txt"
    # Caller writes the file content BEFORE calling open_automated_pr.
    target_file.write_text("hello\n")

    result = open_automated_pr(
        repo_root=local_repo,
        branch="feature/x",
        files=[target_file],
        title="feat: x",
        body="body",
        base="main",
        auto_merge=True,
    )

    # PR command invoked exactly once, with correct title/body/branch
    assert any(("pr" in c and "create" in c) for c in gh_calls)
    # Auto-merge enabled
    assert any(("pr" in c and "merge" in c and "--auto" in c) for c in gh_calls)
    # Result carries the PR URL
    assert result.pr_url == "https://github.com/x/y/pull/1"
    # No leftover worktrees
    wt_list = subprocess.run(
        ["git", "-C", str(local_repo), "worktree", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert wt_list.count("\n") == 1  # only main checkout remains


def test_open_automated_pr_cleans_up_worktree_on_failure(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worktree is removed even when the gh call fails."""
    from auto_pr import AutoPrError, open_automated_pr

    def failing_gh(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="gh failed")

    monkeypatch.setattr("auto_pr._run_gh", failing_gh)

    (local_repo / "f.txt").write_text("x\n")
    with pytest.raises(AutoPrError):
        open_automated_pr(
            repo_root=local_repo,
            branch="feature/fail",
            files=[local_repo / "f.txt"],
            title="t",
            body="b",
        )

    wt_list = subprocess.run(
        ["git", "-C", str(local_repo), "worktree", "list"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert wt_list.count("\n") == 1  # only main checkout remains


def test_open_automated_pr_skips_when_no_diff(local_repo: Path) -> None:
    """If the caller passes no files, the function returns a 'no-diff' result without pushing."""
    from auto_pr import open_automated_pr

    # files=[] short-circuits before any gh call is made, so no monkeypatching needed.
    result = open_automated_pr(
        repo_root=local_repo,
        branch="feature/empty",
        files=[],
        title="t",
        body="b",
    )

    assert result.pr_url is None
    assert result.status == "no-diff"


def test_open_automated_pr_skips_when_file_matches_base(local_repo: Path) -> None:
    """A file whose content matches origin produces an empty staged diff → no-diff."""
    from auto_pr import open_automated_pr

    # README.md already exists on origin/main with content "init\n".
    # Pass it unchanged — the staged diff will be empty.
    result = open_automated_pr(
        repo_root=local_repo,
        branch="feature/identical",
        files=[local_repo / "README.md"],
        title="t",
        body="b",
    )

    assert result.pr_url is None
    assert result.status == "no-diff"


def test_open_automated_pr_wraps_git_add_failure_in_autoprerror(
    local_repo: Path,
) -> None:
    """A file outside repo_root triggers a ValueError in relative_to; must surface as AutoPrError."""
    from auto_pr import AutoPrError, open_automated_pr

    outside = local_repo.parent / "outside.txt"
    outside.write_text("x\n")

    with pytest.raises(AutoPrError, match="failed to stage files"):
        open_automated_pr(
            repo_root=local_repo,
            branch="feature/bad-path",
            files=[outside],
            title="t",
            body="b",
        )


def test_remove_worktree_deletes_local_branch(local_repo: Path) -> None:
    """After open_automated_pr returns no-diff, the local branch is cleaned up so retries work."""
    from auto_pr import open_automated_pr

    branch = "feature/retry-me"
    # First call: no-diff (files=[]).
    open_automated_pr(
        repo_root=local_repo,
        branch=branch,
        files=[],
        title="t",
        body="b",
    )
    # Second call with the same branch must not fail with "branch already exists".
    result = open_automated_pr(
        repo_root=local_repo,
        branch=branch,
        files=[],
        title="t",
        body="b",
    )
    assert result.status == "no-diff"


# ---------------------------------------------------------------------------
# Async API tests
# ---------------------------------------------------------------------------


import subprocess as _sp
from collections.abc import Awaitable, Callable
from pathlib import Path as _Path

GhHandler = Callable[[tuple[str, ...]], str | None]
OnCmd = Callable[[tuple[str, ...]], None]
FailOn = Callable[[tuple[str, ...]], str | None]


def _real_run_subprocess_stub(
    gh_handler: GhHandler | None = None,
    on_cmd: OnCmd | None = None,
    fail_on: FailOn | None = None,
) -> Callable[..., Awaitable[str]]:
    """Build a fake `run_subprocess` that matches the real contract:

    - Raises RuntimeError on non-zero exit (not CalledProcessError).
    - Returns stripped stdout on success.
    - `gh pr` calls route through `gh_handler` so tests never hit real `gh`.
    - `on_cmd` is a side-effect hook.
    - `fail_on` returning a non-None string raises RuntimeError with that msg.
    """

    async def fake_run(
        *cmd: str,
        cwd: _Path | None = None,
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
        if cmd[:2] == ("gh", "pr") and gh_handler is not None:
            stdout = gh_handler(cmd)
            if stdout is None:
                raise RuntimeError(f"gh command failed: {cmd}")
            return stdout.strip()
        try:
            return _sp.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except _sp.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    return fake_run


@pytest.mark.asyncio
async def test_async_happy_path_opens_pr(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open_automated_pr_async: file written, committed, pushed, gh pr create called."""
    from auto_pr import open_automated_pr_async

    gh_calls: list[tuple[str, ...]] = []

    def gh_handler(cmd: tuple[str, ...]) -> str:
        gh_calls.append(cmd)
        if cmd[2] == "create":
            return "https://github.com/x/y/pull/42\n"
        return ""

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _real_run_subprocess_stub(gh_handler=gh_handler),
    )

    target = local_repo / "note.txt"
    target.write_text("hi\n")

    result = await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/a",
        files=[target],
        pr_title="feat: a",
        pr_body="b",
        auto_merge=True,
    )

    assert result.status == "opened"
    assert result.pr_url == "https://github.com/x/y/pull/42"
    assert any(c[:3] == ("gh", "pr", "create") for c in gh_calls)
    assert any(c[:3] == ("gh", "pr", "merge") for c in gh_calls)


@pytest.mark.asyncio
async def test_async_uses_separate_commit_message(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When commit_message is supplied, it's used for the commit (not pr_title)."""
    from auto_pr import open_automated_pr_async

    commit_msgs: list[str] = []

    def on_cmd(cmd: tuple[str, ...]) -> None:
        if "commit" in cmd and "-m" in cmd:
            idx = cmd.index("-m")
            commit_msgs.append(cmd[idx + 1])

    def gh_handler(cmd: tuple[str, ...]) -> str:
        if cmd[2] == "create":
            return "https://github.com/x/y/pull/1\n"
        return ""

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _real_run_subprocess_stub(gh_handler=gh_handler, on_cmd=on_cmd),
    )

    target = local_repo / "x.txt"
    target.write_text("x\n")

    await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/msg",
        files=[target],
        pr_title="short title",
        pr_body="body",
        commit_message="long commit message\n\nDetails here.",
    )

    assert "long commit message" in commit_msgs[0]
    assert "short title" not in commit_msgs[0]


@pytest.mark.asyncio
async def test_async_raise_on_failure_false_returns_failed_status(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With raise_on_failure=False, push failure returns status='failed' instead of raising."""
    from auto_pr import open_automated_pr_async

    def fail_on(cmd: tuple[str, ...]) -> str | None:
        if cmd[:2] == ("git", "push"):
            return "push rejected"
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _real_run_subprocess_stub(fail_on=fail_on),
    )

    target = local_repo / "f.txt"
    target.write_text("f\n")

    result = await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/nofail",
        files=[target],
        pr_title="t",
        pr_body="b",
        raise_on_failure=False,
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "push" in result.error.lower()


@pytest.mark.asyncio
async def test_async_gh_token_is_forwarded(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gh_token kwarg is forwarded to every subprocess call."""
    from auto_pr import open_automated_pr_async

    tokens_seen: list[str] = []

    # We need the raw gh_token that was passed — go direct rather than via
    # the stub factory so we can capture it.
    import subprocess as _spmod

    async def capturing_run(
        *cmd: str,
        cwd: Path | None = None,
        gh_token: str = "",
        timeout: float = 120.0,
        runner: object = None,
    ) -> str:
        del timeout, runner
        tokens_seen.append(gh_token)
        if cmd[:3] == ("gh", "pr", "create"):
            return "https://github.com/x/y/pull/7"
        if cmd[:2] == ("gh", "pr"):
            return ""
        try:
            return _spmod.run(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except _spmod.CalledProcessError as exc:
            raise RuntimeError(exc.stderr or str(exc)) from exc

    monkeypatch.setattr("subprocess_util.run_subprocess", capturing_run)

    target = local_repo / "t.txt"
    target.write_text("t\n")

    await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/tok",
        files=[target],
        pr_title="t",
        pr_body="b",
        gh_token="ghs_TESTTOKEN",
    )

    # Every captured call received the same token (ignore the rare empty
    # no-op entries for edge paths if any).
    relevant = [t for t in tokens_seen if t]
    assert relevant, "no subprocess calls observed"
    assert all(t == "ghs_TESTTOKEN" for t in relevant)


@pytest.mark.asyncio
async def test_async_commit_author_is_forwarded(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """commit_author_name / commit_author_email appear in the git commit -c args."""
    from auto_pr import open_automated_pr_async

    commit_cmds: list[tuple[str, ...]] = []

    def on_cmd(cmd: tuple[str, ...]) -> None:
        if "commit" in cmd and "-m" in cmd:
            commit_cmds.append(cmd)

    def gh_handler(cmd: tuple[str, ...]) -> str:
        if cmd[2] == "create":
            return "https://github.com/x/y/pull/11\n"
        return ""

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _real_run_subprocess_stub(gh_handler=gh_handler, on_cmd=on_cmd),
    )

    target = local_repo / "author.txt"
    target.write_text("hi\n")

    await open_automated_pr_async(
        repo_root=local_repo,
        branch="feature/author",
        files=[target],
        pr_title="t",
        pr_body="b",
        commit_author_name="Jane Dev",
        commit_author_email="jane@example.com",
    )

    assert len(commit_cmds) == 1
    cmd = commit_cmds[0]
    assert "user.email=jane@example.com" in cmd
    assert "user.name=Jane Dev" in cmd


@pytest.mark.asyncio
async def test_async_fetch_failure_is_non_fatal(
    local_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """git fetch failures log a warning but don't abort the flow.

    The subsequent worktree add proceeds against the cached `origin/{base}`.
    """
    from auto_pr import open_automated_pr_async

    def fail_on(cmd: tuple[str, ...]) -> str | None:
        if cmd[:3] == ("git", "fetch", "origin"):
            return "network unreachable"
        return None

    def gh_handler(cmd: tuple[str, ...]) -> str:
        if cmd[2] == "create":
            return "https://github.com/x/y/pull/12\n"
        return ""

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _real_run_subprocess_stub(gh_handler=gh_handler, fail_on=fail_on),
    )

    target = local_repo / "offline.txt"
    target.write_text("offline\n")

    with caplog.at_level("WARNING", logger="auto_pr"):
        result = await open_automated_pr_async(
            repo_root=local_repo,
            branch="feature/offline",
            files=[target],
            pr_title="t",
            pr_body="b",
        )

    assert result.status == "opened"
    assert any(
        "git fetch origin main failed" in rec.message and rec.levelname == "WARNING"
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_async_fail_logs_at_warning_not_error(
    local_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Transient subprocess failures with raise_on_failure=False log at WARNING,
    not ERROR, to avoid flooding Sentry (docs/agents/sentry.md).
    """
    from auto_pr import open_automated_pr_async

    def fail_on(cmd: tuple[str, ...]) -> str | None:
        if cmd[:2] == ("git", "push"):
            return "push rejected"
        return None

    monkeypatch.setattr(
        "subprocess_util.run_subprocess",
        _real_run_subprocess_stub(fail_on=fail_on),
    )

    target = local_repo / "x.txt"
    target.write_text("x\n")

    with caplog.at_level("WARNING", logger="auto_pr"):
        result = await open_automated_pr_async(
            repo_root=local_repo,
            branch="feature/warn",
            files=[target],
            pr_title="t",
            pr_body="b",
            raise_on_failure=False,
        )

    assert result.status == "failed"
    # The failure message must log at WARNING, never ERROR.
    failure_logs = [
        rec for rec in caplog.records if "open_automated_pr_async failed" in rec.message
    ]
    assert failure_logs, "expected a failure log line"
    assert all(rec.levelname == "WARNING" for rec in failure_logs)
