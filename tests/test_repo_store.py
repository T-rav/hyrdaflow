"""Tests for repo_store.py — clone_config_for_repo."""

from __future__ import annotations

from pathlib import Path

from repo_store import clone_config_for_repo
from tests.helpers import ConfigFactory


class TestCloneConfigForRepo:
    def test_overrides_repo_and_repo_root(self, tmp_path: Path):
        base = ConfigFactory.create(repo="org/base", repo_root=tmp_path / "base")
        new_root = tmp_path / "new-repo"
        new_root.mkdir()
        cloned = clone_config_for_repo(base, repo="org/new-repo", repo_root=new_root)
        assert cloned.repo == "org/new-repo"
        assert cloned.repo_root == new_root

    def test_preserves_non_identity_fields(self, tmp_path: Path):
        base = ConfigFactory.create(
            repo="org/base",
            repo_root=tmp_path / "base",
            max_workers=5,
            poll_interval=30,
            model="opus",
        )
        new_root = tmp_path / "other"
        new_root.mkdir()
        cloned = clone_config_for_repo(base, repo="org/other", repo_root=new_root)
        assert cloned.max_workers == 5
        assert cloned.poll_interval == 30
        assert cloned.model == "opus"

    def test_returns_independent_config(self, tmp_path: Path):
        base = ConfigFactory.create(repo="org/base", repo_root=tmp_path / "base")
        new_root = tmp_path / "fork"
        new_root.mkdir()
        cloned = clone_config_for_repo(base, repo="org/fork", repo_root=new_root)
        # Changing the clone should not affect the base
        assert cloned is not base
        assert cloned.repo != base.repo
