"""Tests for workspace — create, destroy, and repo-scoped isolation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import ConfigFactory, make_proc
from workspace import WorkspaceManager

# ---------------------------------------------------------------------------
# WorkspaceManager.create
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for WorkspaceManager.create."""

    @pytest.mark.asyncio
    async def test_create_calls_git_clone_and_checkout(
        self, config, tmp_path: Path
    ) -> None:
        """create should fetch main, clone locally, set origin, fetch, then checkout -b."""
        manager = WorkspaceManager(config)

        # Pre-create the base directory so mkdir doesn't cause issues
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=success_proc
            ) as mock_exec,
            patch.object(
                manager, "_assert_origin_matches_repo", new_callable=AsyncMock
            ),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock),
            patch.object(
                manager,
                "_get_origin_url",
                new_callable=AsyncMock,
                return_value="https://github.com/test/repo.git",
            ),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        calls = mock_exec.call_args_list
        # First call: git clone --local --no-checkout
        assert calls[0].args[:3] == ("git", "clone", "--local")
        assert "--no-checkout" in calls[0].args
        # Second call: git remote set-url origin
        assert calls[1].args[:4] == ("git", "remote", "set-url", "origin")
        # Third call: git fetch origin main
        assert calls[2].args[:3] == ("git", "fetch", "origin")
        # Fourth call: git ls-remote (from _remote_branch_exists mock — skipped)
        # Fifth call: git checkout -b branch origin/main
        assert calls[3].args[:3] == ("git", "checkout", "-b")

    @pytest.mark.asyncio
    async def test_create_fetches_remote_branch_when_exists(
        self, config, tmp_path: Path
    ) -> None:
        """create should fetch the remote branch and checkout instead of creating new."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=success_proc
            ) as mock_exec,
            patch.object(
                manager, "_assert_origin_matches_repo", new_callable=AsyncMock
            ),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock),
            patch.object(
                manager,
                "_get_origin_url",
                new_callable=AsyncMock,
                return_value="https://github.com/test/repo.git",
            ),
            patch.object(
                manager, "_remote_branch_exists", return_value=True
            ) as mock_remote,
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        mock_remote.assert_awaited_once_with("agent/issue-7")
        calls = mock_exec.call_args_list
        # First call: git clone --local --no-checkout
        assert calls[0].args[:3] == ("git", "clone", "--local")
        # Second call: git remote set-url origin
        assert calls[1].args[:4] == ("git", "remote", "set-url", "origin")
        # Third call: git fetch origin main
        assert calls[2].args[:3] == ("git", "fetch", "origin")
        # Fourth call: git fetch with force refspec for the branch
        assert calls[3].args[:3] == ("git", "fetch", "origin")
        assert "+refs/heads/agent/issue-7:refs/heads/agent/issue-7" in calls[3].args
        # Fifth call: git checkout branch (not -b)
        assert calls[4].args[:3] == ("git", "checkout", "agent/issue-7")
        # Should NOT have git checkout -b (new branch)
        for call in calls:
            assert call.args[:3] != ("git", "checkout", "-b"), (
                "Should not create new branch when remote exists"
            )

    @pytest.mark.asyncio
    async def test_create_fresh_branch_when_no_remote(
        self, config, tmp_path: Path
    ) -> None:
        """create should checkout -b from origin/main when no remote branch exists."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=success_proc
            ) as mock_exec,
            patch.object(
                manager, "_assert_origin_matches_repo", new_callable=AsyncMock
            ),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock),
            patch.object(
                manager,
                "_get_origin_url",
                new_callable=AsyncMock,
                return_value="https://github.com/test/repo.git",
            ),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        calls = mock_exec.call_args_list
        # After clone, set-url, and fetch: git checkout -b agent/issue-7 origin/main
        checkout_calls = [c for c in calls if c.args[:3] == ("git", "checkout", "-b")]
        assert len(checkout_calls) == 1
        assert checkout_calls[0].args[3] == "agent/issue-7"

    @pytest.mark.asyncio
    async def test_create_calls_setup_env_create_venv_and_install_hooks(
        self, config, tmp_path: Path
    ) -> None:
        """create should invoke _setup_env, _create_venv, and _install_hooks."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc()

        setup_env = MagicMock()
        create_venv = AsyncMock()
        install_hooks = AsyncMock()

        with (
            patch("asyncio.create_subprocess_exec", return_value=success_proc),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env", setup_env),
            patch.object(manager, "_create_venv", create_venv),
            patch.object(manager, "_install_hooks", install_hooks),
        ):
            result = await manager.create(issue_number=7, branch="agent/issue-7")

        setup_env.assert_called_once()
        create_venv.assert_awaited_once()
        install_hooks.assert_awaited_once()
        assert result == config.worktree_path_for_issue(7)

    @pytest.mark.asyncio
    async def test_create_returns_correct_path(self, config, tmp_path: Path) -> None:
        """create should return <worktree_base>/issue-<number>."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc()

        with (
            patch("asyncio.create_subprocess_exec", return_value=success_proc),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            result = await manager.create(issue_number=99, branch="agent/issue-99")

        assert result == config.worktree_path_for_issue(99)

    @pytest.mark.asyncio
    async def test_create_dry_run_skips_git_commands(
        self, dry_config, tmp_path: Path
    ) -> None:
        """In dry-run mode, create should not call any git subprocesses."""
        manager = WorkspaceManager(dry_config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await manager.create(issue_number=7, branch="agent/issue-7")

        mock_exec.assert_not_called()
        assert result == dry_config.worktree_path_for_issue(7)

    @pytest.mark.asyncio
    async def test_create_raises_when_fetch_origin_main_fails(
        self, config, tmp_path: Path
    ) -> None:
        """create should propagate RuntimeError when 'git fetch origin main' fails."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with (
            patch("asyncio.create_subprocess_exec", return_value=fail_proc),
            pytest.raises(RuntimeError, match="network error"),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

    @pytest.mark.asyncio
    async def test_create_retries_on_origin_main_ref_lock_race(
        self, config, tmp_path: Path
    ) -> None:
        """create should retry when git fetch hits origin/main ref-lock races."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        race_proc = make_proc(
            returncode=1,
            stderr=(
                b"error: cannot lock ref 'refs/remotes/origin/main': is at aaaaaaaa "
                b"but expected bbbbbbbb\n"
                b"! bbbbbbbb..aaaaaaaa main -> origin/main (unable to update local ref)"
            ),
        )
        success_proc = make_proc(returncode=0)

        call_count = 0
        fetch_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count, fetch_count
            call_count += 1
            # Track fetch calls specifically — first fetch races, second succeeds
            if args[:3] == ("git", "fetch", "origin"):
                fetch_count += 1
                if fetch_count == 1:
                    return race_proc
            return success_proc

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
            patch.object(
                manager, "_assert_origin_matches_repo", new_callable=AsyncMock
            ),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock),
            patch.object(
                manager,
                "_get_origin_url",
                new_callable=AsyncMock,
                return_value="https://github.com/test/repo.git",
            ),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            result = await manager.create(issue_number=7, branch="agent/issue-7")

        assert result == config.worktree_path_for_issue(7)
        # clone, set-url, fetch (fail), fetch (retry), ls-remote, checkout -b
        assert call_count >= 4
        sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_serializes_fetch_when_two_workers_start_together(
        self, config, tmp_path: Path
    ) -> None:
        """Concurrent create() calls should never overlap git fetch origin/main."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        fetch_in_flight = 0
        max_fetch_in_flight = 0

        async def fake_run_subprocess(*cmd, **kwargs):
            nonlocal fetch_in_flight, max_fetch_in_flight
            if cmd[:3] == ("git", "fetch", "origin"):
                fetch_in_flight += 1
                max_fetch_in_flight = max(max_fetch_in_flight, fetch_in_flight)
                await asyncio.sleep(0.01)
                fetch_in_flight -= 1
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run_subprocess),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            await asyncio.gather(
                manager.create(issue_number=7, branch="agent/issue-7"),
                manager.create(issue_number=8, branch="agent/issue-8"),
            )

        assert max_fetch_in_flight == 1

    @pytest.mark.asyncio
    async def test_create_raises_when_checkout_fails_after_clone(
        self, config, tmp_path: Path
    ) -> None:
        """create should propagate RuntimeError when 'git checkout -b' fails after clone."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: checkout failed")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # clone, set-url, fetch succeed; checkout -b fails
            if call_count <= 3:
                return success_proc
            return fail_proc

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock),
            patch.object(
                manager, "_assert_origin_matches_repo", new_callable=AsyncMock
            ),
            patch.object(
                manager,
                "_get_origin_url",
                new_callable=AsyncMock,
                return_value="https://github.com/test/repo.git",
            ),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            pytest.raises(RuntimeError, match="checkout failed"),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

    @pytest.mark.asyncio
    async def test_create_propagates_setup_env_error(
        self, config, tmp_path: Path
    ) -> None:
        """create should propagate OSError from _setup_env (not wrapped in try/except)."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)

        with (
            patch("asyncio.create_subprocess_exec", return_value=success_proc),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(
                manager, "_setup_env", side_effect=OSError("Permission denied")
            ),
            pytest.raises(OSError, match="Permission denied"),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

    @pytest.mark.asyncio
    async def test_create_venv_failure_does_not_block_create(
        self, config, tmp_path: Path
    ) -> None:
        """create should return a valid path even when uv sync fails inside _create_venv."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(returncode=1, stderr=b"uv sync failed")

        async def fake_exec(*args, **kwargs):
            if args[0:2] == ("uv", "sync"):
                return fail_proc
            return success_proc

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
        ):
            result = await manager.create(issue_number=7, branch="agent/issue-7")

        # _create_venv catches RuntimeError internally, so create completes
        assert result == config.worktree_path_for_issue(7)

    @pytest.mark.asyncio
    async def test_create_cleans_up_on_checkout_failure(
        self, config, tmp_path: Path
    ) -> None:
        """Cleanup should remove cloned directory when checkout fails."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: checkout failed")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # clone, set-url, fetch succeed; checkout -b fails
            if call_count <= 3:
                return success_proc
            return fail_proc

        wt_path = config.worktree_path_for_issue(7)
        # Create the directory so cleanup finds it
        wt_path.mkdir(parents=True, exist_ok=True)

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            patch.object(
                manager, "_assert_origin_matches_repo", new_callable=AsyncMock
            ),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock),
            patch.object(
                manager,
                "_get_origin_url",
                new_callable=AsyncMock,
                return_value="https://github.com/test/repo.git",
            ),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            pytest.raises(RuntimeError, match="checkout failed"),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        # Cleanup should have removed the cloned directory via shutil.rmtree
        # (ignore_errors=True means it won't fail even if partially cleaned)
        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_create_cleans_up_worktree_when_setup_env_fails(
        self, config, tmp_path: Path
    ) -> None:
        """Cleanup should remove cloned directory when post-creation setup fails."""
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        wt_path = config.worktree_path_for_issue(7)
        # Pre-create the directory so cleanup finds it
        wt_path.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)

        with (
            patch("asyncio.create_subprocess_exec", return_value=success_proc),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(
                manager, "_setup_env", side_effect=OSError("Permission denied")
            ),
            pytest.raises(OSError, match="Permission denied"),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        # Cleanup should have removed the cloned directory via shutil.rmtree
        assert not wt_path.exists()


# ---------------------------------------------------------------------------
# WorkspaceManager.destroy
# ---------------------------------------------------------------------------


class TestDestroy:
    """Tests for WorkspaceManager.destroy."""

    @pytest.mark.asyncio
    async def test_destroy_removes_directory(self, config, tmp_path: Path) -> None:
        """destroy should call shutil.rmtree on the workspace directory."""
        manager = WorkspaceManager(config)

        # Simulate existing worktree path
        wt_path = config.worktree_path_for_issue(7)
        wt_path.mkdir(parents=True, exist_ok=True)

        await manager.destroy(issue_number=7)

        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_destroy_handles_non_existent_worktree_gracefully(
        self, config, tmp_path: Path
    ) -> None:
        """destroy should not crash if the worktree directory does not exist."""
        manager = WorkspaceManager(config)

        # wt_path does NOT exist — destroy should not raise
        await manager.destroy(issue_number=999)

    @pytest.mark.asyncio
    async def test_destroy_tolerates_missing_branch(
        self, config, tmp_path: Path
    ) -> None:
        """destroy should complete without error even if directory is already gone."""
        manager = WorkspaceManager(config)

        # Don't create the directory — destroy should handle gracefully
        await manager.destroy(issue_number=7)

    @pytest.mark.asyncio
    async def test_destroy_removes_existing_directory(
        self, config, tmp_path: Path
    ) -> None:
        """destroy should remove the workspace directory via shutil.rmtree."""
        manager = WorkspaceManager(config)

        wt_path = config.worktree_path_for_issue(7)
        wt_path.mkdir(parents=True, exist_ok=True)
        (wt_path / "somefile.txt").write_text("content")

        await manager.destroy(issue_number=7)

        assert not wt_path.exists()

    @pytest.mark.asyncio
    async def test_destroy_dry_run_skips_removal(
        self, dry_config, tmp_path: Path
    ) -> None:
        """In dry-run mode, destroy should not remove the directory."""
        manager = WorkspaceManager(dry_config)

        wt_path = dry_config.worktree_path_for_issue(7)
        wt_path.mkdir(parents=True, exist_ok=True)

        await manager.destroy(issue_number=7)

        # In dry-run mode, the directory should still exist
        assert wt_path.exists()


# ---------------------------------------------------------------------------
# WorkspaceManager.destroy_all
# ---------------------------------------------------------------------------


class TestDestroyAll:
    """Tests for WorkspaceManager.destroy_all."""

    @pytest.mark.asyncio
    async def test_destroy_all_iterates_issue_directories(
        self, config, tmp_path: Path
    ) -> None:
        """destroy_all should call destroy for each issue-N directory."""
        manager = WorkspaceManager(config)

        # Create two issue directories in the repo-scoped subdirectory
        repo_base = config.worktree_base / config.repo_slug
        (repo_base / "issue-1").mkdir(parents=True, exist_ok=True)
        (repo_base / "issue-2").mkdir(parents=True, exist_ok=True)

        destroyed: list[int] = []

        async def fake_destroy(issue_number: int) -> None:
            destroyed.append(issue_number)

        with patch.object(manager, "destroy", side_effect=fake_destroy):
            await manager.destroy_all()

        assert sorted(destroyed) == [1, 2]

    @pytest.mark.asyncio
    async def test_destroy_all_noop_when_base_missing(self, config) -> None:
        """destroy_all should return immediately if worktree_base does not exist."""
        manager = WorkspaceManager(config)
        # config.worktree_base was NOT created

        with patch.object(manager, "destroy", new_callable=AsyncMock) as mock_destroy:
            await manager.destroy_all()

        mock_destroy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_destroy_all_ignores_non_issue_dirs(
        self, config, tmp_path: Path
    ) -> None:
        """destroy_all should skip directories not named issue-N."""
        manager = WorkspaceManager(config)

        repo_base = config.worktree_base / config.repo_slug
        (repo_base / "random-dir").mkdir(parents=True, exist_ok=True)
        (repo_base / "issue-5").mkdir(parents=True, exist_ok=True)

        destroyed: list[int] = []

        async def fake_destroy(issue_number: int) -> None:
            destroyed.append(issue_number)

        with patch.object(manager, "destroy", side_effect=fake_destroy):
            await manager.destroy_all()

        assert destroyed == [5]


# ---------------------------------------------------------------------------
# Repo-scoped isolation
# ---------------------------------------------------------------------------


class TestRepoScopedPaths:
    """Verify worktree paths are namespaced by repo slug."""

    def test_worktree_path_includes_repo_slug(self, config) -> None:
        """worktree_path_for_issue should include repo_slug in the path."""
        path = config.worktree_path_for_issue(42)
        assert config.repo_slug in str(path)
        assert path.name == "issue-42"
        assert path.parent.name == config.repo_slug

    def test_two_repos_have_distinct_paths(self, tmp_path: Path) -> None:
        """Two different repos should have non-overlapping worktree paths."""
        cfg_a = ConfigFactory.create(
            repo="org/repo-a",
            worktree_base=tmp_path / "worktrees",
            repo_root=tmp_path / "a",
        )
        cfg_b = ConfigFactory.create(
            repo="org/repo-b",
            worktree_base=tmp_path / "worktrees",
            repo_root=tmp_path / "b",
        )
        path_a = cfg_a.worktree_path_for_issue(10)
        path_b = cfg_b.worktree_path_for_issue(10)
        assert path_a != path_b
        assert "org-repo-a" in str(path_a)
        assert "org-repo-b" in str(path_b)


class TestPerRepoWorktreeLock:
    """Verify per-repo locking prevents concurrent worktree operations."""

    @pytest.mark.asyncio
    async def test_create_delegates_to_create_unlocked(self, config) -> None:
        """create should delegate to _create_unlocked under the lock."""
        manager = WorkspaceManager(config)

        mock_create = AsyncMock(return_value=config.worktree_path_for_issue(7))
        with patch.object(manager, "_create_unlocked", mock_create):
            result = await manager.create(7, "agent/issue-7")

        mock_create.assert_awaited_once_with(7, "agent/issue-7")
        assert result == config.worktree_path_for_issue(7)

    def test_same_repo_gets_same_lock(self, config) -> None:
        """Two managers for the same repo should share the same lock."""
        manager_a = WorkspaceManager(config)
        manager_b = WorkspaceManager(config)
        assert manager_a._repo_workspace_lock() is manager_b._repo_workspace_lock()

    def test_different_repos_get_different_locks(self, tmp_path: Path) -> None:
        """Two managers for different repos should have independent locks."""
        cfg_a = ConfigFactory.create(
            repo="org/alpha",
            worktree_base=tmp_path / "wt",
            repo_root=tmp_path / "a",
        )
        cfg_b = ConfigFactory.create(
            repo="org/beta",
            worktree_base=tmp_path / "wt",
            repo_root=tmp_path / "b",
        )
        lock_a = WorkspaceManager(cfg_a)._repo_workspace_lock()
        lock_b = WorkspaceManager(cfg_b)._repo_workspace_lock()
        assert lock_a is not lock_b


class TestDestroyAllRepoScoped:
    """Verify destroy_all only cleans the current repo's worktrees."""

    @pytest.mark.asyncio
    async def test_destroy_all_only_targets_repo_scoped_dir(
        self, tmp_path: Path
    ) -> None:
        """destroy_all should remove worktrees under the repo-scoped directory."""
        cfg = ConfigFactory.create(
            repo="org/alpha",
            worktree_base=tmp_path / "worktrees",
            repo_root=tmp_path / "repo",
        )
        manager = WorkspaceManager(cfg)

        # Create repo-scoped worktree dirs
        alpha_base = tmp_path / "worktrees" / "org-alpha"
        (alpha_base / "issue-1").mkdir(parents=True)
        (alpha_base / "issue-2").mkdir(parents=True)

        # Create another repo's worktree (should NOT be destroyed)
        beta_base = tmp_path / "worktrees" / "org-beta"
        (beta_base / "issue-1").mkdir(parents=True)

        destroyed: list[int] = []

        async def fake_destroy(issue_number: int) -> None:
            destroyed.append(issue_number)

        with patch.object(manager, "destroy", side_effect=fake_destroy):
            await manager.destroy_all()

        assert sorted(destroyed) == [1, 2]
        # Beta repo's worktree should still exist
        assert (beta_base / "issue-1").exists()
