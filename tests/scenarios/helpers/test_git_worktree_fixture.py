"""Tests for init_test_worktree helper."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.scenario


def test_init_test_worktree_uses_custom_origin(tmp_path):
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    wt = tmp_path / "wt"
    origin = tmp_path / "custom-origin.git"
    init_test_worktree(wt, origin=origin)
    assert origin.exists()
    assert (origin / "HEAD").exists()


def test_init_test_worktree_multiple_workspaces_no_collision(tmp_path):
    """Two worktrees sharing the same parent can each init cleanly."""
    from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

    wt1 = tmp_path / "worktrees" / "issue-1"
    wt2 = tmp_path / "worktrees" / "issue-2"
    init_test_worktree(wt1, branch="agent/issue-1")
    init_test_worktree(wt2, branch="agent/issue-2")
    assert wt1.exists()
    assert wt2.exists()
