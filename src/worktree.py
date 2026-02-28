"""Git worktree lifecycle management for HydraFlow."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import shutil
import stat
from pathlib import Path

from config import HydraFlowConfig
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.worktree")

_FETCH_LOCKS: dict[str, asyncio.Lock] = {}


class WorktreeManager:
    """Creates, configures, and destroys isolated git worktrees.

    Each worktree gets:
    - A fresh branch from ``main``
    - An independent venv via ``uv sync``
    - ``.env`` and ``node_modules/`` dirs (symlinked in host mode, copied in docker mode)
    - Copied ``.claude/settings.local.json``
    - Pre-commit hooks installed (symlinked path in host mode, copied files in docker mode)
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._repo_root = config.repo_root
        self._base = config.worktree_base
        self._ui_dirs = self._detect_ui_dirs()

    def _detect_ui_dirs(self) -> list[str]:
        """Auto-detect UI directories by scanning for ``package.json`` files.

        Falls back to ``config.ui_dirs`` if no ``package.json`` files are found.
        """
        detected: list[str] = []
        try:
            for pkg_json in self._repo_root.rglob("package.json"):
                # Skip node_modules and hidden directories
                parts = pkg_json.relative_to(self._repo_root).parts
                if "node_modules" in parts or any(p.startswith(".") for p in parts):
                    continue
                parent = str(pkg_json.parent.relative_to(self._repo_root))
                if parent == ".":
                    continue  # Skip root-level package.json
                detected.append(parent)
        except OSError:
            logger.debug("Could not scan for package.json files", exc_info=True)
        if detected:
            logger.info("Auto-detected UI dirs: %s", detected)
            return sorted(detected)
        return list(self._config.ui_dirs)

    def _repo_fetch_lock(self) -> asyncio.Lock:
        """Return a shared lock for git fetch operations in this repo."""
        key = str(self._repo_root.resolve())
        lock = _FETCH_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _FETCH_LOCKS[key] = lock
        return lock

    def _is_main_ref_lock_error(self, message: str) -> bool:
        """Return True when *message* matches git remote-ref lock races."""
        main_ref = f"refs/remotes/origin/{self._config.main_branch}"
        return (
            f"cannot lock ref '{main_ref}'" in message
            and "unable to update local ref" in message
        )

    async def _fetch_origin_with_retry(self, cwd: Path, *refs: str) -> None:
        """Run ``git fetch origin <refs...>`` with lock + targeted race retry."""
        attempts = 3
        async with self._repo_fetch_lock():
            for attempt in range(1, attempts + 1):
                try:
                    await run_subprocess(
                        "git",
                        "fetch",
                        "origin",
                        *refs,
                        cwd=cwd,
                        gh_token=self._config.gh_token,
                    )
                    return
                except RuntimeError as exc:
                    msg = str(exc)
                    if attempt < attempts and self._is_main_ref_lock_error(msg):
                        delay = 0.2 * (2 ** (attempt - 1)) + random.uniform(0, 0.15)  # noqa: S311
                        logger.warning(
                            "git fetch race on origin/%s (attempt %d/%d) — retrying in %.2fs",
                            self._config.main_branch,
                            attempt,
                            attempts,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

    async def _delete_local_branch(self, branch: str) -> None:
        """Delete a local branch if it exists, ignoring errors."""
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "branch",
                "-D",
                branch,
                cwd=self._repo_root,
                gh_token=self._config.gh_token,
            )

    async def _remote_branch_exists(self, branch: str) -> bool:
        """Check whether *branch* exists on the remote."""
        try:
            output = await run_subprocess(
                "git",
                "ls-remote",
                "--heads",
                "origin",
                branch,
                cwd=self._repo_root,
                gh_token=self._config.gh_token,
            )
            return bool(output.strip())
        except RuntimeError:
            return False

    async def create(self, issue_number: int, branch: str) -> Path:
        """Create a worktree for *issue_number* on *branch*.

        If the branch already exists on the remote (previous run), fetches
        and checks it out so work can resume.  Otherwise creates a fresh
        branch from main.

        Returns the absolute path to the new worktree.
        """
        wt_path = self._config.worktree_path_for_issue(issue_number)
        logger.info(
            "Creating worktree %s on branch %s",
            wt_path,
            branch,
            extra={"issue": issue_number},
        )

        if self._config.dry_run:
            logger.info("[dry-run] Would create worktree at %s", wt_path)
            return wt_path

        # Ensure base directory exists
        self._base.mkdir(parents=True, exist_ok=True)

        # Clean up any stale local branch (from previous runs) to avoid
        # fetch conflicts and worktree checkout errors
        await self._delete_local_branch(branch)

        branch_created = False
        worktree_created = False

        try:
            # Fetch latest main so we branch from the latest state
            await self._fetch_origin_with_retry(
                self._repo_root, self._config.main_branch
            )

            # Check if the branch already exists on the remote (resumable work)
            if await self._remote_branch_exists(branch):
                logger.info(
                    "Remote branch %s exists — resuming from remote",
                    branch,
                    extra={"issue": issue_number},
                )
                await run_subprocess(
                    "git",
                    "fetch",
                    "origin",
                    f"+refs/heads/{branch}:refs/heads/{branch}",
                    cwd=self._repo_root,
                    gh_token=self._config.gh_token,
                )
            else:
                # Create a fresh branch from main
                await run_subprocess(
                    "git",
                    "branch",
                    "-f",
                    branch,
                    f"origin/{self._config.main_branch}",
                    cwd=self._repo_root,
                    gh_token=self._config.gh_token,
                )
            branch_created = True

            # Create the worktree
            await run_subprocess(
                "git",
                "worktree",
                "add",
                str(wt_path),
                branch,
                cwd=self._repo_root,
                gh_token=self._config.gh_token,
            )
            worktree_created = True

            # Set up the environment inside the worktree
            self._setup_env(wt_path)
            await self._configure_git_identity(wt_path)
            await self._create_venv(wt_path)
            await self._install_hooks(wt_path)
        except BaseException:
            logger.warning(
                "Worktree creation failed for issue %d; cleaning up partial state",
                issue_number,
            )
            if worktree_created:
                with contextlib.suppress(Exception):
                    await run_subprocess(
                        "git",
                        "worktree",
                        "remove",
                        "--force",
                        str(wt_path),
                        cwd=self._repo_root,
                        gh_token=self._config.gh_token,
                    )
            if branch_created:
                with contextlib.suppress(Exception):
                    await self._delete_local_branch(branch)
            raise

        logger.info(
            "Worktree ready at %s",
            wt_path,
            extra={"issue": issue_number},
        )
        return wt_path

    async def destroy(self, issue_number: int) -> None:
        """Remove the worktree for *issue_number*."""
        wt_path = self._config.worktree_path_for_issue(issue_number)
        if self._config.dry_run:
            logger.info("[dry-run] Would destroy worktree %s", wt_path)
            return

        if wt_path.exists():
            await run_subprocess(
                "git",
                "worktree",
                "remove",
                str(wt_path),
                "--force",
                cwd=self._repo_root,
                gh_token=self._config.gh_token,
            )
            logger.info(
                "Destroyed worktree %s",
                wt_path,
                extra={"issue": issue_number},
            )

        # Also clean up the branch
        branch = self._config.branch_for_issue(issue_number)
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "branch",
                "-D",
                branch,
                cwd=self._repo_root,
                gh_token=self._config.gh_token,
            )

    async def destroy_all(self) -> None:
        """Remove every worktree under the base directory."""
        if not self._base.exists():
            return
        for child in self._base.iterdir():
            if child.is_dir() and child.name.startswith("issue-"):
                try:
                    num = int(child.name.split("-", 1)[1])
                    await self.destroy(num)
                except (ValueError, RuntimeError) as exc:
                    logger.warning("Could not destroy %s: %s", child, exc)

        # Final prune
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "worktree",
                "prune",
                cwd=self._repo_root,
                gh_token=self._config.gh_token,
            )

    async def _fetch_and_merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Fetch and merge main into *branch* inside *worktree_path*.

        Performs the shared three-step sequence: fetch origin, fast-forward
        local branch to match remote, then merge ``origin/main``.  Raises
        ``RuntimeError`` on any failure so callers can decide how to handle it.

        Returns *True* on success.
        """
        await self._fetch_origin_with_retry(
            worktree_path, self._config.main_branch, branch
        )
        await run_subprocess(
            "git",
            "merge",
            "--ff-only",
            f"origin/{branch}",
            cwd=worktree_path,
            gh_token=self._config.gh_token,
        )
        await run_subprocess(
            "git",
            "merge",
            f"origin/{self._config.main_branch}",
            "--no-edit",
            cwd=worktree_path,
            gh_token=self._config.gh_token,
        )
        return True

    async def merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Merge latest main into *branch* inside *worktree_path*.

        First pulls the branch itself so the local copy is in sync with
        the remote, then merges ``origin/main``.  Because this uses merge
        the subsequent push is always fast-forward.

        Returns *True* on success, *False* if conflicts arise.
        """
        try:
            return await self._fetch_and_merge_main(worktree_path, branch)
        except RuntimeError:
            with contextlib.suppress(RuntimeError):
                await run_subprocess(
                    "git",
                    "merge",
                    "--abort",
                    cwd=worktree_path,
                    gh_token=self._config.gh_token,
                )
            return False

    async def start_merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Begin merging main into *branch*, leaving conflicts for manual resolution.

        Like :meth:`merge_main` but does **not** abort on conflict.
        The caller is expected to resolve the conflict markers and
        complete the merge with ``git add . && git commit --no-edit``.

        Returns *True* if the merge completed cleanly (no conflicts),
        *False* if conflicts remain in the working tree.
        """
        try:
            return await self._fetch_and_merge_main(worktree_path, branch)
        except RuntimeError:
            return False

    async def abort_merge(self, worktree_path: Path) -> None:
        """Abort an in-progress merge in *worktree_path*."""
        with contextlib.suppress(RuntimeError):
            await run_subprocess(
                "git",
                "merge",
                "--abort",
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )

    async def get_conflicting_files(self, worktree_path: Path) -> list[str]:
        """Return the list of files with unresolved merge conflicts.

        Runs ``git diff --name-only --diff-filter=U`` in *worktree_path*.
        Returns an empty list on failure.
        """
        try:
            output = await run_subprocess(
                "git",
                "diff",
                "--name-only",
                "--diff-filter=U",
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            return [f.strip() for f in output.strip().splitlines() if f.strip()]
        except RuntimeError:
            logger.warning("Could not get conflicting files in %s", worktree_path)
            return []

    async def get_main_diff_for_files(
        self,
        worktree_path: Path,
        files: list[str],
        max_chars: int = 30_000,
    ) -> str:
        """Return the diff of what changed on main for *files* since divergence.

        Runs ``git merge-base HEAD origin/main`` then
        ``git diff <base>..origin/main -- <files>``.  Truncates at
        *max_chars*.  Returns an empty string on failure or when *files*
        is empty.
        """
        if not files:
            return ""
        try:
            merge_base = await run_subprocess(
                "git",
                "merge-base",
                "HEAD",
                f"origin/{self._config.main_branch}",
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            base_sha = merge_base.strip()
            if not base_sha:
                return ""

            diff_output = await run_subprocess(
                "git",
                "diff",
                f"{base_sha}..origin/{self._config.main_branch}",
                "--",
                *files,
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            result = diff_output.strip()
            if len(result) > max_chars:
                return result[:max_chars] + "\n\n[Diff truncated]"
            return result
        except RuntimeError:
            logger.warning("Could not get main diff for files in %s", worktree_path)
            return ""

    async def get_main_commits_since_diverge(self, worktree_path: Path) -> str:
        """Return recent commits on main since the branch diverged.

        Runs ``git log --oneline HEAD..origin/main`` in *worktree_path*
        (after fetching main) and returns up to 30 commit summaries as a
        newline-separated string.  Returns an empty string on failure.
        """
        try:
            await self._fetch_origin_with_retry(worktree_path, self._config.main_branch)
            output = await run_subprocess(
                "git",
                "log",
                "--oneline",
                f"HEAD..origin/{self._config.main_branch}",
                "-30",
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            return output.strip()
        except RuntimeError:
            logger.warning(
                "Could not get main commits since diverge in %s",
                worktree_path,
            )
            return ""

    # --- environment setup ---

    def _setup_env(self, wt_path: Path) -> None:
        """Set up .env, settings, and node_modules in the worktree."""
        docker = self._config.execution_mode == "docker"
        self._setup_dotenv(wt_path, docker)
        self._setup_claude_settings(wt_path)
        self._setup_node_modules(wt_path, docker)

    def _setup_dotenv(self, wt_path: Path, docker: bool) -> None:
        """Set up .env in the worktree.

        In host mode, .env is symlinked for performance.
        In docker mode, .env is copied and added to .gitignore to prevent
        accidental commits of secrets.
        """
        env_src = self._repo_root / ".env"
        env_dst = wt_path / ".env"
        if env_src.exists() and not env_dst.exists():
            try:
                if docker:
                    shutil.copy2(env_src, env_dst)
                else:
                    env_dst.symlink_to(env_src)
            except OSError:
                logger.debug(
                    "Could not %s %s → %s",
                    "copy" if docker else "symlink",
                    env_src,
                    env_dst,
                    exc_info=True,
                )

        if docker and env_dst.exists():
            gitignore_path = wt_path / ".gitignore"
            try:
                existing = gitignore_path.read_text() if gitignore_path.exists() else ""
                if ".env" not in [ln.strip() for ln in existing.splitlines()]:
                    with gitignore_path.open("a") as f:
                        if existing and not existing.endswith("\n"):
                            f.write("\n")
                        f.write(
                            "# Docker mode: .env is copied — exclude from commits\n"
                            ".env\n"
                        )
            except OSError:
                logger.debug(
                    "Could not update .gitignore at %s",
                    gitignore_path,
                    exc_info=True,
                )

    def _setup_claude_settings(self, wt_path: Path) -> None:
        """Copy .claude/settings.local.json into the worktree (not symlink — agents may modify)."""
        local_settings_src = self._repo_root / ".claude" / "settings.local.json"
        local_settings_dst = wt_path / ".claude" / "settings.local.json"
        if local_settings_src.exists() and not local_settings_dst.exists():
            try:
                local_settings_dst.parent.mkdir(parents=True, exist_ok=True)
                local_settings_dst.write_text(local_settings_src.read_text())
            except OSError:
                logger.debug(
                    "Could not copy settings to %s",
                    local_settings_dst,
                    exc_info=True,
                )

    def _setup_node_modules(self, wt_path: Path, docker: bool) -> None:
        """Set up node_modules for each UI directory in the worktree.

        In host mode, node_modules is symlinked for performance.
        In docker mode, node_modules is copied so the worktree is self-contained.
        """
        for ui_dir in self._ui_dirs:
            nm_src = self._repo_root / ui_dir / "node_modules"
            nm_dst = wt_path / ui_dir / "node_modules"
            if nm_src.exists() and not nm_dst.exists():
                try:
                    nm_dst.parent.mkdir(parents=True, exist_ok=True)
                    if docker:
                        shutil.copytree(nm_src, nm_dst, symlinks=True)
                    else:
                        nm_dst.symlink_to(nm_src)
                except OSError:
                    logger.debug(
                        "Could not %s %s → %s",
                        "copy" if docker else "symlink",
                        nm_src,
                        nm_dst,
                        exc_info=True,
                    )

    async def _configure_git_identity(self, wt_path: Path) -> None:
        """Set git user.name and user.email in the worktree (local scope)."""
        try:
            if self._config.git_user_name:
                await run_subprocess(
                    "git",
                    "config",
                    "user.name",
                    self._config.git_user_name,
                    cwd=wt_path,
                    gh_token=self._config.gh_token,
                )
            if self._config.git_user_email:
                await run_subprocess(
                    "git",
                    "config",
                    "user.email",
                    self._config.git_user_email,
                    cwd=wt_path,
                    gh_token=self._config.gh_token,
                )
        except RuntimeError as exc:
            logger.warning("git identity config failed in %s: %s", wt_path, exc)

    async def _create_venv(self, wt_path: Path) -> None:
        """Create an independent venv in the worktree via ``uv sync``."""
        try:
            await run_subprocess(
                "uv", "sync", cwd=wt_path, gh_token=self._config.gh_token
            )
        except (RuntimeError, FileNotFoundError) as exc:
            logger.warning("uv sync failed in %s: %s", wt_path, exc)

    async def _install_hooks(self, wt_path: Path) -> None:
        """Install git hooks in the worktree.

        In host mode, sets ``core.hooksPath`` to the shared ``.githooks`` dir.
        In docker mode, copies individual hook files into the worktree's git
        hooks directory so the worktree is self-contained.
        """
        if self._config.execution_mode == "docker":
            await self._install_hooks_docker(wt_path)
        else:
            try:
                await run_subprocess(
                    "git",
                    "config",
                    "core.hooksPath",
                    ".githooks",
                    cwd=wt_path,
                    gh_token=self._config.gh_token,
                )
            except RuntimeError as exc:
                logger.warning("git hooks setup failed: %s", exc)

    async def _install_hooks_docker(self, wt_path: Path) -> None:
        """Copy hook files from .githooks/ into the worktree's git hooks dir."""
        githooks_src = self._repo_root / ".githooks"
        if not githooks_src.is_dir():
            logger.debug("No .githooks directory found at %s — skipping", githooks_src)
            return

        # Resolve the actual git hooks directory (worktree .git is a file)
        try:
            hooks_dir_str = await run_subprocess(
                "git",
                "rev-parse",
                "--git-path",
                "hooks",
                cwd=wt_path,
                gh_token=self._config.gh_token,
            )
            hooks_dir = Path(hooks_dir_str.strip())
            if not hooks_dir.is_absolute():
                hooks_dir = wt_path / hooks_dir
        except RuntimeError as exc:
            logger.warning("Could not resolve git hooks path: %s", exc)
            return

        try:
            hooks_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not create git hooks directory %s: %s", hooks_dir, exc
            )
            return

        for hook_file in githooks_src.iterdir():
            if hook_file.is_file():
                dst = hooks_dir / hook_file.name
                try:
                    shutil.copy2(hook_file, dst)
                    dst.chmod(
                        dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                    )
                except OSError:
                    logger.debug(
                        "Could not copy hook %s → %s", hook_file, dst, exc_info=True
                    )
