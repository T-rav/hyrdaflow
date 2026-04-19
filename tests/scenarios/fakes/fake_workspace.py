"""Stateful workspace fake for scenario testing."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

_WorkspaceFaultKind = Literal["permission", "disk_full", "branch_conflict"]


class FakeWorkspace:
    """Tracks worktree create/destroy calls with filesystem paths."""

    def __init__(self, base_path: Path) -> None:
        self._base = base_path
        self.created: list[int] = []
        self.destroyed: list[int] = []
        self._next_fault: _WorkspaceFaultKind | None = None

    def fail_next_create(self, *, kind: _WorkspaceFaultKind) -> None:
        """Inject a single-shot fault into the next create() call."""
        self._next_fault = kind

    async def create(self, issue_number: int, _branch: str) -> Path:
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

    async def sanitize_repo(self) -> None:
        pass
