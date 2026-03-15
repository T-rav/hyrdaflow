"""Tests for workspace — environment setup."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tests.helpers import ConfigFactory, make_docker_manager, make_proc
from workspace import WorkspaceManager

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

    def test_setup_env_handles_symlink_oserror(
        self, config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_setup_env should handle OSError on symlink and log debug message."""
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

        with (
            patch.object(
                Path, "symlink_to", side_effect=OSError("perm denied")
            ) as mock_symlink,
            caplog.at_level(logging.DEBUG, logger="hydraflow.workspace"),
        ):
            manager._setup_env(wt_path)  # should not raise

        assert mock_symlink.call_count >= 1
        assert any("Could not" in r.message for r in caplog.records)

    def test_setup_env_handles_copy_oserror(
        self, config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_setup_env should handle OSError when copying settings and log debug message."""
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

        with (
            patch.object(
                Path, "write_text", side_effect=OSError("read-only")
            ) as mock_write,
            caplog.at_level(logging.DEBUG, logger="hydraflow.workspace"),
        ):
            manager._setup_env(wt_path)  # should not raise

        assert mock_write.call_count >= 1
        assert any("Could not copy settings" in r.message for r in caplog.records)


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

    def test_oserror_during_write_is_suppressed(
        self, config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_setup_claude_settings should suppress OSError and log debug message."""
        manager = WorkspaceManager(config)
        repo_root = config.repo_root
        repo_root.mkdir(parents=True, exist_ok=True)
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        claude_dir = repo_root / ".claude"
        claude_dir.mkdir()
        settings_src = claude_dir / "settings.local.json"
        settings_src.write_text('{"allowed": []}')

        with (
            patch.object(
                Path, "write_text", side_effect=OSError("read-only")
            ) as mock_write,
            caplog.at_level(logging.DEBUG, logger="hydraflow.workspace"),
        ):
            manager._setup_claude_settings(wt_path)  # should not raise

        assert mock_write.call_count >= 1
        assert any("Could not copy settings" in r.message for r in caplog.records)


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
    async def test_runtime_error_does_not_raise(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_configure_git_identity should log warning and continue on RuntimeError."""
        cfg = ConfigFactory.create(
            git_user_name="Bot",
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        manager = WorkspaceManager(cfg)
        fail_proc = make_proc(returncode=1, stderr=b"fatal: config error")

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=fail_proc
            ) as mock_exec,
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        ):
            await manager._configure_git_identity(tmp_path)

        mock_exec.assert_called_once()
        assert any("git identity config failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_called_during_create(self, tmp_path: Path) -> None:
        """_configure_git_identity should be called during create()."""
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
    async def test_create_venv_swallows_errors(
        self, config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_create_venv should log warning and continue if uv sync fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"uv not found")

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=fail_proc
            ) as mock_exec,
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        ):
            await manager._create_venv(tmp_path)

        mock_exec.assert_called_once()
        assert any("uv sync failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_create_venv_swallows_file_not_found_error(
        self, config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_create_venv should log warning when uv binary is missing."""
        manager = WorkspaceManager(config)

        with (
            patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("uv"),
            ) as mock_exec,
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        ):
            await manager._create_venv(tmp_path)

        mock_exec.assert_called_once()
        assert any("uv sync failed" in r.message for r in caplog.records)


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
    async def test_install_hooks_swallows_errors(
        self, config, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_install_hooks should log warning and continue if git config fails."""
        manager = WorkspaceManager(config)
        fail_proc = make_proc(returncode=1, stderr=b"error")

        with (
            patch(
                "asyncio.create_subprocess_exec", return_value=fail_proc
            ) as mock_exec,
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
        ):
            await manager._install_hooks(tmp_path)

        mock_exec.assert_called_once()
        assert any("git hooks setup failed" in r.message for r in caplog.records)
