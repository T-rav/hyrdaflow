"""Tests that terminal state transitions clean up active_branches and active_workspaces."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import make_tracker


class TestTerminalStateCleanup:
    """mark_issue() with a terminal status removes branch and worktree entries."""

    @pytest.mark.parametrize("status", ["merged", "failed", "completed", "hitl_closed"])
    def test_terminal_status_removes_branch(self, tmp_path: Path, status: str) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(42, "agent/issue-42")
        tracker.mark_issue(42, status)
        assert tracker.get_branch(42) is None

    @pytest.mark.parametrize("status", ["merged", "failed", "completed", "hitl_closed"])
    def test_terminal_status_removes_worktree(
        self, tmp_path: Path, status: str
    ) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(42, "/tmp/wt-42")
        tracker.mark_issue(42, status)
        assert tracker.get_active_workspaces().get(42) is None

    def test_non_terminal_status_preserves_branch(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(42, "agent/issue-42")
        tracker.mark_issue(42, "in_progress")
        assert tracker.get_branch(42) == "agent/issue-42"

    def test_non_terminal_status_preserves_worktree(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(42, "/tmp/wt-42")
        tracker.mark_issue(42, "in_progress")
        assert tracker.get_active_workspaces()[42] == "/tmp/wt-42"

    def test_terminal_cleanup_does_not_affect_other_issues(
        self, tmp_path: Path
    ) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(1, "agent/issue-1")
        tracker.set_branch(2, "agent/issue-2")
        tracker.set_workspace(1, "/tmp/wt-1")
        tracker.set_workspace(2, "/tmp/wt-2")
        tracker.mark_issue(1, "merged")
        assert tracker.get_branch(1) is None
        assert tracker.get_branch(2) == "agent/issue-2"
        assert 1 not in tracker.get_active_workspaces()
        assert tracker.get_active_workspaces()[2] == "/tmp/wt-2"

    def test_terminal_cleanup_persists(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(10, "agent/issue-10")
        tracker.set_workspace(10, "/tmp/wt-10")
        tracker.mark_issue(10, "failed")
        reloaded = make_tracker(tmp_path)
        assert reloaded.get_branch(10) is None
        assert 10 not in reloaded.get_active_workspaces()

    def test_terminal_cleanup_noop_when_no_entries(self, tmp_path: Path) -> None:
        """Cleaning up non-existent entries should not raise."""
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(999, "merged")  # no branch/worktree set
        assert tracker.get_branch(999) is None
