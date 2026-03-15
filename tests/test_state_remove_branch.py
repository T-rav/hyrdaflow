"""Tests for remove_branch() and get_active_branches() on WorktreeStateMixin."""

from __future__ import annotations

from pathlib import Path

from tests.helpers import make_tracker


class TestRemoveBranch:
    """Unit tests for StateTracker.remove_branch()."""

    def test_remove_existing_branch(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(42, "agent/issue-42")
        assert tracker.get_branch(42) == "agent/issue-42"
        tracker.remove_branch(42)
        assert tracker.get_branch(42) is None

    def test_remove_nonexistent_branch_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.remove_branch(999)  # should not raise
        assert tracker.get_branch(999) is None

    def test_remove_branch_persists(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(10, "agent/issue-10")
        tracker.remove_branch(10)
        # Reload from disk
        reloaded = make_tracker(tmp_path)
        assert reloaded.get_branch(10) is None

    def test_remove_branch_does_not_affect_others(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(1, "agent/issue-1")
        tracker.set_branch(2, "agent/issue-2")
        tracker.remove_branch(1)
        assert tracker.get_branch(1) is None
        assert tracker.get_branch(2) == "agent/issue-2"


class TestGetActiveBranches:
    """Unit tests for StateTracker.get_active_branches()."""

    def test_empty_on_fresh_tracker(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_active_branches() == {}

    def test_returns_int_keyed_mapping(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(42, "agent/issue-42")
        tracker.set_branch(99, "agent/issue-99")
        result = tracker.get_active_branches()
        assert result == {42: "agent/issue-42", 99: "agent/issue-99"}

    def test_reflects_removal(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(1, "agent/issue-1")
        tracker.set_branch(2, "agent/issue-2")
        tracker.remove_branch(1)
        assert tracker.get_active_branches() == {2: "agent/issue-2"}
