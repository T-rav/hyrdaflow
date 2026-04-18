"""Auto PR — shared helper for automated worktree+commit+push+PR flows.

This module encapsulates the repeated "create an ephemeral worktree, stage
a set of files, commit, push the branch, open a PR, and clean up" pattern
used by agents that emit PRs on behalf of HydraFlow (ADR acceptance, repo
wiki maintenance, etc.).

Callers write the desired file contents into `repo_root` *before* invoking
`open_automated_pr`; the helper copies each file (preserving relative path)
into a fresh worktree branched off `origin/{base}`, commits it with the
caller-supplied identity (defaulting to the HydraFlow bot, or falling back
to ambient git config when both name and email are empty), pushes, and
opens the PR via `gh`.  The worktree is always removed in a `finally`
block, even on failure.

See `src/adr_reviewer.py::_commit_acceptance` for the original pattern this
helper generalizes.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOT_EMAIL = "hydraflow@noreply"
BOT_NAME = "HydraFlow"
# ^^ Defaults used when the caller does not supply
# `commit_author_name` / `commit_author_email`.  HydraFlow callers should
# pass `self._config.git_user_name` / `self._config.git_user_email` so a
# user-configured identity is respected.

# Characters that are not safe for a filesystem path component. Branch names
# may contain "/" and other characters; sanitize for the worktree dir name.
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class AutoPrError(RuntimeError):
    """Raised when the automated PR flow fails (push, gh create, etc.)."""


@dataclass(frozen=True)
class AutoPrResult:
    """Outcome of an `open_automated_pr` call."""

    status: Literal["opened", "no-diff", "failed"]
    pr_url: str | None
    branch: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitize_branch_for_path(branch: str) -> str:
    """Return a filesystem-safe version of a branch name."""
    cleaned = _SANITIZE_RE.sub("-", branch).strip("-")
    return cleaned or "autopr"


def _run_git(
    args: list[str], *, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the completed process.

    Separated from `_run_gh` so test code can stub `gh` without also stubbing
    the many git calls this module makes against a real repo.
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


def _run_gh(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Thin wrapper around `subprocess.run` for `gh` invocations.

    Kept as a module-level function so tests can monkeypatch
    `auto_pr._run_gh` without intercepting every `subprocess.run` call.
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )


def _remove_worktree(
    repo_root: Path, worktree_path: Path, branch: str | None = None
) -> None:
    """Best-effort worktree cleanup. Never raises.

    When `branch` is provided, also deletes the local branch so a retry with
    the same branch name doesn't hit "branch already exists".
    """
    try:
        _run_git(
            ["worktree", "remove", str(worktree_path), "--force"],
            cwd=repo_root,
            check=False,
        )
    except Exception:  # pragma: no cover - defensive
        # Per docs/agents/sentry.md: handled cleanup failures log at
        # `warning` minimum — never bare `except: pass` or debug-silent.
        logger.warning("git worktree remove failed for %s", worktree_path)

    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)

    if branch is not None:
        # Best-effort: delete the local branch. Harmless if it was already
        # removed by `git worktree remove`.
        _run_git(["branch", "-D", branch], cwd=repo_root, check=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_commit_args(author_name: str, author_email: str, message: str) -> list[str]:
    """Build the arg list for `git commit`, skipping identity overrides when
    the caller-supplied name or email is empty.

    Empty values mean "fall back to git's ambient config" per the
    `HydraFlowConfig.git_user_name/email` contract. Passing `-c user.email=`
    to git would instead force an empty identity and fail with
    "Author identity unknown".
    """
    args: list[str] = []
    if author_name and author_email:
        args.extend(["-c", f"user.email={author_email}"])
        args.extend(["-c", f"user.name={author_name}"])
    args.extend(["commit", "-m", message])
    return args


def open_automated_pr(
    *,
    repo_root: Path,
    branch: str,
    files: list[Path],
    title: str,
    body: str,
    base: str = "main",
    auto_merge: bool = True,
    worktree_parent: Path | None = None,
    commit_author_name: str = BOT_NAME,
    commit_author_email: str = BOT_EMAIL,
) -> AutoPrResult:
    """Open a PR for `files` on a fresh worktree branched from `origin/{base}`.

    Callers write the desired contents to each path under `repo_root` before
    calling; the helper copies each file into a new worktree (preserving
    the path relative to `repo_root`), commits with the HydraFlow bot
    identity, pushes, and opens the PR via `gh`.

    If `files` is empty or the staged diff is empty, returns an
    ``AutoPrResult`` with ``status="no-diff"`` and no push/PR side effects.

    Args:
        repo_root: Root of the primary git checkout.
        branch: New branch name to create (must not already exist on origin).
        files: Paths (under `repo_root`) whose current contents should be
            staged into the PR.  An empty list short-circuits to no-diff.
        title: PR title (also used as the commit message).
        body: PR body.
        base: Base branch the PR targets. Defaults to ``"main"``.
        auto_merge: If True, attempt to enable auto-merge via
            ``gh pr merge --auto --squash``.  Best-effort — failure here is
            logged but does not raise.
        worktree_parent: Directory to create the ephemeral worktree under.
            Defaults to ``repo_root.parent``. Callers that keep worktrees in
            a dedicated workspace (e.g. HydraFlow's ``workspace_base``) pass
            that path here.
        commit_author_name: Name for ``git -c user.name`` on the commit.
            Defaults to the HydraFlow bot. When both name and email are
            empty strings, the ``-c`` overrides are omitted and git uses
            the ambient worktree/global config instead.
        commit_author_email: Email for ``git -c user.email``. See above
            regarding empty-string fallback.

    Returns:
        ``AutoPrResult`` describing the outcome.

    Raises:
        AutoPrError: If the worktree-add, stage, commit, push, or
            ``gh pr create`` step fails.
    """
    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    wt_name = f"autopr-{_sanitize_branch_for_path(branch)}-{timestamp}"
    wt_parent = (worktree_parent or repo_root.parent).resolve()
    wt_parent.mkdir(parents=True, exist_ok=True)
    worktree_path = wt_parent / wt_name

    # Ensure we have an up-to-date origin ref for the base branch.
    _run_git(["fetch", "origin", base, "--quiet"], cwd=repo_root, check=False)

    # Create the worktree on a new branch that starts from origin/{base}.
    try:
        _run_git(
            [
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                f"origin/{base}",
            ],
            cwd=repo_root,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AutoPrError(
            f"git worktree add failed for branch {branch!r}: {exc.stderr}"
        ) from exc

    try:
        # Short-circuit when the caller supplied no files to stage.
        if not files:
            logger.info("open_automated_pr: no files supplied for %s, skipping", branch)
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)

        # Copy each file into the worktree and stage it by relative path.
        try:
            for src_path in files:
                rel = src_path.resolve().relative_to(repo_root)
                dst_path = worktree_path / rel
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                dst_path.write_bytes(src_path.read_bytes())
                _run_git(
                    ["add", str(rel)],
                    cwd=worktree_path,
                    check=True,
                )
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            raise AutoPrError(
                f"failed to stage files for branch {branch!r}: {exc}"
            ) from exc

        # Detect empty staged diff — e.g. the file contents matched origin.
        diff_check = _run_git(
            ["diff", "--cached", "--quiet"],
            cwd=worktree_path,
            check=False,
        )
        if diff_check.returncode == 0:
            logger.info(
                "open_automated_pr: staged diff is empty for %s, skipping",
                branch,
            )
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)

        # Commit with the caller-supplied identity when provided; when either
        # value is empty, omit the `-c user.*` overrides so git falls back to
        # ambient config (worktree → user global → system). This matches the
        # documented `HydraFlowConfig.git_user_name/email` contract that an
        # empty config value falls back to global git config.
        commit_args = _build_commit_args(commit_author_name, commit_author_email, title)
        try:
            _run_git(commit_args, cwd=worktree_path, check=True)
        except subprocess.CalledProcessError as exc:
            raise AutoPrError(f"git commit failed: {exc.stderr}") from exc

        try:
            _run_git(
                ["push", "-u", "origin", branch],
                cwd=worktree_path,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise AutoPrError(
                f"git push failed for branch {branch!r}: {exc.stderr}"
            ) from exc

        create_proc = _run_gh(
            [
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                base,
                "--head",
                branch,
            ],
            cwd=worktree_path,
        )
        if create_proc.returncode != 0:
            raise AutoPrError(
                f"gh pr create failed for branch {branch!r}: "
                f"{create_proc.stderr or create_proc.stdout}"
            )

        pr_url = _extract_pr_url(create_proc.stdout)
        if pr_url is None:
            logger.warning(
                "gh pr create succeeded for %s but no URL was parsed from stdout: %r",
                branch,
                create_proc.stdout,
            )

        if auto_merge and pr_url is not None:
            merge_proc = _run_gh(
                ["gh", "pr", "merge", pr_url, "--auto", "--squash"],
                cwd=worktree_path,
            )
            if merge_proc.returncode != 0:
                # Auto-merge is best-effort; many repos disallow it and that
                # shouldn't fail the whole flow.
                logger.warning(
                    "gh pr merge --auto failed for %s: %s",
                    pr_url,
                    merge_proc.stderr or merge_proc.stdout,
                )

        return AutoPrResult(status="opened", pr_url=pr_url, branch=branch)

    finally:
        _remove_worktree(repo_root, worktree_path, branch=branch)


def _extract_pr_url(stdout: str) -> str | None:
    """Pull the PR URL from `gh pr create` stdout.

    `gh` may emit warnings after the URL; scan from the end for the first
    non-empty line that looks like an HTTPS URL.
    """
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("https://"):
            return stripped
    return None


# ---------------------------------------------------------------------------
# Async API — used from HydraFlow's async call sites (ADR reviewer, etc.)
# ---------------------------------------------------------------------------


async def open_automated_pr_async(  # noqa: PLR0911 — linear step-by-step guards, each with its own fail path
    *,
    repo_root: Path,
    branch: str,
    files: list[Path],
    pr_title: str,
    pr_body: str,
    commit_message: str | None = None,
    base: str = "main",
    auto_merge: bool = True,
    gh_token: str = "",
    raise_on_failure: bool = True,
    worktree_parent: Path | None = None,
    commit_author_name: str = BOT_NAME,
    commit_author_email: str = BOT_EMAIL,
) -> AutoPrResult:
    """Async variant that routes subprocess calls through `run_subprocess`.

    Same high-level behavior as the sync `open_automated_pr`:
    worktree → copy files → stage → commit → push → gh pr create → gh pr merge
    → clean up.

    Differences from the sync version:

    - Uses :func:`subprocess_util.run_subprocess` so it participates in the
      HydraFlow async loop and the `gh/git` concurrency semaphore.
    - Accepts an explicit `gh_token` that's threaded through every call.
    - Accepts an independent `commit_message` for callers where the commit
      message differs from the PR title (e.g. the ADR reviewer embeds the
      council summary in the commit).
    - When `raise_on_failure=False`, logs + returns an
      ``AutoPrResult(status="failed", error=...)`` instead of raising —
      matching the ADR reviewer's "log and continue" contract.

    Args:
        repo_root: Root of the primary git checkout.
        branch: New branch name (must not already exist on origin).
        files: Paths under `repo_root` whose current contents should be
            staged into the PR. Empty → no-diff short-circuit.
        pr_title: Title for the PR.
        pr_body: Body for the PR.
        commit_message: Commit message; defaults to `pr_title` when None.
        base: Base branch. Defaults to ``"main"``.
        auto_merge: If True, attempt `gh pr merge --auto --squash`.
        gh_token: Value injected as GH_TOKEN for each subprocess call.
        raise_on_failure: If False, failures become
            ``AutoPrResult(status="failed")`` instead of raising.
        worktree_parent: Directory to create the ephemeral worktree under.
            Defaults to ``repo_root.parent``.
        commit_author_name: Name for ``git -c user.name`` on the commit.
            Defaults to the HydraFlow bot. When both name and email are
            empty strings, the ``-c`` overrides are omitted and git uses
            the ambient worktree/global config instead.
        commit_author_email: Email for ``git -c user.email``. See above
            regarding empty-string fallback.

    Returns:
        ``AutoPrResult`` describing the outcome.

    Raises:
        AutoPrError: If a step fails and `raise_on_failure` is True.
    """
    from subprocess_util import run_subprocess  # local import: avoids cycles

    repo_root = repo_root.resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    wt_name = f"autopr-{_sanitize_branch_for_path(branch)}-{timestamp}"
    wt_parent = (worktree_parent or repo_root.parent).resolve()
    wt_parent.mkdir(parents=True, exist_ok=True)
    worktree_path = wt_parent / wt_name
    msg = commit_message if commit_message is not None else pr_title

    def _fail(err: str) -> AutoPrResult:
        if raise_on_failure:
            raise AutoPrError(err)
        # These are transient subprocess failures (git/gh network, auth, race
        # conditions) — operational, not code bugs. Per docs/agents/sentry.md,
        # handled transient failures log at `warning`, not `error`.
        # Plain .warning (not .exception) because we may be called outside an
        # except handler; .exception would attach a misleading
        # `NoneType: None` traceback in Sentry.
        logger.warning("open_automated_pr_async failed for %s: %s", branch, err)
        return AutoPrResult(status="failed", pr_url=None, branch=branch, error=err)

    # Best-effort fetch of the base ref. If the fetch fails (offline,
    # transient auth hiccup), fall through: the subsequent `git worktree add`
    # will use whatever cached `origin/{base}` the local repo already has,
    # which is usually recent enough. Only a missing local `origin/{base}`
    # ref will fail, at which point `git worktree add` surfaces a clear
    # error and we route through `_fail` like any other failure.
    try:
        await run_subprocess(
            "git",
            "fetch",
            "origin",
            base,
            "--quiet",
            cwd=repo_root,
            gh_token=gh_token,
        )
    except RuntimeError as exc:
        logger.warning(
            "git fetch origin %s failed for %s; continuing with cached ref: %s",
            base,
            branch,
            exc,
        )

    # From here on every exit path must go through `finally` so the worktree
    # + branch are torn down regardless of outcome.
    try:
        try:
            await run_subprocess(
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                f"origin/{base}",
                cwd=repo_root,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            return _fail(f"git worktree add failed for {branch!r}: {exc}")
        if not files:
            logger.info("open_automated_pr_async: no files supplied for %s", branch)
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)

        # Copy each file, stage by relative path (targeted; no `git add -A`).
        try:
            for src_path in files:
                rel = src_path.resolve().relative_to(repo_root)
                dst_path = worktree_path / rel
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                dst_path.write_bytes(src_path.read_bytes())
                await run_subprocess(
                    "git",
                    "add",
                    str(rel),
                    cwd=worktree_path,
                    gh_token=gh_token,
                )
        except (RuntimeError, OSError, ValueError) as exc:
            return _fail(f"failed to stage files for {branch!r}: {exc}")

        # Detect empty staged diff.
        try:
            await run_subprocess(
                "git",
                "diff",
                "--cached",
                "--quiet",
                cwd=worktree_path,
                gh_token=gh_token,
            )
            # exit 0 → no staged diff
            logger.info("open_automated_pr_async: empty staged diff for %s", branch)
            return AutoPrResult(status="no-diff", pr_url=None, branch=branch)
        except RuntimeError:
            # Non-zero exit means there IS a diff. Proceed.
            pass

        # Commit with the caller-supplied identity when provided; when either
        # value is empty, omit the `-c user.*` overrides so git falls back to
        # ambient config per the `HydraFlowConfig.git_user_name/email`
        # contract.
        commit_args = _build_commit_args(commit_author_name, commit_author_email, msg)
        try:
            await run_subprocess(
                "git", *commit_args, cwd=worktree_path, gh_token=gh_token
            )
        except RuntimeError as exc:
            return _fail(f"git commit failed: {exc}")

        try:
            await run_subprocess(
                "git",
                "push",
                "-u",
                "origin",
                branch,
                cwd=worktree_path,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            return _fail(f"git push failed for {branch!r}: {exc}")

        # Create the PR.
        try:
            create_stdout = await run_subprocess(
                "gh",
                "pr",
                "create",
                "--title",
                pr_title,
                "--body",
                pr_body,
                "--base",
                base,
                "--head",
                branch,
                cwd=worktree_path,
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            return _fail(f"gh pr create failed for {branch!r}: {exc}")

        pr_url = _extract_pr_url(create_stdout)
        if pr_url is None:
            logger.warning(
                "gh pr create succeeded for %s but no URL parsed: %r",
                branch,
                create_stdout,
            )

        if auto_merge and pr_url is not None:
            try:
                await run_subprocess(
                    "gh",
                    "pr",
                    "merge",
                    pr_url,
                    "--auto",
                    "--squash",
                    cwd=worktree_path,
                    gh_token=gh_token,
                )
            except RuntimeError as exc:
                logger.warning("gh pr merge --auto failed for %s: %s", pr_url, exc)

        return AutoPrResult(status="opened", pr_url=pr_url, branch=branch)

    finally:
        await _remove_worktree_async(repo_root, worktree_path, branch, gh_token)


async def _remove_worktree_async(
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    gh_token: str,
) -> None:
    """Best-effort async worktree cleanup. Never raises."""
    from subprocess_util import run_subprocess  # local import: avoids cycles

    try:
        await run_subprocess(
            "git",
            "worktree",
            "remove",
            str(worktree_path),
            "--force",
            cwd=repo_root,
            gh_token=gh_token,
        )
    except RuntimeError:
        # Per docs/agents/sentry.md: handled cleanup failures log at
        # `warning` minimum.
        logger.warning("git worktree remove failed for %s", worktree_path)

    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)

    try:
        await run_subprocess(
            "git",
            "branch",
            "-D",
            branch,
            cwd=repo_root,
            gh_token=gh_token,
        )
    except RuntimeError:
        logger.warning("git branch -D failed for %s", branch)
