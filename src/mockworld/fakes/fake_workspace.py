"""Stateful workspace fake for scenario testing."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

_WorkspaceFaultKind = Literal["permission", "disk_full", "branch_conflict"]


class FakeWorkspace:
    """Tracks worktree create/destroy calls with filesystem paths."""

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self, base_path: Path) -> None:
        self._base = base_path
        self.created: list[int] = []
        self.destroyed: list[int] = []
        self._next_fault: _WorkspaceFaultKind | None = None

    def fail_next_create(self, *, kind: _WorkspaceFaultKind) -> None:
        """Inject a single-shot fault into the next create() call."""
        self._next_fault = kind

    async def create(self, issue_number: int, branch: str) -> Path:
        fault = self._next_fault
        self._next_fault = None
        if fault == "permission":
            raise PermissionError("FakeWorkspace: permission fault injected")
        if fault == "disk_full":
            raise OSError(28, "FakeWorkspace: disk full")
        if fault == "branch_conflict":
            raise RuntimeError("FakeWorkspace: worktree already exists")
        self.created.append(issue_number)
        path = self._base / f"issue-{issue_number}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def destroy(self, issue_number: int) -> None:
        self.destroyed.append(issue_number)

    async def destroy_all(self) -> None:
        """Remove all managed worktrees (no-op stub)."""

    async def merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Merge main into the worktree (stub — always succeeds)."""
        return True

    async def get_conflicting_files(self, worktree_path: Path) -> list[str]:
        """Return conflicting files in the worktree (stub — always empty)."""
        return []

    async def reset_to_main(self, worktree_path: Path) -> None:
        """Hard-reset worktree to origin/main (no-op stub)."""

    async def post_work_cleanup(
        self, issue_number: int, *, phase: str = "implement"
    ) -> None:
        """Clean up after an issue is done (no-op stub)."""

    async def abort_merge(self, worktree_path: Path) -> None:
        """Abort an in-progress merge (no-op stub)."""

    async def start_merge_main(self, worktree_path: Path, branch: str) -> bool:
        """Begin merging main into branch (stub — always clean)."""
        return True

    async def sanitize_repo(self) -> None:
        pass

    async def enable_rerere(self) -> None:
        """Enable git rerere on the managed repo (no-op stub).

        Production WorkspaceManager flips a config flag; FakeWorkspace
        has no real repo, so this is a no-op. Required because
        ``HydraFlowOrchestrator.run()`` calls ``workspaces.enable_rerere()``
        unconditionally during pipeline boot.
        """
        return None
