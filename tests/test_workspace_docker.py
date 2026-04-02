"""Tests for workspace — docker mode, UI detection, and lifecycle hooks."""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.helpers import ConfigFactory, make_docker_manager, make_proc
from workspace import WorkspaceManager

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

        with patch(
            "workspace.shutil.copytree", side_effect=OSError("disk full")
        ) as mock_copytree:
            manager._setup_env(wt_path)  # should not raise

        mock_copytree.assert_called_once()

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

        with patch("pathlib.Path.open", side_effect=OSError("read-only")) as mock_open:
            manager._setup_env(wt_path)  # should not raise

        assert mock_open.call_count >= 1

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

        assert not (wt_path / ".git" / "hooks").exists()

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
            patch(
                "workspace.shutil.copy2", side_effect=OSError("perm denied")
            ) as mock_copy,
        ):
            await manager._install_hooks(wt_path)  # should not raise

        assert mock_copy.call_count >= 1

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
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        # Create two UI dirs with package.json
        (repo_root / "ui").mkdir()
        (repo_root / "ui" / "package.json").write_text("{}")
        (repo_root / "dashboard" / "frontend").mkdir(parents=True)
        (repo_root / "dashboard" / "frontend" / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        assert "dashboard/frontend" in manager._ui_dirs
        assert "ui" in manager._ui_dirs

    def test_skips_node_modules_package_json(self, tmp_path: Path) -> None:
        """Should not detect package.json inside node_modules."""
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
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        assert manager._ui_dirs == ["ui"]

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        """Should not detect package.json inside hidden directories."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".hidden" / "sub").mkdir(parents=True)
        (repo_root / ".hidden" / "sub" / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        # No package.json found outside hidden dirs, falls back to config
        assert manager._ui_dirs == ["ui"]

    def test_skips_root_level_package_json(self, tmp_path: Path) -> None:
        """Should not include root-level package.json as a UI dir."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)

        # Root package.json is excluded, falls back to config
        assert manager._ui_dirs == ["ui"]

    def test_falls_back_to_config_when_no_package_json(self, tmp_path: Path) -> None:
        """Should use config.ui_dirs when no package.json files are found."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            ui_dirs=["custom/ui", "other/frontend"],
        )
        manager = WorkspaceManager(cfg)

        assert manager._ui_dirs == ["custom/ui", "other/frontend"]

    def test_detection_overrides_config(self, tmp_path: Path) -> None:
        """When package.json files are found, they override config.ui_dirs."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "webapp").mkdir()
        (repo_root / "webapp" / "package.json").write_text("{}")

        cfg = ConfigFactory.create(
            repo_root=repo_root,
            workspace_base=tmp_path / "worktrees",
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
    async def test_sanitize_fetches_and_prunes_orphan_branches(self, config) -> None:
        """sanitize_repo fetches latest main and prunes agent/* branches."""
        manager = WorkspaceManager(config)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args, cwd=None, gh_token=None):
            calls.append(args)
            if args == ("git", "branch", "--list", "agent/*"):
                return "  agent/issue-99\n  agent/issue-100\n"
            return ""

        fetch_mock = AsyncMock()
        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "_fetch_origin_with_retry", fetch_mock),
        ):
            await manager.sanitize_repo()

        # Fetch must be called
        fetch_mock.assert_called_once()

        # Orphan branches must be deleted
        cmd_strs = [" ".join(c) for c in calls]
        assert any("branch -D agent/issue-99" in c for c in cmd_strs)
        assert any("branch -D agent/issue-100" in c for c in cmd_strs)

    @pytest.mark.asyncio
    async def test_sanitize_never_runs_checkout_or_reset(self, config) -> None:
        """sanitize_repo must not force-checkout or hard-reset the primary checkout."""
        manager = WorkspaceManager(config)

        calls: list[tuple[str, ...]] = []

        async def fake_run(*args, cwd=None, gh_token=None):
            calls.append(args)
            if args == ("git", "branch", "--list", "agent/*"):
                return "  agent/issue-7\n"
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "_fetch_origin_with_retry", new_callable=AsyncMock),
        ):
            await manager.sanitize_repo()

        cmd_strs = [" ".join(c) for c in calls]
        assert not any("checkout" in c for c in cmd_strs), (
            "sanitize_repo must not run git checkout on the primary checkout"
        )
        assert not any("reset" in c for c in cmd_strs), (
            "sanitize_repo must not run git reset on the primary checkout"
        )

    @pytest.mark.asyncio
    async def test_sanitize_tolerates_no_orphan_branches(self, config) -> None:
        """sanitize_repo succeeds cleanly when there are no agent/* branches."""
        manager = WorkspaceManager(config)

        async def fake_run(*args, cwd=None, gh_token=None):
            if args == ("git", "branch", "--list", "agent/*"):
                return ""
            return ""

        with (
            patch("workspace.run_subprocess", side_effect=fake_run),
            patch.object(manager, "_fetch_origin_with_retry", new_callable=AsyncMock),
        ):
            await manager.sanitize_repo()  # must not raise


# ---------------------------------------------------------------------------
# WorkspaceManager.reset_to_main
# ---------------------------------------------------------------------------


class TestResetToMain:
    """Tests for the reset_to_main method."""

    @pytest.mark.asyncio
    async def test_reset_runs_fetch_reset_clean(self, tmp_path: Path) -> None:
        """reset_to_main should fetch, hard-reset, and clean."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(config)
        wt_path = tmp_path / "worktrees" / "issue-42"
        wt_path.mkdir(parents=True)

        commands_run: list[list[str]] = []

        async def mock_run_subprocess(*args, cwd=None, gh_token=None):
            commands_run.append(list(args))
            return ""

        with patch("workspace.run_subprocess", side_effect=mock_run_subprocess):
            await manager.reset_to_main(wt_path)

        # Should have run 3 commands: fetch, reset --hard, clean -fd
        assert len(commands_run) == 3
        assert commands_run[0][:3] == ["git", "fetch", "origin"]
        assert "reset" in commands_run[1] and "--hard" in commands_run[1]
        assert "clean" in commands_run[2] and "-fd" in commands_run[2]

    @pytest.mark.asyncio
    async def test_reset_uses_configured_main_branch(self, tmp_path: Path) -> None:
        """reset_to_main should use the configured main branch name."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        # Override main_branch for this test
        object.__setattr__(config, "main_branch", "develop")
        manager = WorkspaceManager(config)
        wt_path = tmp_path / "worktrees" / "issue-42"
        wt_path.mkdir(parents=True)

        commands_run: list[list[str]] = []

        async def mock_run_subprocess(*args, cwd=None, gh_token=None):
            commands_run.append(list(args))
            return ""

        with patch("workspace.run_subprocess", side_effect=mock_run_subprocess):
            await manager.reset_to_main(wt_path)

        assert "develop" in commands_run[0]  # fetch includes branch
        assert "origin/develop" in commands_run[1]  # reset target


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

        wt_path = config.workspace_path_for_issue(42)
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

        wt_path = config.workspace_path_for_issue(42)
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
        ) as mock_destroy:
            # Should not raise — destroy failure is suppressed
            await manager.post_work_cleanup(42)

        mock_destroy.assert_called_once()


# ---------------------------------------------------------------------------
# Wiring: pre_work_check called from create
# ---------------------------------------------------------------------------


class TestCreateCallsPreWorkCheck:
    """Verify WorkspaceManager.create calls pre_work_check before creating."""

    @pytest.mark.asyncio
    async def test_create_calls_pre_work_check(self, config) -> None:
        manager = WorkspaceManager(config)
        config.workspace_base.mkdir(parents=True, exist_ok=True)

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
