"""Stateful workspace fake for scenario testing."""

from __future__ import annotations

from pathlib import Path


class FakeWorkspace:
    """Tracks worktree create/destroy calls with filesystem paths."""

    def __init__(self, base_path: Path) -> None:
        self._base = base_path
        self.created: list[int] = []
        self.destroyed: list[int] = []

    async def create(self, issue_number: int, _branch: str) -> Path:
        self.created.append(issue_number)
        path = self._base / f"issue-{issue_number}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def destroy(self, issue_number: int) -> None:
        self.destroyed.append(issue_number)

    async def sanitize_repo(self) -> None:
        pass
