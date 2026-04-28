"""FakeGit — in-memory git CLI surface with worktree + corruption modeling."""

from __future__ import annotations

import hashlib
from pathlib import Path


class FakeGit:
    _is_fake_adapter = True

    def __init__(self) -> None:
        self._worktrees: dict[Path, str] = {}
        self._configs: dict[Path, dict[str, str]] = {}
        self._commit_counter = 0
        self._commits: dict[Path, list[str]] = {}
        self._reject_next_push = False

    # --- script API (tests) ---

    def set_corrupted_config(self, cwd: Path, *, key: str, value: str) -> None:
        self._configs.setdefault(cwd, {})[key] = value

    def reject_next_push(self) -> None:
        self._reject_next_push = True

    def active_worktrees(self) -> dict[Path, str]:
        return dict(self._worktrees)

    # --- port methods ---

    async def worktree_add(
        self, path: Path, branch: str, *, new_branch: bool = False
    ) -> None:
        _ = new_branch
        self._worktrees[path] = branch

    async def worktree_remove(self, path: Path, *, force: bool = False) -> None:
        _ = force
        self._worktrees.pop(path, None)

    async def worktree_prune(self) -> None:
        # No-op: FakeGit doesn't track stale refs beyond active_worktrees.
        return

    async def status(self, cwd: Path) -> str:
        _ = cwd
        return ""

    async def commit(self, cwd: Path, message: str) -> str:
        self._commit_counter += 1
        sha = hashlib.sha1(
            f"{cwd}:{self._commit_counter}:{message}".encode(), usedforsecurity=False
        ).hexdigest()
        self._commits.setdefault(cwd, []).append(sha)
        return sha

    async def push(self, cwd: Path, remote: str, branch: str) -> None:
        _ = (cwd, remote, branch)
        if self._reject_next_push:
            self._reject_next_push = False
            msg = "non-fast-forward: push rejected by remote"
            raise RuntimeError(msg)

    async def rev_parse(self, cwd: Path, ref: str) -> str:
        commits = self._commits.get(cwd) or []
        if ref in ("HEAD", "main") and commits:
            return commits[-1]
        return "0" * 40

    async def config_get(self, cwd: Path, key: str) -> str | None:
        return self._configs.get(cwd, {}).get(key)

    async def config_unset(self, cwd: Path, key: str) -> None:
        self._configs.get(cwd, {}).pop(key, None)
