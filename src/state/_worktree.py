"""Worktree and branch tracking state."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

_V = TypeVar("_V")

if TYPE_CHECKING:
    from models import StateData


class WorktreeStateMixin:
    """Methods for worktree and branch tracking."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    @staticmethod
    def _int_keys(d: dict[str, _V]) -> dict[int, _V]: ...  # provided by StateTracker

    # --- worktree tracking ---

    def get_active_worktrees(self) -> dict[int, str]:
        """Return ``{issue_number: worktree_path}`` mapping."""
        return self._int_keys(self._data.active_worktrees)

    def set_worktree(self, issue_number: int, path: str) -> None:
        """Record the worktree filesystem *path* for *issue_number*."""
        self._data.active_worktrees[self._key(issue_number)] = path
        self.save()

    def remove_worktree(self, issue_number: int) -> None:
        """Remove the worktree mapping for *issue_number* (no-op if absent)."""
        self._data.active_worktrees.pop(self._key(issue_number), None)
        self.save()

    # --- branch tracking ---

    def get_active_branches(self) -> dict[int, str]:
        """Return ``{issue_number: branch_name}`` mapping."""
        return self._int_keys(self._data.active_branches)

    def set_branch(self, issue_number: int, branch: str) -> None:
        """Record the active *branch* name for *issue_number*."""
        self._data.active_branches[self._key(issue_number)] = branch
        self.save()

    def get_branch(self, issue_number: int) -> str | None:
        """Return the active branch for *issue_number*, or *None*."""
        return self._data.active_branches.get(self._key(issue_number))

    def remove_branch(self, issue_number: int) -> None:
        """Remove the branch mapping for *issue_number* (no-op if absent)."""
        self._data.active_branches.pop(self._key(issue_number), None)
        self.save()
