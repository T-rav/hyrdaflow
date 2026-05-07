"""FakeGit unit tests — worktree lifecycle, corruption modes, commit/push."""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_git import FakeGit
from tests.scenarios.ports import GitPort


def test_fake_git_satisfies_port() -> None:
    assert isinstance(FakeGit(), GitPort)


async def test_worktree_add_tracks_branch(tmp_path: Path) -> None:
    fake = FakeGit()
    wt = tmp_path / "wt"
    await fake.worktree_add(wt, "feature/x", new_branch=True)
    assert fake.active_worktrees()[wt] == "feature/x"


async def test_worktree_remove_clears(tmp_path: Path) -> None:
    fake = FakeGit()
    wt = tmp_path / "wt"
    await fake.worktree_add(wt, "feature/x", new_branch=True)
    await fake.worktree_remove(wt)
    assert wt not in fake.active_worktrees()


async def test_core_worktree_corruption_detected(tmp_path: Path) -> None:
    fake = FakeGit()
    fake.script_set_corrupted_config(tmp_path, key="core.worktree", value="/workspace")
    assert await fake.config_get(tmp_path, "core.worktree") == "/workspace"
    await fake.config_unset(tmp_path, "core.worktree")
    assert await fake.config_get(tmp_path, "core.worktree") is None


async def test_commit_returns_fake_sha(tmp_path: Path) -> None:
    fake = FakeGit()
    sha1 = await fake.commit(tmp_path, "first")
    sha2 = await fake.commit(tmp_path, "second")
    assert sha1 != sha2 and len(sha1) == 40


async def test_push_rejects_when_scripted(tmp_path: Path) -> None:
    fake = FakeGit()
    fake.reject_next_push()
    with pytest.raises(RuntimeError, match="non-fast-forward"):
        await fake.push(tmp_path, "origin", "main")
