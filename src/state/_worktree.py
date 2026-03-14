"""Worktree and branch tracking state."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")


class WorktreeStateMixin:
    """Methods for worktree and branch tracking."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- worktree tracking ---

    def get_active_worktrees(self) -> dict[int, str]:
        """Return ``{issue_number: worktree_path}`` mapping."""
        result: dict[int, str] = {}
        for k, v in self._data.active_worktrees.items():
            try:
                result[int(k)] = v
            except (ValueError, TypeError):
                logger.warning("Skipping non-integer worktree key: %r", k)
        return result

    def set_worktree(self, issue_number: int, path: str) -> None:
        """Record the worktree filesystem *path* for *issue_number*."""
        self._data.active_worktrees[str(issue_number)] = path
        self.save()

    def remove_worktree(self, issue_number: int) -> None:
        """Remove the worktree mapping for *issue_number* (no-op if absent)."""
        self._data.active_worktrees.pop(str(issue_number), None)
        self.save()

    # --- branch tracking ---

    def set_branch(self, issue_number: int, branch: str) -> None:
        """Record the active *branch* name for *issue_number*."""
        self._data.active_branches[str(issue_number)] = branch
        self.save()

    def get_branch(self, issue_number: int) -> str | None:
        """Return the active branch for *issue_number*, or *None*."""
        return self._data.active_branches.get(str(issue_number))
