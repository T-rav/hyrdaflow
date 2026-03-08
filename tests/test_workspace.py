"""Tests for dx/hydraflow/worktree.py — WorkspaceManager."""

from __future__ import annotations

import asyncio
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import make_docker_manager, make_proc
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
        from tests.helpers import ConfigFactory

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
        from tests.helpers import ConfigFactory

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
        from tests.helpers import ConfigFactory

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


# ---------------------------------------------------------------------------
# WorkspaceManager._fetch_and_merge_main
# ---------------------------------------------------------------------------


class TestFetchAndMergeMain:
    """Tests for WorkspaceManager._fetch_and_merge_main."""

    @pytest.mark.asyncio
    async def test_success_returns_true(self, config, tmp_path: Path) -> None:
        """_fetch_and_merge_main should return True when all 3 git commands succeed."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch("asyncio.create_subprocess_exec", return_value=success_proc):
            result = await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_fetch_failure_raises_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """_fetch_and_merge_main should raise RuntimeError when fetch fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with (
            patch("asyncio.create_subprocess_exec", return_value=fail_proc),
            pytest.raises(RuntimeError, match="network error"),
        ):
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

    @pytest.mark.asyncio
    async def test_ff_only_merge_failure_raises_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """_fetch_and_merge_main should raise RuntimeError when ff-only merge fails."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: not a fast-forward")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return success_proc  # fetch succeeds
            return fail_proc  # ff-only merge fails

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            pytest.raises(RuntimeError, match="not a fast-forward"),
        ):
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

    @pytest.mark.asyncio
    async def test_main_merge_failure_raises_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """_fetch_and_merge_main should raise RuntimeError when merge origin/main fails."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)
        fail_proc = make_proc(
            returncode=1, stderr=b"CONFLICT (content): Merge conflict"
        )

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return success_proc  # fetch + ff-only succeed
            return fail_proc  # merge origin/main fails

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            pytest.raises(RuntimeError, match="Merge conflict"),
        ):
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

    @pytest.mark.asyncio
    async def test_correct_git_commands(self, config, tmp_path: Path) -> None:
        """_fetch_and_merge_main should issue the 3 correct git commands in order."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._fetch_and_merge_main(tmp_path, "agent/issue-7")

        calls = mock_exec.call_args_list
        assert len(calls) == 3
        # 1. git fetch origin main agent/issue-7
        assert calls[0].args[:3] == ("git", "fetch", "origin")
        assert config.main_branch in calls[0].args
        assert "agent/issue-7" in calls[0].args
        # 2. git merge --ff-only origin/agent/issue-7
        assert calls[1].args[:3] == ("git", "merge", "--ff-only")
        assert calls[1].args[3] == "origin/agent/issue-7"
        # 3. git merge origin/main --no-edit
        assert calls[2].args[:2] == ("git", "merge")
        assert f"origin/{config.main_branch}" in calls[2].args
        assert "--no-edit" in calls[2].args


# ---------------------------------------------------------------------------
# WorkspaceManager.merge_main
# ---------------------------------------------------------------------------


class TestMergeMain:
    """Tests for WorkspaceManager.merge_main."""

    @pytest.mark.asyncio
    async def test_merge_main_success_returns_true(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should return True when fetch, ff-pull, and merge succeed."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch("asyncio.create_subprocess_exec", return_value=success_proc):
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_merge_main_conflict_aborts_and_returns_false(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should abort and return False when conflicts occur."""
        manager = WorkspaceManager(config)

        success_proc = make_proc(returncode=0)
        merge_fail_proc = make_proc(
            returncode=1, stderr=b"CONFLICT (content): Merge conflict"
        )
        abort_proc = make_proc(returncode=0)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return success_proc  # git fetch + ff-only merge succeed
            if call_count == 3:
                return merge_fail_proc  # git merge origin/main fails
            return abort_proc  # git merge --abort

        with patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ) as mock_exec:
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is False
        # Verify abort was called
        abort_calls = [c for c in mock_exec.call_args_list if "--abort" in c.args]
        assert len(abort_calls) == 1

    @pytest.mark.asyncio
    async def test_merge_main_fetch_failure_returns_false(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should return False if the initial fetch fails."""
        manager = WorkspaceManager(config)

        fetch_fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")
        abort_proc = make_proc(returncode=0)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fetch_fail_proc
            return abort_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is False

    @pytest.mark.asyncio
    async def test_merge_main_retries_ref_lock_fetch_race_and_succeeds(
        self, config, tmp_path: Path
    ) -> None:
        """merge_main should retry fetch lock-race errors and complete successfully."""
        manager = WorkspaceManager(config)

        lock_error = RuntimeError(
            "Command ('git', 'fetch', 'origin', 'main') failed (rc=1): "
            "error: cannot lock ref 'refs/remotes/origin/main': is at aaaaaaaa "
            "but expected bbbbbbbb\n"
            "! bbbbbbbb..aaaaaaaa main -> origin/main (unable to update local ref)"
        )
        calls: list[tuple[str, ...]] = []
        fetch_failures = 0

        async def fake_run_subprocess(*cmd, **kwargs):
            nonlocal fetch_failures
            calls.append(tuple(str(p) for p in cmd))
            if cmd[:3] == ("git", "fetch", "origin"):
                if fetch_failures == 0:
                    fetch_failures += 1
                    raise lock_error
                return ""
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run_subprocess),
            patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            result = await manager.merge_main(tmp_path, "agent/issue-7")

        assert result is True
        fetch_calls = [c for c in calls if c[:3] == ("git", "fetch", "origin")]
        assert len(fetch_calls) == 2  # first fetch failed, second fetch retried
        sleep_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# WorkspaceManager._delete_local_branch
# ---------------------------------------------------------------------------


class TestDeleteLocalBranch:
    """Tests for WorkspaceManager._delete_local_branch."""

    @pytest.mark.asyncio
    async def test_deletes_existing_branch(self, config, tmp_path: Path) -> None:
        """Should call git branch -D for the given branch."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._delete_local_branch("agent/issue-7")

        mock_exec.assert_called_once()
        assert mock_exec.call_args.args[:4] == ("git", "branch", "-D", "agent/issue-7")

    @pytest.mark.asyncio
    async def test_swallows_error_when_branch_missing(
        self, config, tmp_path: Path
    ) -> None:
        """Should not raise when the branch does not exist."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"error: branch not found")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            # Should not raise
            await manager._delete_local_branch("agent/issue-999")


# ---------------------------------------------------------------------------
# WorkspaceManager._remote_branch_exists
# ---------------------------------------------------------------------------


class TestRemoteBranchExists:
    """Tests for WorkspaceManager._remote_branch_exists."""

    @pytest.mark.asyncio
    async def test_returns_true_when_ls_remote_has_output(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=0, stdout=b"abc123\trefs/heads/agent/issue-7")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager._remote_branch_exists("agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_ls_remote_empty(
        self, config, tmp_path: Path
    ) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=0, stdout=b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager._remote_branch_exists("agent/issue-99")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self, config, tmp_path: Path) -> None:
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager._remote_branch_exists("agent/issue-7")

        assert result is False


# ---------------------------------------------------------------------------
# WorkspaceManager._setup_env
# ---------------------------------------------------------------------------


class TestSetupEnv:
    """Tests for WorkspaceManager._setup_env."""

    def test_setup_env_does_not_symlink_venv(self, config, tmp_path: Path) -> None:
        """_setup_env should NOT create a symlink for venv/ (independent venvs via uv sync)."""
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        # Create fake repo structure
        repo_root.mkdir(parents=True, exist_ok=True)
        venv_src = repo_root / "venv"
        venv_src.mkdir()

        manager._setup_env(wt_path)

        venv_dst = wt_path / "venv"
        assert not venv_dst.exists()

    def test_setup_env_symlinks_dotenv(self, config, tmp_path: Path) -> None:
        """_setup_env should create a symlink for .env if source exists."""
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        repo_root.mkdir(parents=True, exist_ok=True)
        env_src = repo_root / ".env"
        env_src.write_text("SLACK_BOT_TOKEN=test")

        manager._setup_env(wt_path)

        env_dst = wt_path / ".env"
        assert env_dst.is_symlink()

    def test_setup_env_copies_settings_local_json(self, config, tmp_path: Path) -> None:
        """_setup_env should copy (not symlink) .claude/settings.local.json."""
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        repo_root.mkdir(parents=True, exist_ok=True)
        claude_dir = repo_root / ".claude"
        claude_dir.mkdir()
        settings_src = claude_dir / "settings.local.json"
        settings_src.write_text('{"allowed": []}')

        manager._setup_env(wt_path)

        settings_dst = wt_path / ".claude" / "settings.local.json"
        assert settings_dst.exists()
        assert not settings_dst.is_symlink(), (
            "settings.local.json must be copied, not symlinked"
        )
        assert settings_dst.read_text() == '{"allowed": []}'

    def test_setup_env_symlinks_node_modules(self, config, tmp_path: Path) -> None:
        """_setup_env should symlink node_modules for each detected UI directory."""
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        # Create node_modules under the default "ui" dir (from config.ui_dirs)
        ui_nm_src = repo_root / "ui" / "node_modules"
        ui_nm_src.mkdir(parents=True)

        manager._setup_env(wt_path)

        ui_nm_dst = wt_path / "ui" / "node_modules"
        assert ui_nm_dst.is_symlink()

    def test_setup_env_skips_missing_sources(self, config, tmp_path: Path) -> None:
        """_setup_env should not create any symlinks when source dirs are absent."""
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        # No venv, .env, or node_modules present
        manager._setup_env(wt_path)

        assert not (wt_path / "venv").exists()
        assert not (wt_path / ".env").exists()
        assert not (wt_path / ".claude" / "settings.local.json").exists()

    def test_setup_env_does_not_overwrite_existing_symlinks(
        self, config, tmp_path: Path
    ) -> None:
        """_setup_env should not recreate a symlink that already exists."""
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("EXISTING=true")

        env_dst = wt_path / ".env"
        env_dst.symlink_to(env_src)

        # Should not raise
        manager._setup_env(wt_path)
        assert env_dst.is_symlink()

    def test_setup_env_handles_symlink_oserror(self, config, tmp_path: Path) -> None:
        """_setup_env should handle OSError on symlink and continue."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        # Create .env source so the symlink path is entered
        env_src = repo_root / ".env"
        env_src.write_text("SECRET=val")

        # Also create node_modules source under a detected UI dir
        ui_nm_src = repo_root / "ui" / "node_modules"
        ui_nm_src.mkdir(parents=True)

        with patch.object(Path, "symlink_to", side_effect=OSError("perm denied")):
            manager._setup_env(wt_path)  # should not raise

    def test_setup_env_handles_copy_oserror(self, config, tmp_path: Path) -> None:
        """_setup_env should handle OSError when copying settings and continue."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        # Create settings source
        claude_dir = repo_root / ".claude"
        claude_dir.mkdir()
        settings_src = claude_dir / "settings.local.json"
        settings_src.write_text('{"allowed": []}')

        with patch.object(Path, "write_text", side_effect=OSError("read-only")):
            manager._setup_env(wt_path)  # should not raise


# ---------------------------------------------------------------------------
# WorkspaceManager._setup_dotenv
# ---------------------------------------------------------------------------


class TestSetupDotenv:
    """Tests for WorkspaceManager._setup_dotenv."""

    def test_host_mode_symlinks_dotenv(self, config, tmp_path: Path) -> None:
        """In host mode, _setup_dotenv should symlink .env."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        env_src = repo_root / ".env"
        env_src.write_text("SECRET=val")

        manager._setup_dotenv(wt_path, docker=False)

        env_dst = wt_path / ".env"
        assert env_dst.is_symlink()

    def test_docker_mode_copies_dotenv_and_updates_gitignore(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, _setup_dotenv should copy .env and add it to .gitignore."""
        manager = make_docker_manager(tmp_path)
        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        env_src = repo_root / ".env"
        env_src.write_text("SECRET=docker")

        manager._setup_dotenv(wt_path, docker=True)

        env_dst = wt_path / ".env"
        assert env_dst.exists()
        assert not env_dst.is_symlink()
        assert env_dst.read_text() == "SECRET=docker"

        gitignore = wt_path / ".gitignore"
        assert gitignore.exists()
        assert ".env" in [ln.strip() for ln in gitignore.read_text().splitlines()]

    def test_source_absent_is_noop(self, config, tmp_path: Path) -> None:
        """_setup_dotenv should be a no-op when .env source doesn't exist."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        # No .env file in repo_root
        manager._setup_dotenv(wt_path, docker=False)

        assert not (wt_path / ".env").exists()


# ---------------------------------------------------------------------------
# WorkspaceManager._setup_claude_settings
# ---------------------------------------------------------------------------


class TestSetupClaudeSettings:
    """Tests for WorkspaceManager._setup_claude_settings."""

    def test_copies_settings_file(self, config, tmp_path: Path) -> None:
        """_setup_claude_settings should copy settings.local.json into worktree."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        claude_dir = repo_root / ".claude"
        claude_dir.mkdir()
        settings_src = claude_dir / "settings.local.json"
        settings_src.write_text('{"allowed": []}')

        manager._setup_claude_settings(wt_path)

        settings_dst = wt_path / ".claude" / "settings.local.json"
        assert settings_dst.exists()
        assert not settings_dst.is_symlink()
        assert settings_dst.read_text() == '{"allowed": []}'

    def test_source_absent_is_noop(self, config, tmp_path: Path) -> None:
        """_setup_claude_settings should be a no-op when settings.local.json doesn't exist."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        # No .claude/settings.local.json in repo_root
        manager._setup_claude_settings(wt_path)

        assert not (wt_path / ".claude" / "settings.local.json").exists()

    def test_oserror_during_write_is_suppressed(self, config, tmp_path: Path) -> None:
        """_setup_claude_settings should suppress OSError during file write."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        claude_dir = repo_root / ".claude"
        claude_dir.mkdir()
        settings_src = claude_dir / "settings.local.json"
        settings_src.write_text('{"allowed": []}')

        with patch.object(Path, "write_text", side_effect=OSError("read-only")):
            manager._setup_claude_settings(wt_path)  # should not raise


# ---------------------------------------------------------------------------
# WorkspaceManager._setup_node_modules
# ---------------------------------------------------------------------------


class TestSetupNodeModules:
    """Tests for WorkspaceManager._setup_node_modules."""

    def test_host_mode_symlinks_node_modules(self, config, tmp_path: Path) -> None:
        """In host mode, _setup_node_modules should symlink node_modules."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        ui_nm_src = repo_root / "ui" / "node_modules"
        ui_nm_src.mkdir(parents=True)

        manager._setup_node_modules(wt_path, docker=False)

        ui_nm_dst = wt_path / "ui" / "node_modules"
        assert ui_nm_dst.is_symlink()

    def test_docker_mode_copies_node_modules(self, tmp_path: Path) -> None:
        """In docker mode, _setup_node_modules should copy node_modules."""
        manager = make_docker_manager(tmp_path)
        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        ui_nm_src = repo_root / "ui" / "node_modules"
        ui_nm_src.mkdir(parents=True)
        (ui_nm_src / "pkg").mkdir()
        (ui_nm_src / "pkg" / "index.js").write_text("exports = {}")

        manager._setup_node_modules(wt_path, docker=True)

        ui_nm_dst = wt_path / "ui" / "node_modules"
        assert ui_nm_dst.exists()
        assert not ui_nm_dst.is_symlink()
        assert (ui_nm_dst / "pkg" / "index.js").read_text() == "exports = {}"

    def test_multiple_ui_dirs_all_symlinked(self, tmp_path: Path) -> None:
        """_setup_node_modules should symlink node_modules for every UI directory."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            ui_dirs=["frontend", "admin"],
        )
        manager = WorkspaceManager(cfg)
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        (repo_root / "frontend" / "node_modules").mkdir(parents=True)
        (repo_root / "admin" / "node_modules").mkdir(parents=True)

        manager._setup_node_modules(wt_path, docker=False)

        assert (wt_path / "frontend" / "node_modules").is_symlink()
        assert (wt_path / "admin" / "node_modules").is_symlink()


# ---------------------------------------------------------------------------
# WorkspaceManager._configure_git_identity
# ---------------------------------------------------------------------------


class TestConfigureGitIdentity:
    """Tests for WorkspaceManager._configure_git_identity."""

    @staticmethod
    def _clear_git_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "HYDRAFLOW_GIT_USER_NAME",
            "HYDRAFLOW_GIT_USER_EMAIL",
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)

    @pytest.mark.asyncio
    async def test_sets_user_name_and_email(self, tmp_path: Path) -> None:
        """Should run git config for both user.name and user.email."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            git_user_name="Bot",
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._configure_git_identity(tmp_path)

        calls = mock_exec.call_args_list
        assert len(calls) == 2
        assert calls[0].args == ("git", "config", "user.name", "Bot")
        assert calls[1].args == ("git", "config", "user.email", "bot@example.com")

    @pytest.mark.asyncio
    async def test_skips_when_both_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should not run any git config commands when identity is empty."""
        self._clear_git_identity_env(monkeypatch)

        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            await manager._configure_git_identity(tmp_path)

        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_only_name_when_email_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should only set user.name when email is empty."""
        self._clear_git_identity_env(monkeypatch)

        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            git_user_name="Bot",
            git_user_email="",
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._configure_git_identity(tmp_path)

        calls = mock_exec.call_args_list
        assert len(calls) == 1
        assert calls[0].args == ("git", "config", "user.name", "Bot")

    @pytest.mark.asyncio
    async def test_sets_only_email_when_name_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should only set user.email when name is empty."""
        self._clear_git_identity_env(monkeypatch)

        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            git_user_name="",
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._configure_git_identity(tmp_path)

        calls = mock_exec.call_args_list
        assert len(calls) == 1
        assert calls[0].args == ("git", "config", "user.email", "bot@example.com")

    @pytest.mark.asyncio
    async def test_runtime_error_does_not_raise(self, tmp_path: Path) -> None:
        """_configure_git_identity should log warning and continue on RuntimeError."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            git_user_name="Bot",
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: config error")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            # Should not raise — logs warning and continues
            await manager._configure_git_identity(tmp_path)

    @pytest.mark.asyncio
    async def test_called_during_create(self, tmp_path: Path) -> None:
        """_configure_git_identity should be called during create()."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            git_user_name="Bot",
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)
        cfg.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc()
        configure_identity = AsyncMock()

        with (
            patch("asyncio.create_subprocess_exec", return_value=success_proc),
            patch.object(manager, "_remote_branch_exists", return_value=False),
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_configure_git_identity", configure_identity),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        configure_identity.assert_awaited_once()


# ---------------------------------------------------------------------------
# WorkspaceManager._create_venv
# ---------------------------------------------------------------------------


class TestCreateVenv:
    """Tests for WorkspaceManager._create_venv."""

    @pytest.mark.asyncio
    async def test_create_venv_runs_uv_sync(self, config, tmp_path: Path) -> None:
        """_create_venv should run 'uv sync' in the worktree."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._create_venv(tmp_path)

        mock_exec.assert_called_once()
        assert mock_exec.call_args.args[:2] == ("uv", "sync")

    @pytest.mark.asyncio
    async def test_create_venv_swallows_errors(self, config, tmp_path: Path) -> None:
        """_create_venv should not propagate errors if uv sync fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"uv not found")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            # Should not raise
            await manager._create_venv(tmp_path)

    @pytest.mark.asyncio
    async def test_create_venv_swallows_file_not_found_error(
        self, config, tmp_path: Path
    ) -> None:
        """_create_venv should handle missing uv binary (FileNotFoundError)."""
        manager = WorkspaceManager(config)

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("uv"),
        ):
            await manager._create_venv(tmp_path)  # should not raise


# ---------------------------------------------------------------------------
# WorkspaceManager._install_hooks
# ---------------------------------------------------------------------------


class TestInstallHooks:
    """Tests for WorkspaceManager._install_hooks."""

    @pytest.mark.asyncio
    async def test_install_hooks_sets_hooks_path(self, config, tmp_path: Path) -> None:
        """_install_hooks should set core.hooksPath to .githooks."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._install_hooks(tmp_path)

        mock_exec.assert_called_once()
        assert mock_exec.call_args.args[:4] == (
            "git",
            "config",
            "core.hooksPath",
            ".githooks",
        )

    @pytest.mark.asyncio
    async def test_install_hooks_swallows_errors(self, config, tmp_path: Path) -> None:
        """_install_hooks should not propagate errors if git config fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"error")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            # Should not raise
            await manager._install_hooks(tmp_path)


# ---------------------------------------------------------------------------
# WorkspaceManager.start_merge_main
# ---------------------------------------------------------------------------


class TestStartMergeMain:
    """Tests for WorkspaceManager.start_merge_main."""

    @pytest.mark.asyncio
    async def test_start_merge_main_clean_merge_returns_true(
        self, config, tmp_path: Path
    ) -> None:
        """start_merge_main should return True when all commands succeed."""
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch("asyncio.create_subprocess_exec", return_value=success_proc):
            result = await manager.start_merge_main(tmp_path, "agent/issue-7")

        assert result is True

    @pytest.mark.asyncio
    async def test_start_merge_main_conflict_returns_false_without_abort(
        self, config, tmp_path: Path
    ) -> None:
        """start_merge_main should return False on conflict and NOT call --abort."""
        manager = WorkspaceManager(config)

        success_proc = make_proc(returncode=0)
        merge_fail_proc = make_proc(
            returncode=1, stderr=b"CONFLICT (content): Merge conflict"
        )

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return success_proc  # git fetch + ff-only merge succeed
            return merge_fail_proc  # git merge origin/main fails

        with patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ) as mock_exec:
            result = await manager.start_merge_main(tmp_path, "agent/issue-7")

        assert result is False
        # Critical: start_merge_main must NOT call git merge --abort
        for call in mock_exec.call_args_list:
            assert "--abort" not in call.args, (
                "start_merge_main must NOT abort on conflict — "
                "caller resolves conflicts"
            )

    @pytest.mark.asyncio
    async def test_start_merge_main_fetch_failure_returns_false(
        self, config, tmp_path: Path
    ) -> None:
        """start_merge_main should return False if fetch fails."""
        manager = WorkspaceManager(config)

        fetch_fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with patch("asyncio.create_subprocess_exec", return_value=fetch_fail_proc):
            result = await manager.start_merge_main(tmp_path, "agent/issue-7")

        assert result is False


# ---------------------------------------------------------------------------
# WorkspaceManager.abort_merge
# ---------------------------------------------------------------------------


class TestAbortMerge:
    """Tests for WorkspaceManager.abort_merge."""

    @pytest.mark.asyncio
    async def test_abort_merge_calls_git_merge_abort(
        self, config, tmp_path: Path
    ) -> None:
        """abort_merge should call 'git merge --abort' with correct cwd."""
        manager = WorkspaceManager(config)
        success_proc = make_proc(returncode=0)

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager.abort_merge(tmp_path)

        mock_exec.assert_called_once()
        args = mock_exec.call_args.args
        assert args[:3] == ("git", "merge", "--abort")

    @pytest.mark.asyncio
    async def test_abort_merge_swallows_runtime_error(
        self, config, tmp_path: Path
    ) -> None:
        """abort_merge should suppress RuntimeError via contextlib.suppress."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: no merge in progress")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            # Should not raise
            await manager.abort_merge(tmp_path)


# ---------------------------------------------------------------------------
# WorkspaceManager.get_conflicting_files
# ---------------------------------------------------------------------------


class TestGetConflictingFiles:
    """Tests for WorkspaceManager.get_conflicting_files."""

    @pytest.mark.asyncio
    async def test_returns_list_of_conflicting_files(
        self, config, tmp_path: Path
    ) -> None:
        """Should return file names from git diff --name-only --diff-filter=U."""
        manager = WorkspaceManager(config)
        output = b"src/foo.py\nsrc/bar.py\n"
        proc = make_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == ["src/foo.py", "src/bar.py"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_conflicts(
        self, config, tmp_path: Path
    ) -> None:
        """Should return empty list when no files have conflicts."""
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=0, stdout=b"")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_failure(self, config, tmp_path: Path) -> None:
        """Should return empty list when git command fails."""
        manager = WorkspaceManager(config)
        proc = make_proc(returncode=1, stderr=b"fatal: not a git repo")

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == []

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_filenames(
        self, config, tmp_path: Path
    ) -> None:
        """Should strip leading/trailing whitespace from each filename."""
        manager = WorkspaceManager(config)
        output = b"  foo.py  \n  bar.py  \n\n"
        proc = make_proc(returncode=0, stdout=output)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await manager.get_conflicting_files(tmp_path)

        assert result == ["foo.py", "bar.py"]


# ---------------------------------------------------------------------------
# WorkspaceManager.get_main_diff_for_files
# ---------------------------------------------------------------------------


class TestGetMainDiffForFiles:
    """Tests for WorkspaceManager.get_main_diff_for_files."""

    @pytest.mark.asyncio
    async def test_returns_diff_for_specified_files(
        self, config, tmp_path: Path
    ) -> None:
        """Should return the diff output for the given files."""
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        diff_proc = make_proc(
            returncode=0, stdout=b"diff --git a/foo.py b/foo.py\n+added\n"
        )

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return merge_base_proc
            return diff_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_diff_for_files(tmp_path, ["foo.py"])

        assert "diff --git a/foo.py b/foo.py" in result
        assert "+added" in result

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_file_list(
        self, config, tmp_path: Path
    ) -> None:
        """Should return empty string when no files are provided."""
        manager = WorkspaceManager(config)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            result = await manager.get_main_diff_for_files(tmp_path, [])

        assert result == ""
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_truncates_large_diff(self, config, tmp_path: Path) -> None:
        """Should truncate diff exceeding max_chars and append marker."""
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        large_diff = b"x" * 50_000
        diff_proc = make_proc(returncode=0, stdout=large_diff)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return merge_base_proc
            return diff_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_diff_for_files(
                tmp_path, ["foo.py"], max_chars=1000
            )

        assert len(result) < 1100  # 1000 + truncation marker
        assert "[Diff truncated]" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_merge_base_failure(
        self, config, tmp_path: Path
    ) -> None:
        """Should return empty string when git merge-base fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: bad revision")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            result = await manager.get_main_diff_for_files(tmp_path, ["foo.py"])

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_diff_failure(self, config, tmp_path: Path) -> None:
        """Should return empty string when git diff fails."""
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        diff_fail_proc = make_proc(returncode=1, stderr=b"fatal: bad path")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return merge_base_proc
            return diff_fail_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_diff_for_files(tmp_path, ["foo.py"])

        assert result == ""

    @pytest.mark.asyncio
    async def test_passes_multiple_files(self, config, tmp_path: Path) -> None:
        """Should pass all files to the git diff command."""
        manager = WorkspaceManager(config)
        merge_base_proc = make_proc(returncode=0, stdout=b"abc123\n")
        diff_proc = make_proc(returncode=0, stdout=b"combined diff\n")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return merge_base_proc
            return diff_proc

        with patch(
            "asyncio.create_subprocess_exec", side_effect=fake_exec
        ) as mock_exec:
            await manager.get_main_diff_for_files(
                tmp_path, ["foo.py", "bar.py", "baz.py"]
            )

        # The second call is git diff — check that all files are in the args
        diff_call = mock_exec.call_args_list[1]
        assert "foo.py" in diff_call.args
        assert "bar.py" in diff_call.args
        assert "baz.py" in diff_call.args


# ---------------------------------------------------------------------------
# WorkspaceManager.get_main_commits_since_diverge
# ---------------------------------------------------------------------------


class TestGetMainCommitsSinceDiverge:
    """Tests for WorkspaceManager.get_main_commits_since_diverge."""

    @pytest.mark.asyncio
    async def test_returns_commit_log(self, config, tmp_path: Path) -> None:
        """Should return oneline commits from HEAD..origin/main."""
        manager = WorkspaceManager(config)

        fetch_proc = make_proc(returncode=0)
        log_output = b"abc1234 Add feature X\ndef5678 Fix bug Y\n"
        log_proc = make_proc(returncode=0, stdout=log_output)

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fetch_proc
            return log_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert "abc1234 Add feature X" in result
        assert "def5678 Fix bug Y" in result

    @pytest.mark.asyncio
    async def test_returns_empty_on_fetch_failure(self, config, tmp_path: Path) -> None:
        """Should return empty string when git fetch fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: network error")

        with patch("asyncio.create_subprocess_exec", return_value=fail_proc):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_log_failure(self, config, tmp_path: Path) -> None:
        """Should return empty string when git log fails."""
        manager = WorkspaceManager(config)

        fetch_proc = make_proc(returncode=0)
        log_fail_proc = make_proc(returncode=1, stderr=b"fatal: bad revision")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fetch_proc
            return log_fail_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_diverged_commits(
        self, config, tmp_path: Path
    ) -> None:
        """Should return empty string when branch is up to date with main."""
        manager = WorkspaceManager(config)

        fetch_proc = make_proc(returncode=0)
        log_proc = make_proc(returncode=0, stdout=b"")

        call_count = 0

        async def fake_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fetch_proc
            return log_proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            result = await manager.get_main_commits_since_diverge(tmp_path)

        assert result == ""

    @pytest.mark.asyncio
    async def test_passes_limit_flag(self, config, tmp_path: Path) -> None:
        """Should pass -30 to limit the number of commits."""
        manager = WorkspaceManager(config)

        success_proc = make_proc(returncode=0, stdout=b"abc123 commit\n")

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager.get_main_commits_since_diverge(tmp_path)

        # Second call is git log
        log_call = mock_exec.call_args_list[1]
        assert "-30" in log_call.args


# ---------------------------------------------------------------------------
# Docker mode — helpers
# ---------------------------------------------------------------------------


def _make_hooks_subprocess_mock(hooks_dir: Path):
    """Return a coroutine that fakes 'git rev-parse --git-path hooks'."""

    async def _fake(*args, **_kwargs):
        if "rev-parse" in args:
            return str(hooks_dir)
        return ""

    return _fake


# ---------------------------------------------------------------------------
# Docker mode — _setup_env
# ---------------------------------------------------------------------------


class TestSetupEnvDocker:
    """Tests for _setup_env when execution_mode='docker'."""

    def test_setup_env_docker_copies_dotenv(self, tmp_path: Path) -> None:
        """In docker mode, .env should be copied (not symlinked) into worktree."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("SECRET=docker_test")

        manager._setup_env(wt_path)

        env_dst = wt_path / ".env"
        assert env_dst.exists()
        assert not env_dst.is_symlink(), (
            ".env must be copied, not symlinked in docker mode"
        )
        assert env_dst.read_text() == "SECRET=docker_test"

    def test_setup_env_docker_copies_node_modules(self, tmp_path: Path) -> None:
        """In docker mode, node_modules/ should be copied (not symlinked)."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        # Use "ui" — the default ui_dirs fallback from ConfigFactory
        ui_nm_src = repo_root / "ui" / "node_modules"
        ui_nm_src.mkdir(parents=True)
        (ui_nm_src / "some-pkg").mkdir()
        (ui_nm_src / "some-pkg" / "index.js").write_text("module.exports = {}")

        manager._setup_env(wt_path)

        ui_nm_dst = wt_path / "ui" / "node_modules"
        assert ui_nm_dst.exists()
        assert ui_nm_dst.is_dir()
        assert not ui_nm_dst.is_symlink(), (
            "node_modules must be copied, not symlinked in docker mode"
        )
        assert (
            ui_nm_dst / "some-pkg" / "index.js"
        ).read_text() == "module.exports = {}"

    def test_setup_env_docker_skips_missing_sources(self, tmp_path: Path) -> None:
        """In docker mode, missing .env and node_modules should be skipped gracefully."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        manager._setup_env(wt_path)

        assert not (wt_path / ".env").exists()

    def test_setup_env_docker_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """In docker mode, existing destination files should not be overwritten."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("NEW_CONTENT")

        env_dst = wt_path / ".env"
        env_dst.write_text("EXISTING_CONTENT")

        manager._setup_env(wt_path)

        assert env_dst.read_text() == "EXISTING_CONTENT"

    def test_setup_env_docker_handles_copy_oserror(self, tmp_path: Path) -> None:
        """In docker mode, OSError during copy should be caught and not raised."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("SECRET=val")

        with patch("workspace.shutil.copy2", side_effect=OSError("permission denied")):
            manager._setup_env(wt_path)  # should not raise

        assert not (wt_path / ".env").exists()
        assert not (wt_path / ".gitignore").exists(), (
            ".gitignore must not be updated when .env copy fails"
        )

    def test_setup_env_docker_handles_copytree_oserror(self, tmp_path: Path) -> None:
        """In docker mode, OSError during node_modules copytree should be caught."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        ui_nm_src = repo_root / "ui" / "node_modules"
        ui_nm_src.mkdir(parents=True)

        with patch("workspace.shutil.copytree", side_effect=OSError("disk full")):
            manager._setup_env(wt_path)  # should not raise

    def test_setup_env_docker_adds_env_to_gitignore(self, tmp_path: Path) -> None:
        """In docker mode, .env should be appended to worktree .gitignore."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("SECRET=val")

        manager._setup_env(wt_path)

        gitignore = wt_path / ".gitignore"
        assert gitignore.exists()
        assert ".env" in [ln.strip() for ln in gitignore.read_text().splitlines()]

    def test_setup_env_docker_does_not_duplicate_gitignore_entry(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, .env should not be added to .gitignore if already present."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("SECRET=val")

        # Pre-populate .gitignore with .env already listed
        gitignore = wt_path / ".gitignore"
        gitignore.write_text("node_modules/\n.env\n*.pyc\n")

        manager._setup_env(wt_path)

        lines = [ln.strip() for ln in gitignore.read_text().splitlines()]
        assert lines.count(".env") == 1, "duplicate .env entries must not be added"

    def test_setup_env_docker_handles_gitignore_update_oserror(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, OSError when updating .gitignore should be caught."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        # Pre-create env_dst so the gitignore update block is reached;
        # with env_dst already present the copy step is skipped.
        env_src = repo_root / ".env"
        env_src.write_text("SECRET=val")
        (wt_path / ".env").write_text("SECRET=val")

        with patch("pathlib.Path.open", side_effect=OSError("read-only")):
            manager._setup_env(wt_path)  # should not raise

    def test_setup_env_host_still_symlinks(self, config, tmp_path: Path) -> None:
        """Confirm host mode still creates symlinks (regression check)."""
        assert config.execution_mode == "host"
        manager = WorkspaceManager(config)

        repo_root = config.repo_root
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        repo_root.mkdir(parents=True, exist_ok=True)

        env_src = repo_root / ".env"
        env_src.write_text("HOST_MODE=true")

        manager._setup_env(wt_path)

        env_dst = wt_path / ".env"
        assert env_dst.is_symlink(), ".env must be symlinked in host mode"


# ---------------------------------------------------------------------------
# Docker mode — _install_hooks
# ---------------------------------------------------------------------------


class TestInstallHooksDocker:
    """Tests for _install_hooks when execution_mode='docker'."""

    @pytest.mark.asyncio
    async def test_install_hooks_docker_copies_hook_files(self, tmp_path: Path) -> None:
        """In docker mode, hook files should be copied to the git hooks dir."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)

        # Create .githooks with a pre-commit hook
        githooks_dir = repo_root / ".githooks"
        githooks_dir.mkdir()
        hook_file = githooks_dir / "pre-commit"
        hook_file.write_text("#!/bin/sh\nexit 0\n")

        # Create worktree with a git hooks directory
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        hooks_dir = wt_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        with patch(
            "workspace.run_subprocess",
            side_effect=_make_hooks_subprocess_mock(hooks_dir),
        ):
            await manager._install_hooks(wt_path)

        copied_hook = hooks_dir / "pre-commit"
        assert copied_hook.exists()
        assert copied_hook.read_text() == "#!/bin/sh\nexit 0\n"
        # Check executable permission
        assert copied_hook.stat().st_mode & stat.S_IXUSR

    @pytest.mark.asyncio
    async def test_install_hooks_docker_skips_when_githooks_missing(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, missing .githooks/ should be handled gracefully."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        # No .githooks directory

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        # Should not raise
        await manager._install_hooks(wt_path)

    @pytest.mark.asyncio
    async def test_install_hooks_docker_handles_copy_error(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, OSError during hook copy should be caught."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)

        githooks_dir = repo_root / ".githooks"
        githooks_dir.mkdir()
        (githooks_dir / "pre-commit").write_text("#!/bin/sh\nexit 0\n")

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        hooks_dir = wt_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        with (
            patch(
                "workspace.run_subprocess",
                side_effect=_make_hooks_subprocess_mock(hooks_dir),
            ),
            patch("workspace.shutil.copy2", side_effect=OSError("perm denied")),
        ):
            await manager._install_hooks(wt_path)  # should not raise

    @pytest.mark.asyncio
    async def test_install_hooks_docker_handles_mkdir_oserror(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, OSError creating git hooks dir should be caught."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)

        githooks_dir = repo_root / ".githooks"
        githooks_dir.mkdir()
        (githooks_dir / "pre-commit").write_text("#!/bin/sh\nexit 0\n")

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        hooks_dir = wt_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        with (
            patch(
                "workspace.run_subprocess",
                side_effect=_make_hooks_subprocess_mock(hooks_dir),
            ),
            patch("pathlib.Path.mkdir", side_effect=OSError("read-only fs")),
        ):
            await manager._install_hooks(wt_path)  # should not raise

        assert not (hooks_dir / "pre-commit").exists()

    @pytest.mark.asyncio
    async def test_install_hooks_host_sets_hooks_path(
        self, config, tmp_path: Path
    ) -> None:
        """Confirm host mode still sets core.hooksPath (regression check)."""
        assert config.execution_mode == "host"
        manager = WorkspaceManager(config)
        success_proc = make_proc()

        with patch(
            "asyncio.create_subprocess_exec", return_value=success_proc
        ) as mock_exec:
            await manager._install_hooks(tmp_path)

        mock_exec.assert_called_once()
        assert mock_exec.call_args.args[:4] == (
            "git",
            "config",
            "core.hooksPath",
            ".githooks",
        )

    @pytest.mark.asyncio
    async def test_install_hooks_docker_copies_multiple_hooks(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, all hook files should be copied."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)

        githooks_dir = repo_root / ".githooks"
        githooks_dir.mkdir()
        (githooks_dir / "pre-commit").write_text("#!/bin/sh\necho pre-commit\n")
        (githooks_dir / "pre-push").write_text("#!/bin/sh\necho pre-push\n")

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        hooks_dir = wt_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)

        with patch(
            "workspace.run_subprocess",
            side_effect=_make_hooks_subprocess_mock(hooks_dir),
        ):
            await manager._install_hooks(wt_path)

        assert (hooks_dir / "pre-commit").exists()
        assert (hooks_dir / "pre-push").exists()

    @pytest.mark.asyncio
    async def test_install_hooks_docker_handles_git_rev_parse_error(
        self, tmp_path: Path
    ) -> None:
        """In docker mode, RuntimeError from git rev-parse should be caught."""
        manager = make_docker_manager(tmp_path)

        repo_root = manager._repo_root
        repo_root.mkdir(parents=True, exist_ok=True)

        githooks_dir = repo_root / ".githooks"
        githooks_dir.mkdir()
        (githooks_dir / "pre-commit").write_text("#!/bin/sh\nexit 0\n")

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        async def _raise(*args, cwd=None, gh_token=None):  # noqa: ARG001
            raise RuntimeError("git not available")

        with patch("workspace.run_subprocess", side_effect=_raise):
            await manager._install_hooks(wt_path)  # should not raise

        # No hooks should have been copied since git rev-parse failed
        assert not (wt_path / ".git" / "hooks" / "pre-commit").exists()


# ---------------------------------------------------------------------------
# WorkspaceManager._detect_ui_dirs
# ---------------------------------------------------------------------------


class TestDetectUiDirs:
    """Tests for WorkspaceManager._detect_ui_dirs."""

    def test_detects_package_json_dirs(self, tmp_path: Path) -> None:
        """Should discover UI dirs from package.json files in repo root."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        # Create two UI dirs with package.json
        (repo_root / "ui").mkdir()
        (repo_root / "ui" / "package.json").write_text("{}")
        (repo_root / "dashboard" / "frontend").mkdir(parents=True)
        (repo_root / "dashboard" / "frontend" / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        assert "dashboard/frontend" in manager._ui_dirs
        assert "ui" in manager._ui_dirs

    def test_skips_node_modules_package_json(self, tmp_path: Path) -> None:
        """Should not detect package.json inside node_modules."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "ui").mkdir()
        (repo_root / "ui" / "package.json").write_text("{}")
        (repo_root / "ui" / "node_modules" / "some-pkg").mkdir(parents=True)
        (repo_root / "ui" / "node_modules" / "some-pkg" / "package.json").write_text(
            "{}"
        )

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        assert manager._ui_dirs == ["ui"]

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        """Should not detect package.json inside hidden directories."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".hidden" / "sub").mkdir(parents=True)
        (repo_root / ".hidden" / "sub" / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        # No package.json found outside hidden dirs, falls back to config
        assert manager._ui_dirs == ["ui"]

    def test_skips_root_level_package_json(self, tmp_path: Path) -> None:
        """Should not include root-level package.json as a UI dir."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        # Root package.json is excluded, falls back to config
        assert manager._ui_dirs == ["ui"]

    def test_falls_back_to_config_when_no_package_json(self, tmp_path: Path) -> None:
        """Should use config.ui_dirs when no package.json files are found."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            ui_dirs=["custom/ui", "other/frontend"],
        )
        manager = WorkspaceManager(cfg)

        assert manager._ui_dirs == ["custom/ui", "other/frontend"]

    def test_detection_overrides_config(self, tmp_path: Path) -> None:
        """When package.json files are found, they override config.ui_dirs."""
        from tests.helpers import ConfigFactory

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "webapp").mkdir()
        (repo_root / "webapp" / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            ui_dirs=["old/ui"],
        )
        manager = WorkspaceManager(cfg)

        assert manager._ui_dirs == ["webapp"]


# ---------------------------------------------------------------------------
# sanitize_repo
# ---------------------------------------------------------------------------


class TestSanitizeRepo:
    """Tests for WorkspaceManager.sanitize_repo."""

    @pytest.mark.asyncio
    async def test_sanitize_prunes_and_checks_out_main(self, config) -> None:
        manager = WorkspaceManager(config)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args, cwd=None, gh_token=None):
            calls.append(args)
            if args == ("git", "symbolic-ref", "--short", "HEAD"):
                return "main\n"
            if args == ("git", "branch", "--list", "agent/*"):
                return "  agent/issue-99\n  agent/issue-100\n"
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "_fetch_origin_with_retry", new_callable=AsyncMock),
        ):
            await manager.sanitize_repo()

        cmd_strs = [" ".join(c) for c in calls]
        assert any("branch -D agent/issue-99" in c for c in cmd_strs)
        assert any("branch -D agent/issue-100" in c for c in cmd_strs)

    @pytest.mark.asyncio
    async def test_sanitize_forces_checkout_when_on_wrong_branch(self, config) -> None:
        manager = WorkspaceManager(config)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args, cwd=None, gh_token=None):
            calls.append(args)
            if args == ("git", "symbolic-ref", "--short", "HEAD"):
                return "agent/issue-42\n"
            if args == ("git", "branch", "--list", "agent/*"):
                return ""
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "_fetch_origin_with_retry", new_callable=AsyncMock),
        ):
            await manager.sanitize_repo()

        cmd_strs = [" ".join(c) for c in calls]
        assert any("checkout -f main" in c for c in cmd_strs)
        assert any("reset --hard origin/main" in c for c in cmd_strs)


# ---------------------------------------------------------------------------
# pre_work_check
# ---------------------------------------------------------------------------


class TestPreWorkCheck:
    """Tests for WorkspaceManager.pre_work_check."""

    @pytest.mark.asyncio
    async def test_pre_work_fetches_main(self, config) -> None:
        manager = WorkspaceManager(config)

        with patch.object(
            manager, "_fetch_origin_with_retry", new_callable=AsyncMock
        ) as mock_fetch:
            await manager.pre_work_check()

        mock_fetch.assert_awaited_once_with(config.repo_root, config.main_branch)


# ---------------------------------------------------------------------------
# post_work_cleanup
# ---------------------------------------------------------------------------


class TestPostWorkCleanup:
    """Tests for WorkspaceManager.post_work_cleanup."""

    @pytest.mark.asyncio
    async def test_post_work_destroys(self, config) -> None:
        manager = WorkspaceManager(config)

        with patch.object(manager, "destroy", new_callable=AsyncMock) as mock_destroy:
            await manager.post_work_cleanup(42)

        mock_destroy.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_post_work_salvages_uncommitted_changes(self, config) -> None:
        manager = WorkspaceManager(config)

        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args, cwd=None, gh_token=None):
            calls.append(args)
            if args == ("git", "status", "--porcelain"):
                return " M src/foo.py\n"
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "destroy", new_callable=AsyncMock),
        ):
            await manager.post_work_cleanup(42)

        cmd_strs = [" ".join(c) for c in calls]
        assert any("git add -A" in c for c in cmd_strs)
        assert any("git commit" in c for c in cmd_strs)
        assert any("git push" in c for c in cmd_strs)

    @pytest.mark.asyncio
    async def test_post_work_skips_salvage_when_clean(self, config) -> None:
        manager = WorkspaceManager(config)

        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args, cwd=None, gh_token=None):
            calls.append(args)
            if args == ("git", "status", "--porcelain"):
                return ""
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "destroy", new_callable=AsyncMock),
        ):
            await manager.post_work_cleanup(42)

        cmd_strs = [" ".join(c) for c in calls]
        assert not any("git add -A" in c for c in cmd_strs)
        assert not any("git commit" in c for c in cmd_strs)

    @pytest.mark.asyncio
    async def test_post_work_continues_if_destroy_fails(self, config) -> None:
        manager = WorkspaceManager(config)

        with patch.object(
            manager, "destroy", side_effect=RuntimeError("worktree gone")
        ):
            # Should not raise — destroy failure is suppressed
            await manager.post_work_cleanup(42)


# ---------------------------------------------------------------------------
# Wiring: pre_work_check called from create
# ---------------------------------------------------------------------------


class TestCreateCallsPreWorkCheck:
    """Verify WorkspaceManager.create calls pre_work_check before creating."""

    @pytest.mark.asyncio
    async def test_create_calls_pre_work_check(self, config) -> None:
        manager = WorkspaceManager(config)
        config.worktree_base.mkdir(parents=True, exist_ok=True)

        success_proc = make_proc(returncode=0)

        with (
            patch("asyncio.create_subprocess_exec", return_value=success_proc),
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
            patch.object(manager, "_setup_env"),
            patch.object(manager, "_create_venv", new_callable=AsyncMock),
            patch.object(manager, "_install_hooks", new_callable=AsyncMock),
            patch.object(manager, "pre_work_check", new_callable=AsyncMock) as mock_pre,
        ):
            await manager.create(issue_number=7, branch="agent/issue-7")

        mock_pre.assert_awaited_once()


# NOTE: Tests for the subprocess helper (stdout parsing, error handling,
# GH_TOKEN injection, CLAUDECODE stripping) are now in test_subprocess_util.py
# since the logic was extracted into subprocess_util.run_subprocess.
