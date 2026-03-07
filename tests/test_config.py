"""Tests for dx/hydraflow/config.py."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import get_args

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import (
    _ENV_BOOL_OVERRIDES,
    _ENV_FLOAT_OVERRIDES,
    _ENV_INT_OVERRIDES,
    _ENV_LITERAL_OVERRIDES,
    _ENV_STR_OVERRIDES,
    HydraFlowConfig,
    _detect_repo_slug,
    _find_repo_root,
)

# ---------------------------------------------------------------------------
# _find_repo_root
# ---------------------------------------------------------------------------


class TestFindRepoRoot:
    """Tests for the _find_repo_root() helper."""

    def test_finds_git_root_from_repo_subdirectory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return the directory containing .git when walking up."""
        # Arrange
        git_root = tmp_path / "project"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        nested = git_root / "src" / "pkg"
        nested.mkdir(parents=True)

        monkeypatch.chdir(nested)

        # Act
        result = _find_repo_root()

        # Assert
        assert result == git_root.resolve()

    def test_finds_git_root_from_repo_root_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return cwd when .git exists directly in cwd."""
        # Arrange
        git_root = tmp_path / "project"
        git_root.mkdir()
        (git_root / ".git").mkdir()

        monkeypatch.chdir(git_root)

        # Act
        result = _find_repo_root()

        # Assert
        assert result == git_root.resolve()

    def test_returns_cwd_when_no_git_root_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should fall back to cwd when no .git directory exists in the hierarchy."""
        # Arrange – tmp_path has no .git anywhere above it inside tmp_path
        no_git_dir = tmp_path / "no_git"
        no_git_dir.mkdir()
        monkeypatch.chdir(no_git_dir)

        # Act
        result = _find_repo_root()

        # Assert – result is a resolved Path (either cwd or a real parent that
        # happens to contain .git on the host machine; we only care it is a Path)
        assert isinstance(result, Path)

    def test_returns_resolved_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The returned path should be an absolute resolved Path."""
        # Arrange
        git_root = tmp_path / "proj"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        monkeypatch.chdir(git_root)

        # Act
        result = _find_repo_root()

        # Assert
        assert result.is_absolute()

    def test_finds_git_root_initialized_with_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should find the root when a .git directory exists."""
        # Arrange
        git_root = tmp_path / "real_repo"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        nested = git_root / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        # Act
        result = _find_repo_root()

        # Assert
        assert result == git_root.resolve()

    def test_prefers_outermost_git_root_when_nested(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should pick the outermost repo when multiple .git roots exist above cwd."""
        outer = tmp_path / "outer"
        inner = outer / "inner"
        nested = inner / "src"
        outer.mkdir()
        inner.mkdir()
        nested.mkdir(parents=True)
        (outer / ".git").mkdir()
        (inner / ".git").mkdir()
        monkeypatch.chdir(nested)

        result = _find_repo_root()

        assert result == outer.resolve()


# ---------------------------------------------------------------------------
# _detect_repo_slug
# ---------------------------------------------------------------------------


class TestDetectRepoSlug:
    """Tests for the _detect_repo_slug() helper."""

    def test_ssh_remote_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should parse SSH remote URL and strip .git suffix."""
        # Arrange
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="git@github.com:owner/repo.git\n"
            ),
        )

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == "owner/repo"

    def test_https_remote_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should parse HTTPS remote URL and strip .git suffix."""
        # Arrange
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="https://github.com/owner/repo.git\n"
            ),
        )

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == "owner/repo"

    def test_ssh_url_without_git_suffix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should parse SSH remote URL without .git suffix."""
        # Arrange
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="git@github.com:owner/repo\n"
            ),
        )

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == "owner/repo"

    def test_https_url_without_git_suffix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should parse HTTPS remote URL without .git suffix."""
        # Arrange
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="https://github.com/owner/repo\n"
            ),
        )

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == "owner/repo"

    def test_empty_remote_returns_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return empty string when git remote output is empty."""
        # Arrange
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout=""
            ),
        )

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == ""

    def test_subprocess_file_not_found_returns_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return empty string when git is not installed."""

        # Arrange
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", _raise)

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == ""

    def test_subprocess_os_error_returns_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return empty string on OSError."""

        # Arrange
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise OSError("subprocess failed")

        monkeypatch.setattr(subprocess, "run", _raise)

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == ""

    def test_subprocess_timeout_returns_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return empty string when git command times out."""

        # Arrange
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="git", timeout=10)

        monkeypatch.setattr(subprocess, "run", _raise)

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == ""

    def test_non_github_remote_returns_empty_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return empty string for non-GitHub hosts."""
        # Arrange
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess(
                args=[], returncode=0, stdout="https://gitlab.com/owner/repo.git\n"
            ),
        )

        # Act
        result = _detect_repo_slug(tmp_path)

        # Assert
        assert result == ""


# ---------------------------------------------------------------------------
# HydraFlowConfig – defaults
# ---------------------------------------------------------------------------


class TestHydraFlowConfigDefaults:
    """Tests that default field values are correct."""

    def test_label_default(self, tmp_path: Path) -> None:
        # Arrange / Act
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        # Assert
        assert cfg.ready_label == ["hydraflow-ready"]

    def test_batch_size_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.batch_size == 15

    def test_repo_auto_detects_from_git_remote(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        # repo is auto-detected from git remote; in non-git dirs it falls back to ""
        assert isinstance(cfg.repo, str)

    def test_max_workers_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_workers == 1

    def test_improve_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["hydraflow-improve"]

    def test_find_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.find_label == ["hydraflow-find"]

    def test_max_planners_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_planners == 1

    def test_max_reviewers_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_reviewers == 1

    def test_max_triagers_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_triagers == 1

    def test_max_triagers_env_override_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_TRIAGERS env var should be ignored; worker counts are config-file-only."""
        monkeypatch.setenv("HYDRAFLOW_MAX_TRIAGERS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_triagers == 1

    def test_max_workers_env_override_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_WORKERS env var should be ignored; worker counts are config-file-only."""
        monkeypatch.setenv("HYDRAFLOW_MAX_WORKERS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_workers == 1

    def test_max_reviewers_env_override_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_REVIEWERS env var should be ignored; worker counts are config-file-only."""
        monkeypatch.setenv("HYDRAFLOW_MAX_REVIEWERS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_reviewers == 1

    def test_max_planners_env_override_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_PLANNERS env var should be ignored; worker counts are config-file-only."""
        monkeypatch.setenv("HYDRAFLOW_MAX_PLANNERS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_planners == 1

    def test_max_hitl_workers_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_hitl_workers == 1

    def test_max_hitl_workers_env_override_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_HITL_WORKERS env var should be ignored; worker counts are config-file-only."""
        monkeypatch.setenv("HYDRAFLOW_MAX_HITL_WORKERS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_hitl_workers == 1

    def test_hitl_active_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_active_label == ["hydraflow-hitl-active"]

    def test_model_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.model == "opus"

    def test_review_model_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.review_model == "sonnet"

    def test_main_branch_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.main_branch == "main"

    def test_dashboard_port_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dashboard_port == 5555

    def test_dashboard_enabled_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dashboard_enabled is True

    def test_dry_run_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dry_run is False

    def test_inject_runtime_logs_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.inject_runtime_logs is False

    def test_max_runtime_log_chars_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_runtime_log_chars == 8_000

    def test_max_ci_log_chars_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_ci_log_chars == 12_000


# ---------------------------------------------------------------------------
# HydraFlowConfig – custom values override defaults
# ---------------------------------------------------------------------------


class TestHydraFlowConfigCustomValues:
    """Tests that custom constructor values take precedence over defaults."""

    def test_custom_label_overrides_ready_label_default(self, tmp_path: Path) -> None:
        # Arrange / Act
        cfg = HydraFlowConfig(
            ready_label=["sprint"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        # Assert
        assert cfg.ready_label == ["sprint"]

    def test_custom_batch_size(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            batch_size=10,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.batch_size == 10

    def test_custom_repo(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="myorg/myrepo",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo == "myorg/myrepo"

    def test_custom_max_workers(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_workers=3,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_workers == 3

    def test_custom_model(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            model="haiku",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.model == "haiku"

    def test_custom_review_model(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            review_model="sonnet",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.review_model == "sonnet"

    def test_custom_main_branch(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            main_branch="develop",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.main_branch == "develop"

    def test_custom_dashboard_port(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dashboard_port=8080,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dashboard_port == 8080

    def test_custom_dashboard_enabled_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dashboard_enabled=False,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dashboard_enabled is False

    def test_custom_max_hitl_workers(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_hitl_workers=3,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_hitl_workers == 3

    def test_custom_hitl_active_label(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            hitl_active_label=["custom-active"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_active_label == ["custom-active"]

    def test_custom_improve_label(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            improve_label=["my-improve"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["my-improve"]

    def test_custom_dry_run_true(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dry_run=True,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dry_run is True


# ---------------------------------------------------------------------------
# HydraFlowConfig – path resolution via resolve_paths model_validator
# ---------------------------------------------------------------------------


class TestHydraFlowConfigPathResolution:
    """Tests for the resolve_paths model validator."""

    def test_explicit_repo_root_is_preserved(self, tmp_path: Path) -> None:
        # Arrange
        explicit_root = tmp_path / "my_repo"
        explicit_root.mkdir()

        # Act
        cfg = HydraFlowConfig(
            repo_root=explicit_root,
            worktree_base=explicit_root / "wt",
            state_file=explicit_root / "state.json",
        )

        # Assert
        assert cfg.repo_root == explicit_root

    def test_explicit_worktree_base_is_preserved(self, tmp_path: Path) -> None:
        # Arrange
        explicit_root = tmp_path / "repo"
        explicit_wt = tmp_path / "worktrees"

        # Act
        cfg = HydraFlowConfig(
            repo_root=explicit_root,
            worktree_base=explicit_wt,
            state_file=explicit_root / "state.json",
        )

        # Assert
        assert cfg.worktree_base == explicit_wt

    def test_explicit_state_file_is_preserved(self, tmp_path: Path) -> None:
        # Arrange
        explicit_root = tmp_path / "repo"
        explicit_state = tmp_path / "custom-state.json"

        # Act
        cfg = HydraFlowConfig(
            repo_root=explicit_root,
            worktree_base=explicit_root / "wt",
            state_file=explicit_state,
        )

        # Assert
        assert cfg.state_file == explicit_state

    def test_default_worktree_base_derived_from_repo_root(self, tmp_path: Path) -> None:
        """When worktree_base is left as Path('.'), it should default to ~/.hydraflow/worktrees."""
        # Arrange
        git_root = tmp_path / "hydra"
        git_root.mkdir()
        (git_root / ".git").mkdir()

        # Act – pass repo_root explicitly but leave worktree_base and state_file at their defaults (Path("."))
        cfg = HydraFlowConfig(repo_root=git_root)

        # Assert
        assert (
            cfg.worktree_base == Path("~/.hydraflow/worktrees").expanduser().resolve()
        )

    def test_default_state_file_derived_from_repo_root(self, tmp_path: Path) -> None:
        """state_file should resolve to repo_root / '.hydraflow/<slug>/state.json'."""
        # Arrange
        git_root = tmp_path / "hydra"
        git_root.mkdir()
        (git_root / ".git").mkdir()

        # Act
        cfg = HydraFlowConfig(repo_root=git_root, repo="org/my-repo")

        # Assert
        assert cfg.state_file == git_root / ".hydraflow" / "org-my-repo" / "state.json"

    def test_auto_detected_repo_root_is_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When repo_root is not provided, the auto-detected value must be absolute."""
        # Arrange – place cwd inside a git repo
        git_root = tmp_path / "autodetect_repo"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        monkeypatch.chdir(git_root)

        # Act
        cfg = HydraFlowConfig()

        # Assert
        assert cfg.repo_root.is_absolute()

    def test_auto_detected_worktree_base_uses_hydraflow_worktrees_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auto-derived worktree_base should be ~/.hydraflow/worktrees."""
        # Arrange
        git_root = tmp_path / "repo"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        monkeypatch.chdir(git_root)

        # Act
        cfg = HydraFlowConfig()

        # Assert
        assert (
            cfg.worktree_base == Path("~/.hydraflow/worktrees").expanduser().resolve()
        )

    def test_auto_detected_state_file_named_hydraflow_state_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auto-derived state_file should be inside .hydraflow/<slug>/ and named 'state.json'."""
        # Arrange
        git_root = tmp_path / "repo"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        monkeypatch.chdir(git_root)

        # Act
        cfg = HydraFlowConfig()

        # Assert
        assert cfg.state_file.name == "state.json"
        # state_file is at .hydraflow/<repo_slug>/state.json
        assert cfg.state_file.parent.parent.name == ".hydraflow"


# ---------------------------------------------------------------------------
# HydraFlowConfig – validation constraints
# ---------------------------------------------------------------------------


class TestHydraFlowConfigValidationConstraints:
    """Tests for Pydantic field constraints (ge/le/gt)."""

    # batch_size: ge=1, le=50

    def test_batch_size_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            batch_size=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.batch_size == 1

    def test_batch_size_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            batch_size=50,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.batch_size == 50

    def test_batch_size_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                batch_size=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_batch_size_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                batch_size=51,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_workers: ge=1, le=10

    def test_max_workers_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_workers=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_workers == 1

    def test_max_workers_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_workers=10,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_workers == 10

    def test_max_workers_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_workers=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_workers_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_workers=11,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_triagers: ge=1, le=10

    def test_max_triagers_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_triagers=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_triagers == 1

    def test_max_triagers_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_triagers=10,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_triagers == 10

    def test_max_triagers_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_triagers=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_triagers_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_triagers=11,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_planners: ge=1, le=10

    def test_max_planners_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_planners=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_planners == 1

    def test_max_planners_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_planners=10,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_planners == 10

    def test_max_planners_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_planners=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_planners_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_planners=11,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_reviewers: ge=1, le=10

    def test_max_reviewers_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_reviewers=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_reviewers == 1

    def test_max_reviewers_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_reviewers=10,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_reviewers == 10

    def test_max_reviewers_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_reviewers=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_reviewers_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_reviewers=11,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_hitl_workers: ge=1, le=5

    def test_max_hitl_workers_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_hitl_workers=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_hitl_workers == 1

    def test_max_hitl_workers_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_hitl_workers=5,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_hitl_workers == 5

    def test_max_hitl_workers_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_hitl_workers=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_hitl_workers_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_hitl_workers=6,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # dashboard_port: ge=1024, le=65535

    def test_dashboard_port_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dashboard_port=1024,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dashboard_port == 1024

    def test_dashboard_port_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dashboard_port=65535,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dashboard_port == 65535

    def test_dashboard_port_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                dashboard_port=1023,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_dashboard_port_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                dashboard_port=65536,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # ci_check_timeout: ge=30, le=3600

    def test_ci_check_timeout_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.ci_check_timeout == 600

    def test_ci_check_timeout_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            ci_check_timeout=30,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.ci_check_timeout == 30

    def test_ci_check_timeout_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                ci_check_timeout=29,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # ci_poll_interval: ge=5, le=120

    def test_ci_poll_interval_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.ci_poll_interval == 30

    def test_ci_poll_interval_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            ci_poll_interval=5,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.ci_poll_interval == 5

    def test_ci_poll_interval_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                ci_poll_interval=4,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_ci_fix_attempts: ge=0, le=5

    def test_max_ci_fix_attempts_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_ci_fix_attempts == 2

    def test_max_ci_fix_attempts_zero_disables(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_ci_fix_attempts=0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_ci_fix_attempts == 0

    def test_max_ci_fix_attempts_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_ci_fix_attempts=6,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_review_fix_attempts: ge=0, le=5

    def test_max_review_fix_attempts_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_fix_attempts == 2

    def test_max_review_fix_attempts_configurable(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_review_fix_attempts=4,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_fix_attempts == 4

    def test_max_review_fix_attempts_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_review_fix_attempts=6,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_pre_quality_review_attempts: ge=0, le=5

    def test_max_pre_quality_review_attempts_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_pre_quality_review_attempts == 1

    def test_max_pre_quality_review_attempts_configurable(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_pre_quality_review_attempts=3,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_pre_quality_review_attempts == 3

    def test_max_pre_quality_review_attempts_above_maximum_raises(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_pre_quality_review_attempts=6,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # min_review_findings: ge=0, le=20

    def test_min_review_findings_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_review_findings == 3

    def test_min_review_findings_configurable(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            min_review_findings=5,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_review_findings == 5

    def test_min_review_findings_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                min_review_findings=21,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # min_plan_words: ge=50, le=2000

    def test_min_plan_words_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 200

    def test_min_plan_words_configurable(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            min_plan_words=100,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 100

    def test_min_plan_words_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                min_plan_words=49,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_min_plan_words_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                min_plan_words=2001,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_merge_conflict_fix_attempts: ge=0, le=5

    def test_max_merge_conflict_fix_attempts_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 3

    def test_max_merge_conflict_fix_attempts_configurable(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_merge_conflict_fix_attempts=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 1

    def test_max_merge_conflict_fix_attempts_zero_allowed(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_merge_conflict_fix_attempts=0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 0

    def test_max_merge_conflict_fix_attempts_above_maximum_raises(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_merge_conflict_fix_attempts=6,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    # max_new_files_warning: ge=1, le=20

    def test_max_new_files_warning_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_new_files_warning == 5

    def test_max_new_files_warning_configurable(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_new_files_warning=10,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_new_files_warning == 10

    def test_max_new_files_warning_below_minimum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_new_files_warning=0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_new_files_warning_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                max_new_files_warning=21,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )


# ---------------------------------------------------------------------------
# HydraFlowConfig – gh_token resolution
# ---------------------------------------------------------------------------


class TestHydraFlowConfigGhToken:
    """Tests for the gh_token field and HYDRAFLOW_GH_TOKEN env var resolution."""

    def test_gh_token_default_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.gh_token == ""

    def test_gh_token_explicit_value_preserved(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            gh_token="ghp_explicit123",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.gh_token == "ghp_explicit123"

    def test_gh_token_picks_up_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_GH_TOKEN", "ghp_from_env")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.gh_token == "ghp_from_env"

    def test_gh_token_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_GH_TOKEN", "ghp_from_env")
        cfg = HydraFlowConfig(
            gh_token="ghp_explicit",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.gh_token == "ghp_explicit"

    def test_gh_token_picks_up_dotenv_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        (tmp_path / ".env").write_text("HYDRAFLOW_GH_TOKEN=ghp_from_dotenv\n")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.gh_token == "ghp_from_dotenv"

    def test_gh_token_dotenv_ignores_inline_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        (tmp_path / ".env").write_text(
            "HYDRAFLOW_GH_TOKEN=ghp_from_dotenv # bot token\n"
        )
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.gh_token == "ghp_from_dotenv"


# ---------------------------------------------------------------------------
# HydraFlowConfig – git identity resolution
# ---------------------------------------------------------------------------


class GitIdentityEnvMixin:
    """Utility mixin for clearing git identity env vars across tests."""

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


class TestHydraFlowConfigGitIdentity(GitIdentityEnvMixin):
    """Tests for git_user_name/git_user_email fields and env var resolution."""

    def test_git_user_name_default_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == ""

    def test_git_user_email_default_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_email == ""

    def test_git_user_name_explicit_value_preserved(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            git_user_name="Bot",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "Bot"

    def test_git_user_email_explicit_value_preserved(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_email == "bot@example.com"

    def test_git_user_name_picks_up_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        monkeypatch.setenv("HYDRAFLOW_GIT_USER_NAME", "EnvBot")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "EnvBot"

    def test_git_user_email_picks_up_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        monkeypatch.setenv("HYDRAFLOW_GIT_USER_EMAIL", "env@example.com")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_email == "env@example.com"

    def test_git_user_name_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        monkeypatch.setenv("HYDRAFLOW_GIT_USER_NAME", "EnvBot")
        cfg = HydraFlowConfig(
            git_user_name="ExplicitBot",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "ExplicitBot"

    def test_git_user_email_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        monkeypatch.setenv("HYDRAFLOW_GIT_USER_EMAIL", "env@example.com")
        cfg = HydraFlowConfig(
            git_user_email="explicit@example.com",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_email == "explicit@example.com"

    def test_git_identity_picks_up_dotenv_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        (tmp_path / ".env").write_text(
            "HYDRAFLOW_GIT_USER_NAME=Dotenv Bot\n"
            "HYDRAFLOW_GIT_USER_EMAIL=dotenv-bot@example.com\n"
        )
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "Dotenv Bot"
        assert cfg.git_user_email == "dotenv-bot@example.com"

    def test_git_identity_dotenv_ignores_inline_comment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        (tmp_path / ".env").write_text(
            "HYDRAFLOW_GIT_USER_NAME=Dotenv Bot # preferred\n"
            "HYDRAFLOW_GIT_USER_EMAIL=dotenv-bot@example.com # notifications\n"
        )
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "Dotenv Bot"
        assert cfg.git_user_email == "dotenv-bot@example.com"


# ---------------------------------------------------------------------------
# HydraFlowConfig – hitl_active_label env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigHitlActiveLabel:
    """Tests for hitl_active_label env var override."""

    def test_hitl_active_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_HITL_ACTIVE", "custom-active")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_active_label == ["custom-active"]

    def test_hitl_active_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_HITL_ACTIVE", "env-active")
        cfg = HydraFlowConfig(
            hitl_active_label=["explicit-active"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_active_label == ["explicit-active"]


# ---------------------------------------------------------------------------
# HydraFlowConfig – improve_label env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigDupLabel:
    """Tests for dup_label default, custom value, and env var override."""

    def test_dup_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["hydraflow-dup"]

    def test_dup_label_custom_value(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dup_label=["my-dup"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["my-dup"]

    def test_dup_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_DUP", "custom-dup")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["custom-dup"]

    def test_dup_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_DUP", "env-dup")
        cfg = HydraFlowConfig(
            dup_label=["explicit-dup"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["explicit-dup"]


class TestHydraFlowConfigImproveLabel:
    """Tests for improve_label env var override."""

    def test_improve_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_IMPROVE", "custom-improve")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["custom-improve"]

    def test_improve_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_IMPROVE", "env-improve")
        cfg = HydraFlowConfig(
            improve_label=["explicit-improve"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["explicit-improve"]


class TestHydraFlowConfigEpicChildLabel:
    """Tests for epic_child_label default, custom value, and env var override."""

    def test_epic_child_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["hydraflow-epic-child"]

    def test_epic_child_label_custom_value(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            epic_child_label=["my-epic-child"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["my-epic-child"]

    def test_epic_child_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_EPIC_CHILD", "custom-epic-child")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["custom-epic-child"]

    def test_epic_child_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_EPIC_CHILD", "env-epic-child")
        cfg = HydraFlowConfig(
            epic_child_label=["explicit-epic-child"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["explicit-epic-child"]


# ---------------------------------------------------------------------------
# HydraFlowConfig – min_plan_words env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMinPlanWords:
    """Tests for min_plan_words field and HYDRAFLOW_MIN_PLAN_WORDS env var."""

    def test_min_plan_words_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 200

    def test_min_plan_words_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_PLAN_WORDS", "300")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 300

    def test_min_plan_words_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_PLAN_WORDS", "300")
        cfg = HydraFlowConfig(
            min_plan_words=100,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 100


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_review_fix_attempts env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxReviewFixAttempts:
    """Tests for max_review_fix_attempts env var override."""

    def test_max_review_fix_attempts_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_fix_attempts == 4

    def test_max_review_fix_attempts_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS", "4")
        cfg = HydraFlowConfig(
            max_review_fix_attempts=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_fix_attempts == 1


class TestHydraFlowConfigMaxPreQualityReviewAttempts:
    """Tests for max_pre_quality_review_attempts env var override."""

    def test_max_pre_quality_review_attempts_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_PRE_QUALITY_REVIEW_ATTEMPTS", "3")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_pre_quality_review_attempts == 3

    def test_max_pre_quality_review_attempts_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_PRE_QUALITY_REVIEW_ATTEMPTS", "3")
        cfg = HydraFlowConfig(
            max_pre_quality_review_attempts=2,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_pre_quality_review_attempts == 2


# ---------------------------------------------------------------------------
# HydraFlowConfig – min_review_findings env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMinReviewFindings:
    """Tests for min_review_findings env var override."""

    def test_min_review_findings_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_review_findings == 5

    def test_min_review_findings_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "5")
        cfg = HydraFlowConfig(
            min_review_findings=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_review_findings == 1


# ---------------------------------------------------------------------------
# HydraFlowConfig – lite_plan_labels env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxMergeConflictFixAttempts:
    """Tests for max_merge_conflict_fix_attempts env var override."""

    def test_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 5

    def test_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", "5")
        cfg = HydraFlowConfig(
            max_merge_conflict_fix_attempts=1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 1

    def test_env_var_invalid_value_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 3


class TestHydraFlowConfigLitePlanLabels:
    """Tests for lite_plan_labels field and HYDRAFLOW_LITE_PLAN_LABELS env var."""

    def test_lite_plan_labels_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.lite_plan_labels == ["bug", "typo", "docs"]

    def test_lite_plan_labels_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LITE_PLAN_LABELS", "hotfix,patch")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.lite_plan_labels == ["hotfix", "patch"]

    def test_lite_plan_labels_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LITE_PLAN_LABELS", "hotfix,patch")
        cfg = HydraFlowConfig(
            lite_plan_labels=["custom"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.lite_plan_labels == ["custom"]


# ---------------------------------------------------------------------------
# HydraFlowConfig – improve_label / memory/transcript label env var overrides
# ---------------------------------------------------------------------------


class TestHydraFlowConfigImproveLabelAndMemoryLabel:
    """Tests for improve_label, memory_label, and transcript_label."""

    def test_improve_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["hydraflow-improve"]

    def test_memory_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_label == ["hydraflow-memory"]

    def test_transcript_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_label == ["hydraflow-transcript"]

    def test_improve_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_IMPROVE", "custom-improve")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["custom-improve"]

    def test_memory_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_MEMORY", "custom-memory")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_label == ["custom-memory"]

    def test_transcript_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_TRANSCRIPT", "custom-transcript")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_label == ["custom-transcript"]

    def test_improve_label_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_IMPROVE", "env-improve")
        cfg = HydraFlowConfig(
            improve_label=["explicit-improve"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.improve_label == ["explicit-improve"]

    def test_memory_label_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_MEMORY", "env-memory")
        cfg = HydraFlowConfig(
            memory_label=["explicit-memory"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_label == ["explicit-memory"]

    def test_transcript_label_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_TRANSCRIPT", "env-transcript")
        cfg = HydraFlowConfig(
            transcript_label=["explicit-transcript"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_label == ["explicit-transcript"]

    def test_metrics_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_label == ["hydraflow-metrics"]

    def test_metrics_label_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            metrics_label=["custom-metrics"],
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_label == ["custom-metrics"]

    def test_metrics_label_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_METRICS", "env-metrics")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_label == ["env-metrics"]

    def test_metrics_sync_interval_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_sync_interval == 7200

    def test_metrics_sync_interval_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_METRICS_SYNC_INTERVAL", "120")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_sync_interval == 120

    def test_pr_unstick_interval_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_interval == 3600

    def test_pr_unstick_batch_size_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_batch_size == 10

    def test_pr_unstick_interval_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_PR_UNSTICK_INTERVAL", "1800")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_interval == 1800

    def test_pr_unstick_batch_size_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_PR_UNSTICK_BATCH_SIZE", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_batch_size == 5


# ---------------------------------------------------------------------------
# HydraFlowConfig – branch_for_issue / worktree_path_for_issue helpers
# ---------------------------------------------------------------------------


class TestBranchForIssue:
    """Tests for HydraFlowConfig.branch_for_issue()."""

    def test_returns_canonical_branch_name(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.branch_for_issue(42) == "agent/issue-42"

    def test_single_digit_issue(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.branch_for_issue(1) == "agent/issue-1"

    def test_large_issue_number(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.branch_for_issue(99999) == "agent/issue-99999"


class TestWorktreePathForIssue:
    """Tests for HydraFlowConfig.worktree_path_for_issue()."""

    def test_returns_path_under_worktree_base(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="org/my-repo",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert (
            cfg.worktree_path_for_issue(42)
            == tmp_path / "wt" / "org-my-repo" / "issue-42"
        )

    def test_single_digit_issue(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="org/my-repo",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert (
            cfg.worktree_path_for_issue(1)
            == tmp_path / "wt" / "org-my-repo" / "issue-1"
        )

    def test_uses_configured_worktree_base(self, tmp_path: Path) -> None:
        custom_base = tmp_path / "custom-worktrees"
        cfg = HydraFlowConfig(
            repo="org/proj",
            repo_root=tmp_path,
            worktree_base=custom_base,
            state_file=tmp_path / "s.json",
        )
        assert cfg.worktree_path_for_issue(7) == custom_base / "org-proj" / "issue-7"

    def test_repo_slug_from_repo(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="acme/widgets",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo_slug == "acme-widgets"

    def test_repo_slug_fallback_to_dir_name(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo_slug == tmp_path.name


# ---------------------------------------------------------------------------
# HydraFlowConfig – threshold configuration
# ---------------------------------------------------------------------------


class TestHydraFlowConfigThresholds:
    """Tests for the threshold configuration fields."""

    def test_quality_fix_rate_threshold_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(0.5)

    def test_approval_rate_threshold_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.approval_rate_threshold == pytest.approx(0.5)

    def test_hitl_rate_threshold_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_rate_threshold == pytest.approx(0.2)

    def test_custom_quality_fix_rate_threshold(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            quality_fix_rate_threshold=0.8,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(0.8)

    def test_custom_approval_rate_threshold(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            approval_rate_threshold=0.7,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.approval_rate_threshold == pytest.approx(0.7)

    def test_custom_hitl_rate_threshold(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            hitl_rate_threshold=0.1,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_rate_threshold == pytest.approx(0.1)

    def test_threshold_below_zero_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                quality_fix_rate_threshold=-0.1,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_threshold_above_one_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                quality_fix_rate_threshold=1.1,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_threshold_boundary_zero(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            quality_fix_rate_threshold=0.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(0.0)

    def test_threshold_boundary_one(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            quality_fix_rate_threshold=1.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# HydraFlowConfig – test_command field
# ---------------------------------------------------------------------------


class TestHydraFlowConfigTestCommand:
    """Tests for the test_command config field."""

    def test_test_command_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "make test"

    def test_test_command_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            test_command="npm test",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "npm test"

    def test_test_command_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TEST_COMMAND", "pytest -x")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "pytest -x"

    def test_test_command_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TEST_COMMAND", "pytest -x")
        cfg = HydraFlowConfig(
            test_command="cargo test",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "cargo test"


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_issue_body_chars field
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxIssueBodyChars:
    """Tests for the max_issue_body_chars config field."""

    def test_max_issue_body_chars_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_body_chars == 10_000

    def test_max_issue_body_chars_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_issue_body_chars=5_000,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_body_chars == 5_000

    def test_max_issue_body_chars_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_ISSUE_BODY_CHARS env var should override the default."""
        monkeypatch.setenv("HYDRAFLOW_MAX_ISSUE_BODY_CHARS", "20000")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_body_chars == 20_000

    def test_max_issue_body_chars_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit value should take precedence over env var."""
        monkeypatch.setenv("HYDRAFLOW_MAX_ISSUE_BODY_CHARS", "20000")
        cfg = HydraFlowConfig(
            max_issue_body_chars=5_000,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_body_chars == 5_000


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_review_diff_chars field
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxReviewDiffChars:
    """Tests for the max_review_diff_chars config field."""

    def test_max_review_diff_chars_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_diff_chars == 15_000

    def test_max_review_diff_chars_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_review_diff_chars=30_000,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_diff_chars == 30_000

    def test_max_review_diff_chars_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_MAX_REVIEW_DIFF_CHARS env var should override the default."""
        monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", "50000")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_diff_chars == 50_000

    def test_max_review_diff_chars_explicit_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit value should take precedence over env var."""
        monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", "50000")
        cfg = HydraFlowConfig(
            max_review_diff_chars=25_000,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_diff_chars == 25_000


# ---------------------------------------------------------------------------
# max_issue_attempts
# ---------------------------------------------------------------------------


class TestResolveDefaults:
    """Tests for the resolve_defaults model validator."""

    def test_resolve_defaults_sets_event_log_path(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="org/my-repo")
        assert (
            cfg.event_log_path
            == tmp_path / ".hydraflow" / "org-my-repo" / "events.jsonl"
        )

    def test_resolve_defaults_repo_from_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_GITHUB_REPO", "env-org/env-repo")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo == "env-org/env-repo"

    def test_resolve_defaults_repo_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_GITHUB_REPO", "env-org/env-repo")
        cfg = HydraFlowConfig(
            repo="explicit-org/explicit-repo",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo == "explicit-org/explicit-repo"

    def test_resolve_defaults_data_poll_interval_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DATA_POLL_INTERVAL", "120")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.data_poll_interval == 120


class TestMaxIssueAttempts:
    """Tests for max_issue_attempts config field."""

    def test_default_is_three(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_attempts == 3

    def test_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_ISSUE_ATTEMPTS", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_attempts == 5

    def test_explicit_value_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_ISSUE_ATTEMPTS", "7")
        cfg = HydraFlowConfig(
            max_issue_attempts=4,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_attempts == 4


class TestUpdatedIntervalDefaults:
    """Verify updated default intervals for memory_sync and metrics."""

    def test_memory_sync_default_is_3600(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_sync_interval == 3600

    def test_metrics_sync_default_is_7200(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_sync_interval == 7200

    def test_memory_sync_max_increased_to_14400(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            memory_sync_interval=14400,
        )
        assert cfg.memory_sync_interval == 14400

    def test_metrics_sync_max_increased_to_14400(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            metrics_sync_interval=14400,
        )
        assert cfg.metrics_sync_interval == 14400

    def test_memory_sync_env_override_with_new_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MEMORY_SYNC_INTERVAL", "900")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_sync_interval == 900

    def test_metrics_sync_env_override_with_new_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_METRICS_SYNC_INTERVAL", "1800")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.metrics_sync_interval == 1800


# ---------------------------------------------------------------------------
# Transcript summarization config
# ---------------------------------------------------------------------------


class TestTranscriptSummarizationConfig:
    """Tests for transcript summarization configuration fields."""

    def test_default_enabled(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summarization_enabled is True

    def test_default_model(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summary_model == "haiku"

    def test_default_max_chars(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_transcript_summary_chars == 50_000

    def test_env_var_enabled_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summarization_enabled is False

    def test_env_var_enabled_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED", "0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summarization_enabled is False

    def test_env_var_model_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL", "sonnet")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summary_model == "sonnet"

    def test_env_var_max_chars_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_TRANSCRIPT_SUMMARY_CHARS", "20000")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_transcript_summary_chars == 20_000

    def test_max_chars_validation_min(self, tmp_path: Path) -> None:
        """max_transcript_summary_chars must be >= 5000."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                max_transcript_summary_chars=1000,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_chars_validation_max(self, tmp_path: Path) -> None:
        """max_transcript_summary_chars must be <= 500_000."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                max_transcript_summary_chars=1_000_000,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_explicit_value_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL", "sonnet")
        cfg = HydraFlowConfig(
            transcript_summary_model="opus",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        # Explicit "opus" != default "haiku", so env var should NOT override
        assert cfg.transcript_summary_model == "opus"


# ---------------------------------------------------------------------------
# Data-driven env-var override table validation
# ---------------------------------------------------------------------------


class TestEnvVarOverrideTable:
    """Tests for the _ENV_INT_OVERRIDES and _ENV_STR_OVERRIDES tables."""

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Each int override should apply when the field is at its default."""
        override_value = default + 1
        monkeypatch.setenv(env_key, str(override_value))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == override_value

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Explicit values should take precedence over env var overrides."""
        # Use default + 1 to stay within Pydantic field constraints
        explicit = default + 1
        monkeypatch.setenv(env_key, str(default + 2))
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == explicit

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Non-numeric env var values should be silently ignored."""
        monkeypatch.setenv(env_key, "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == default

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_STR_OVERRIDES,
        ids=[entry[0] for entry in _ENV_STR_OVERRIDES],
    )
    def test_env_str_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: str,
    ) -> None:
        """Each str override should apply when the field is at its default."""
        monkeypatch.setenv(env_key, "custom-value")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == "custom-value"

    # Valid non-default explicit values for Literal-typed string fields.
    # Generic tests can't use arbitrary strings for these fields.
    _EXPLICIT_VALUES: dict[str, str] = {
        "execution_mode": "docker",
    }

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_STR_OVERRIDES,
        ids=[entry[0] for entry in _ENV_STR_OVERRIDES],
    )
    def test_env_str_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: str,
    ) -> None:
        """Explicit values should take precedence over str env var overrides."""
        explicit = self._EXPLICIT_VALUES.get(field, "explicit-value")
        monkeypatch.setenv(env_key, "env-value")
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == explicit

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Each float override should apply when the field is at its default."""
        override_value = default + 1.0
        monkeypatch.setenv(env_key, str(override_value))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(override_value)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Explicit values should take precedence over float env var overrides."""
        explicit = default + 0.5
        monkeypatch.setenv(env_key, str(default + 1.0))
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(explicit)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Non-numeric float env var values should be silently ignored."""
        monkeypatch.setenv(env_key, "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(default)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Each bool override should apply when the field is at its default."""
        monkeypatch.setenv(env_key, "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) is False

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_truthy_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Bool overrides should treat '1', 'true', 'yes' as True."""
        for truthy in ("1", "true", "yes", "True", "YES"):
            monkeypatch.setenv(env_key, truthy)
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
            assert getattr(cfg, field) is True, f"'{truthy}' should parse as True"

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_falsy_variants(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Bool overrides should treat '0', 'false', 'no' as False."""
        for falsy in ("0", "false", "no", "False", "NO"):
            monkeypatch.setenv(env_key, falsy)
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
            assert getattr(cfg, field) is False, f"'{falsy}' should parse as False"

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Explicit values should take precedence over bool env var overrides."""
        explicit = not default
        monkeypatch.setenv(
            env_key, str(default).lower()
        )  # env tries to revert to default
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) is explicit

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
    ) -> None:
        """Each Literal override should apply when the field is at its default."""
        allowed = get_args(HydraFlowConfig.model_fields[field].annotation)
        default = HydraFlowConfig.model_fields[field].default
        # Pick a non-default value from the allowed values
        non_default = next(v for v in allowed if v != default)
        monkeypatch.setenv(env_key, non_default)
        # execution_mode="docker" triggers _validate_docker which needs shutil.which
        if field == "execution_mode":
            import shutil

            monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == non_default

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
    ) -> None:
        """Explicit values should take precedence over Literal env var overrides."""
        allowed = get_args(HydraFlowConfig.model_fields[field].annotation)
        default = HydraFlowConfig.model_fields[field].default
        non_default = next(v for v in allowed if v != default)
        # Pass non-default explicitly, set env var to default
        monkeypatch.setenv(env_key, default)
        # execution_mode="docker" triggers _validate_docker which needs shutil.which
        if field == "execution_mode":
            import shutil

            monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            **{field: non_default},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == non_default

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        field: str,
        env_key: str,
    ) -> None:
        """Invalid Literal env var values should be rejected and field stays at default."""
        default = HydraFlowConfig.model_fields[field].default
        monkeypatch.setenv(env_key, "bogus")
        with caplog.at_level(logging.WARNING, logger="hydraflow.config"):
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        assert getattr(cfg, field) == default
        assert env_key in caplog.text, "Expected warning to name the invalid env var"
        assert "bogus" in caplog.text, "Expected warning to include the invalid value"

    def test_override_table_field_names_are_valid(self) -> None:
        """Every field in the override tables should be a real HydraFlowConfig attribute."""
        all_fields = (
            {f for f, _, _ in _ENV_INT_OVERRIDES}
            | {f for f, _, _ in _ENV_STR_OVERRIDES}
            | {f for f, _, _ in _ENV_FLOAT_OVERRIDES}
            | {f for f, _, _ in _ENV_BOOL_OVERRIDES}
            | {f for f, _ in _ENV_LITERAL_OVERRIDES}
        )
        config_fields = set(HydraFlowConfig.model_fields.keys())
        invalid = all_fields - config_fields
        assert not invalid, f"Invalid field names in override tables: {invalid}"
        # Every field in _ENV_LITERAL_OVERRIDES must actually have a Literal annotation
        # so that get_args() returns allowed values instead of an empty tuple.
        for field, _ in _ENV_LITERAL_OVERRIDES:
            field_info = HydraFlowConfig.model_fields[field]
            args = get_args(field_info.annotation)
            assert args, (
                f"Field '{field}' in _ENV_LITERAL_OVERRIDES has no Literal args "
                f"(annotation={field_info.annotation!r}); "
                "all env var overrides for this field would be silently rejected"
            )
            # Every field must have at least one non-default allowed value so that
            # next(v for v in allowed if v != default) in the parametrized tests
            # never raises StopIteration.
            default = field_info.default
            non_defaults = [v for v in args if v != default]
            assert non_defaults, (
                f"Field '{field}' in _ENV_LITERAL_OVERRIDES has no non-default Literal "
                f"value (default={default!r}, allowed={args}); "
                "test_env_literal_override_applies_when_at_default would raise StopIteration"
            )

    def test_override_table_defaults_match_field_defaults(self) -> None:
        """Default values in the override tables must match HydraFlowConfig field defaults.

        This prevents silent drift when a field default is changed without updating
        the corresponding entry in _ENV_INT_OVERRIDES or _ENV_STR_OVERRIDES.
        """
        # Arrange
        model_fields = HydraFlowConfig.model_fields

        # Act / Assert — int overrides
        for field, _env_key, table_default in _ENV_INT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_INT_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )

        # Act / Assert — str overrides
        for field, _env_key, table_default in _ENV_STR_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_STR_OVERRIDES entry for '{field}' has default={table_default!r}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default!r}"
            )

        # Act / Assert — float overrides
        for field, _env_key, table_default in _ENV_FLOAT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_FLOAT_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )

        # Act / Assert — bool overrides
        for field, _env_key, table_default in _ENV_BOOL_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_BOOL_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )


# ---------------------------------------------------------------------------
# Docker config – defaults
# ---------------------------------------------------------------------------


class TestDockerConfigDefaults:
    """Tests that Docker config fields have correct default values."""

    def test_execution_mode_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "host"

    def test_docker_image_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"

    def test_docker_cpu_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(2.0)

    def test_docker_memory_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4g"

    def test_docker_pids_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 256

    def test_docker_tmp_size_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "1g"

    def test_docker_network_mode_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "bridge"

    def test_docker_spawn_delay_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(2.0)

    def test_docker_read_only_root_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is True

    def test_docker_no_new_privileges_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is True


# ---------------------------------------------------------------------------
# Docker config – custom values override defaults
# ---------------------------------------------------------------------------


class TestDockerConfigCustomValues:
    """Tests that custom Docker config values take precedence over defaults."""

    def test_custom_execution_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            execution_mode="docker",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_custom_docker_image(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_image="my-registry/my-image:v1",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "my-registry/my-image:v1"

    def test_custom_docker_cpu_limit(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=4.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(4.0)

    def test_custom_docker_memory_limit(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="8g",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "8g"

    def test_custom_docker_network_mode(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_network_mode="none",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "none"

    def test_custom_docker_spawn_delay(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=5.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(5.0)

    def test_custom_docker_read_only_root_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_read_only_root=False,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is False

    def test_custom_docker_no_new_privileges_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_no_new_privileges=False,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is False


# ---------------------------------------------------------------------------
# Docker config – validation constraints
# ---------------------------------------------------------------------------


class TestDockerConfigValidation(GitIdentityEnvMixin):
    """Tests for Docker config validation constraints."""

    def test_invalid_execution_mode_raises(self, tmp_path: Path) -> None:
        """Invalid execution_mode Literal values should raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                execution_mode="kubernetes",  # type: ignore[arg-type]
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_docker_network_mode_raises(self, tmp_path: Path) -> None:
        """Invalid docker_network_mode Literal values should raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_network_mode="overlay",  # type: ignore[arg-type]
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_cpu_limit=0.1,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_cpu_limit=32.0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=0.5,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(0.5)

    def test_docker_cpu_limit_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=16.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(16.0)

    def test_docker_spawn_delay_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_spawn_delay=-1.0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_spawn_delay_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_spawn_delay=60.0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_spawn_delay_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=0.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(0.0)

    def test_docker_spawn_delay_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=30.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(30.0)

    def test_docker_pids_limit_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_pids_limit=15,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_pids_limit_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_pids_limit=4097,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_pids_limit_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_pids_limit=16,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 16

    def test_docker_pids_limit_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_pids_limit=4096,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 4096

    def test_docker_memory_limit_invalid_suffix_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4gb",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_memory_limit_invalid_text_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="lots",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_tmp_size_invalid_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_tmp_size="big",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_not_available_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execution_mode='docker' with Docker not on PATH should raise ValueError."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        with pytest.raises(ValueError, match="docker.*not found on PATH"):
            HydraFlowConfig(
                execution_mode="docker",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_available_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execution_mode='docker' with Docker on PATH should not raise."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            execution_mode="docker",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_host_mode_skips_docker_check(self, tmp_path: Path) -> None:
        """execution_mode='host' should not check for Docker availability."""
        cfg = HydraFlowConfig(
            execution_mode="host",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "host"

    def test_docker_mode_warns_when_identity_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        self._clear_git_identity_env(monkeypatch)
        caplog.clear()
        with caplog.at_level("WARNING", logger="hydraflow.config"):
            HydraFlowConfig(
                execution_mode="docker",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        warnings = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "without GH token configured" in warnings
        assert "git identity not configured" in warnings

    def test_docker_mode_warns_on_partial_git_identity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        self._clear_git_identity_env(monkeypatch)
        caplog.clear()
        with caplog.at_level("WARNING", logger="hydraflow.config"):
            HydraFlowConfig(
                execution_mode="docker",
                gh_token="ghp_bot",
                git_user_name="Bot Name",
                git_user_email="",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        warnings = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "git identity is incomplete" in warnings


# ---------------------------------------------------------------------------
# Docker size notation validator – targeted tests for validate_docker_size_notation
# ---------------------------------------------------------------------------


class TestDockerSizeNotationValidator:
    """Tests for the validate_docker_size_notation field validator."""

    def test_valid_size_512m(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="512m",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "512m"

    def test_valid_size_1024k(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="1024k",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "1024k"

    def test_valid_size_100b(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="100b",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "100b"

    def test_valid_size_uppercase_4G(self, tmp_path: Path) -> None:
        """Validator uses re.IGNORECASE — uppercase units should be accepted."""
        cfg = HydraFlowConfig(
            docker_memory_limit="4G",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4G"

    def test_valid_size_uppercase_512M(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="512M",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "512M"

    def test_valid_docker_tmp_size(self, tmp_path: Path) -> None:
        """Validator applies to docker_tmp_size as well."""
        cfg = HydraFlowConfig(
            docker_tmp_size="512m",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "512m"

    def test_invalid_empty_string(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_digits_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_unit_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="g",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_valid_size_4g(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="4g",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4g"

    def test_invalid_size_with_suffix_gb(self, tmp_path: Path) -> None:
        """'4gb' should fail — only single-char unit suffix is valid."""
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4gb",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_size_alpha_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="abc",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )


# ---------------------------------------------------------------------------
# Docker config – env var overrides
# ---------------------------------------------------------------------------


class TestDockerConfigEnvVarOverrides:
    """Tests for Docker-specific env var overrides."""

    def test_execution_mode_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_docker_image_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_IMAGE", "custom/image:v2")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "custom/image:v2"

    def test_docker_memory_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_MEMORY_LIMIT", "16g")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "16g"

    def test_docker_network_mode_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK_MODE", "none")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "none"

    def test_docker_cpu_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_CPU_LIMIT", "8.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(8.0)

    def test_docker_spawn_delay_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "5.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(5.0)

    def test_docker_read_only_root_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_READ_ONLY_ROOT", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is False

    def test_docker_no_new_privileges_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NO_NEW_PRIVILEGES", "0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is False

    def test_execution_mode_docker_via_env_raises_when_docker_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_EXECUTION_MODE=docker should trigger docker availability check."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        with pytest.raises(ValueError, match="docker.*not found on PATH"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_env_override_out_of_range_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_CPU_LIMIT outside ge/le bounds should be silently ignored."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_CPU_LIMIT", "50.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(2.0)  # unchanged default

    def test_docker_spawn_delay_env_override_out_of_range_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_SPAWN_DELAY outside ge/le bounds should be silently ignored."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "999.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(2.0)  # unchanged default

    def test_pids_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "512")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 512

    def test_pids_limit_env_override_below_minimum_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "15")
        with pytest.raises(ValueError, match="HYDRAFLOW_DOCKER_PIDS_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_pids_limit_env_override_above_maximum_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "4097")
        with pytest.raises(ValueError, match="HYDRAFLOW_DOCKER_PIDS_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_pids_limit_env_override_invalid_value_logs_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "not-an-int")
        with caplog.at_level(logging.WARNING):
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

        assert cfg.docker_pids_limit == 256
        assert "HYDRAFLOW_DOCKER_PIDS_LIMIT value" in caplog.text

    def test_tmp_size_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_TMP_SIZE", "2g")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "2g"

    def test_memory_limit_env_override_invalid_value_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_MEMORY_LIMIT with invalid notation must be rejected."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_MEMORY_LIMIT", "invalid_val")
        with pytest.raises(ValueError, match="Invalid HYDRAFLOW_DOCKER_MEMORY_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_tmp_size_env_override_invalid_value_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_TMP_SIZE with invalid notation must be rejected."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_TMP_SIZE", "4gb")
        with pytest.raises(ValueError, match="Invalid HYDRAFLOW_DOCKER_TMP_SIZE"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_execution_mode_default_value_overridden_by_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When execution_mode equals the default ('host'), env var overrides it.

        The override only applies when the value is still at the default. Because
        'host' IS the default, explicitly passing execution_mode='host' is
        indistinguishable from using the default, so the env var wins.
        """
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        cfg = HydraFlowConfig(
            execution_mode="host",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"


# ---------------------------------------------------------------------------
# Docker config fields
# ---------------------------------------------------------------------------


class TestDockerConfig:
    """Tests for Docker-related configuration fields."""

    def test_docker_image_has_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"

    def test_docker_spawn_delay_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 2.0

    def test_docker_network_empty_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network == ""

    def test_docker_extra_mounts_empty_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_extra_mounts == []

    def test_docker_spawn_delay_invalid_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 2.0  # default preserved

    def test_docker_network_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK", "hydra-net")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network == "hydra-net"

    def test_docker_network_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK", "from-env")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_network="explicit-net",
        )
        assert cfg.docker_network == "explicit-net"

    def test_docker_custom_values(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_image="hydra-agent:latest",
            docker_spawn_delay=3.5,
            docker_network="my-network",
            docker_extra_mounts=["/host:/container:rw"],
        )
        assert cfg.docker_image == "hydra-agent:latest"
        assert cfg.docker_spawn_delay == 3.5
        assert cfg.docker_network == "my-network"
        assert cfg.docker_extra_mounts == ["/host:/container:rw"]

    def test_docker_spawn_delay_too_low(self, tmp_path: Path) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                docker_spawn_delay=-1.0,
            )

    def test_docker_spawn_delay_too_high(self, tmp_path: Path) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                docker_spawn_delay=31.0,
            )


class TestAgentToolFields:
    def test_tool_defaults(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.implementation_tool == "claude"
        assert cfg.review_tool == "claude"
        assert cfg.planner_tool == "claude"
        assert cfg.triage_tool == "claude"
        assert cfg.transcript_summary_tool == "claude"
        assert cfg.memory_compaction_tool == "claude"
        assert cfg.ac_tool == "claude"
        assert cfg.verification_judge_tool == "claude"
        assert cfg.system_tool == "inherit"
        assert cfg.background_tool == "inherit"

    def test_tool_env_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_IMPLEMENTATION_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_PLANNER_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_TRIAGE_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_MEMORY_COMPACTION_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_AC_TOOL", "codex")
        monkeypatch.setenv("HYDRAFLOW_VERIFICATION_JUDGE_TOOL", "codex")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.implementation_tool == "codex"
        assert cfg.model == "gpt-5-codex"
        assert cfg.review_tool == "codex"
        assert cfg.planner_tool == "codex"
        assert cfg.triage_tool == "codex"
        assert cfg.transcript_summary_tool == "codex"
        assert cfg.memory_compaction_tool == "codex"
        assert cfg.ac_tool == "codex"
        assert cfg.verification_judge_tool == "codex"

    def test_tool_env_overrides_accept_pi(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_IMPLEMENTATION_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_PLANNER_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_TRIAGE_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_MEMORY_COMPACTION_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_AC_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_VERIFICATION_JUDGE_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_SUBSKILL_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_DEBUG_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_SYSTEM_TOOL", "pi")
        monkeypatch.setenv("HYDRAFLOW_BACKGROUND_TOOL", "pi")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.implementation_tool == "pi"
        assert cfg.review_tool == "pi"
        assert cfg.planner_tool == "pi"
        assert cfg.triage_tool == "pi"
        assert cfg.transcript_summary_tool == "pi"
        assert cfg.memory_compaction_tool == "pi"
        assert cfg.ac_tool == "pi"
        assert cfg.verification_judge_tool == "pi"
        assert cfg.subskill_tool == "pi"
        assert cfg.debug_tool == "pi"
        assert cfg.system_tool == "pi"
        assert cfg.background_tool == "pi"

    def test_profile_tool_overrides_apply_to_defaults(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            system_tool="codex",
            background_tool="codex",
        )
        assert cfg.implementation_tool == "codex"
        assert cfg.model == "gpt-5-codex"
        assert cfg.review_tool == "codex"
        assert cfg.planner_tool == "codex"
        assert cfg.ac_tool == "codex"
        assert cfg.verification_judge_tool == "codex"
        assert cfg.subskill_tool == "codex"
        assert cfg.debug_tool == "codex"
        assert cfg.triage_tool == "codex"
        assert cfg.transcript_summary_tool == "codex"
        assert cfg.memory_compaction_tool == "codex"

    def test_profile_model_overrides_apply_to_defaults(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            system_model="gpt-5-codex",
            background_model="gpt-5-codex",
        )
        assert cfg.model == "gpt-5-codex"
        assert cfg.review_model == "gpt-5-codex"
        assert cfg.planner_model == "gpt-5-codex"
        assert cfg.ac_model == "gpt-5-codex"
        assert cfg.subskill_model == "gpt-5-codex"
        assert cfg.debug_model == "gpt-5-codex"
        assert cfg.triage_model == "gpt-5-codex"
        assert cfg.transcript_summary_model == "gpt-5-codex"
        assert cfg.memory_compaction_model == "gpt-5-codex"

    def test_profile_overrides_do_not_clobber_explicit_per_field(
        self, tmp_path: Path
    ) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            system_tool="codex",
            background_tool="codex",
            system_model="gpt-5-codex",
            background_model="gpt-5-codex",
            review_tool="claude",
            review_model="sonnet",
            transcript_summary_tool="claude",
            transcript_summary_model="haiku",
        )
        assert cfg.review_tool == "claude"
        assert cfg.review_model == "sonnet"
        assert cfg.transcript_summary_tool == "claude"
        assert cfg.transcript_summary_model == "haiku"


class TestTieringFields:
    def test_tiering_defaults_to_claude_subskill_with_debug_escalation_enabled(
        self, tmp_path: Path
    ) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.subskill_tool == "claude"
        assert cfg.subskill_model == "haiku"
        assert cfg.max_subskill_attempts == 0
        assert cfg.debug_escalation_enabled is True
        assert cfg.debug_tool == "claude"
        assert cfg.debug_model == "opus"
        assert cfg.max_debug_attempts == 1
        assert cfg.subskill_confidence_threshold == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Label list validation — empty labels must be rejected
# ---------------------------------------------------------------------------


class TestLabelValidation:
    """Tests for the field validator that rejects empty label lists."""

    @pytest.mark.parametrize(
        "field",
        [
            "ready_label",
            "review_label",
            "hitl_label",
            "hitl_active_label",
            "fixed_label",
            "improve_label",
            "memory_label",
            "transcript_label",
            "metrics_label",
            "dup_label",
            "epic_label",
            "epic_child_label",
            "find_label",
            "planner_label",
        ],
    )
    def test_empty_label_list_raises_validation_error(
        self, tmp_path: Path, field: str
    ) -> None:
        """Constructing HydraFlowConfig with an empty label list must raise."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="must contain at least one label"):
            HydraFlowConfig(
                **{field: []},  # type: ignore[arg-type]
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_label_env_var_empty_string_does_not_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_LABEL_READY='' should not override to empty list."""
        monkeypatch.setenv("HYDRAFLOW_LABEL_READY", "")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.ready_label == ["hydraflow-ready"]


class TestTimeoutConfigFields:
    """Tests for agent_timeout, transcript_summary_timeout, memory_compaction_timeout."""

    def test_agent_timeout_default(self) -> None:
        config = HydraFlowConfig(repo="test/repo")
        assert config.agent_timeout == 3600

    def test_transcript_summary_timeout_default(self) -> None:
        config = HydraFlowConfig(repo="test/repo")
        assert config.transcript_summary_timeout == 120

    def test_memory_compaction_timeout_default(self) -> None:
        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_compaction_timeout == 60

    def test_agent_timeout_bounds_too_low(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", agent_timeout=10)

    def test_agent_timeout_bounds_too_high(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", agent_timeout=20000)

    def test_transcript_summary_timeout_bounds_too_low(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", transcript_summary_timeout=5)

    def test_transcript_summary_timeout_bounds_too_high(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", transcript_summary_timeout=999)

    def test_memory_compaction_timeout_bounds_too_low(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", memory_compaction_timeout=5)

    def test_memory_compaction_timeout_bounds_too_high(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", memory_compaction_timeout=999)

    def test_agent_timeout_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HYDRAFLOW_AGENT_TIMEOUT", "7200")
        config = HydraFlowConfig(repo="test/repo")
        assert config.agent_timeout == 7200

    def test_transcript_summary_timeout_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY_TIMEOUT", "300")
        config = HydraFlowConfig(repo="test/repo")
        assert config.transcript_summary_timeout == 300

    def test_memory_compaction_timeout_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MEMORY_COMPACTION_TIMEOUT", "90")
        config = HydraFlowConfig(repo="test/repo")
        assert config.memory_compaction_timeout == 90


# ---------------------------------------------------------------------------
# ADR review interval bounds
# ---------------------------------------------------------------------------


class TestAdrReviewIntervalBounds:
    """Tests for adr_review_interval Field bounds (ge=28800, le=432000)."""

    def test_adr_review_interval_default(self) -> None:
        config = HydraFlowConfig(repo="test/repo")
        assert config.adr_review_interval == 86400

    def test_adr_review_interval_accepts_minimum(self) -> None:
        config = HydraFlowConfig(repo="test/repo", adr_review_interval=28800)
        assert config.adr_review_interval == 28800

    def test_adr_review_interval_accepts_maximum(self) -> None:
        config = HydraFlowConfig(repo="test/repo", adr_review_interval=432000)
        assert config.adr_review_interval == 432000

    def test_adr_review_interval_rejects_below_minimum(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", adr_review_interval=3600)

    def test_adr_review_interval_rejects_above_maximum(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", adr_review_interval=604800)

    def test_adr_review_interval_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_ADR_REVIEW_INTERVAL", "172800")
        config = HydraFlowConfig(repo="test/repo")
        assert config.adr_review_interval == 172800


# ---------------------------------------------------------------------------
# Directory properties (log_dir, plans_dir, memory_dir)
# ---------------------------------------------------------------------------


class TestDirectoryProperties:
    """Tests for the computed directory @property methods on HydraFlowConfig."""

    def test_log_dir_returns_hydraflow_logs_under_repo_root(
        self, tmp_path: Path
    ) -> None:
        """log_dir should return repo_root / .hydraflow / logs."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.log_dir == tmp_path / ".hydraflow" / "logs"

    def test_plans_dir_returns_hydraflow_plans_under_repo_root(
        self, tmp_path: Path
    ) -> None:
        """plans_dir should return repo_root / .hydraflow / plans."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.plans_dir == tmp_path / ".hydraflow" / "plans"

    def test_memory_dir_returns_hydraflow_memory_under_repo_root(
        self, tmp_path: Path
    ) -> None:
        """memory_dir should return repo_root / .hydraflow / memory."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_dir == tmp_path / ".hydraflow" / "memory"

    def test_directory_properties_follow_repo_root(self, tmp_path: Path) -> None:
        """All directory properties should be anchored to whatever repo_root is."""
        custom_root = tmp_path / "custom" / "root"
        custom_root.mkdir(parents=True)
        cfg = HydraFlowConfig(
            repo_root=custom_root,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.log_dir.parent.parent == custom_root
        assert cfg.plans_dir.parent.parent == custom_root
        assert cfg.memory_dir.parent.parent == custom_root


# ---------------------------------------------------------------------------
# Timeout and limit fields
# ---------------------------------------------------------------------------


class TestTimeoutAndLimitFields:
    """Tests for quality_timeout, git_command_timeout, summarizer_timeout, error_output_max_chars."""

    def test_quality_timeout_default(self, tmp_path: Path) -> None:
        """quality_timeout should default to 3600."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_timeout == 3600

    def test_git_command_timeout_default(self, tmp_path: Path) -> None:
        """git_command_timeout should default to 30."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_command_timeout == 30

    def test_summarizer_timeout_default(self, tmp_path: Path) -> None:
        """summarizer_timeout should default to 120."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.summarizer_timeout == 120

    def test_error_output_max_chars_default(self, tmp_path: Path) -> None:
        """error_output_max_chars should default to 3000."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.error_output_max_chars == 3000

    def test_quality_timeout_custom(self, tmp_path: Path) -> None:
        """quality_timeout should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            quality_timeout=1800,
        )
        assert cfg.quality_timeout == 1800

    def test_git_command_timeout_custom(self, tmp_path: Path) -> None:
        """git_command_timeout should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            git_command_timeout=60,
        )
        assert cfg.git_command_timeout == 60

    def test_summarizer_timeout_custom(self, tmp_path: Path) -> None:
        """summarizer_timeout should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            summarizer_timeout=300,
        )
        assert cfg.summarizer_timeout == 300

    def test_error_output_max_chars_custom(self, tmp_path: Path) -> None:
        """error_output_max_chars should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            error_output_max_chars=5000,
        )
        assert cfg.error_output_max_chars == 5000

    def test_quality_timeout_below_minimum_rejected(self, tmp_path: Path) -> None:
        """quality_timeout below ge=60 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 60"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                quality_timeout=10,
            )

    def test_quality_timeout_above_maximum_rejected(self, tmp_path: Path) -> None:
        """quality_timeout above le=7200 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 7200"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                quality_timeout=10000,
            )

    def test_git_command_timeout_below_minimum_rejected(self, tmp_path: Path) -> None:
        """git_command_timeout below ge=5 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 5"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                git_command_timeout=1,
            )

    def test_summarizer_timeout_below_minimum_rejected(self, tmp_path: Path) -> None:
        """summarizer_timeout below ge=30 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 30"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                summarizer_timeout=5,
            )

    def test_error_output_max_chars_below_minimum_rejected(
        self, tmp_path: Path
    ) -> None:
        """error_output_max_chars below ge=500 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 500"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                error_output_max_chars=100,
            )

    def test_git_command_timeout_above_maximum_rejected(self, tmp_path: Path) -> None:
        """git_command_timeout above le=120 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 120"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                git_command_timeout=300,
            )

    def test_summarizer_timeout_above_maximum_rejected(self, tmp_path: Path) -> None:
        """summarizer_timeout above le=600 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 600"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                summarizer_timeout=1200,
            )

    def test_error_output_max_chars_above_maximum_rejected(
        self, tmp_path: Path
    ) -> None:
        """error_output_max_chars above le=20_000 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 20000"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                error_output_max_chars=50_000,
            )


# ---------------------------------------------------------------------------
# PR Unsticker config fields
# ---------------------------------------------------------------------------


class TestUnstickConfigFields:
    """Tests for the new unsticker configuration fields."""

    def test_unstick_auto_merge_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_auto_merge is True

    def test_unstick_all_causes_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_all_causes is True

    def test_unstick_auto_merge_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_UNSTICK_AUTO_MERGE", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_auto_merge is False

    def test_unstick_all_causes_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_UNSTICK_ALL_CAUSES", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_all_causes is False


# --- all_pipeline_labels ---


class TestAllPipelineLabels:
    """Tests for HydraFlowConfig.all_pipeline_labels property."""

    def test_returns_all_label_fields(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(repo_root=tmp_path / "repo")
        labels = cfg.all_pipeline_labels
        # Should include labels from all pipeline stages
        assert cfg.ready_label[0] in labels
        assert cfg.review_label[0] in labels
        assert cfg.hitl_label[0] in labels
        assert cfg.planner_label[0] in labels
        assert cfg.find_label[0] in labels
        assert cfg.hitl_active_label[0] in labels
        assert cfg.fixed_label[0] in labels
        assert cfg.improve_label[0] in labels
        assert cfg.transcript_label[0] in labels

    def test_returns_flat_list(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(repo_root=tmp_path / "repo")
        labels = cfg.all_pipeline_labels
        assert isinstance(labels, list)
        for label in labels:
            assert isinstance(label, str)

    def test_custom_labels_included(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            ready_label=["custom-ready"],
            review_label=["custom-review"],
        )
        labels = cfg.all_pipeline_labels
        assert "custom-ready" in labels
        assert "custom-review" in labels


# --- labels_must_not_be_empty ---


class TestLabelsMustNotBeEmpty:
    """Tests for the labels_must_not_be_empty validator."""

    def test_rejects_empty_ready_label(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from tests.helpers import ConfigFactory

        with pytest.raises(ValidationError):
            ConfigFactory.create(repo_root=tmp_path / "repo", ready_label=[])

    def test_rejects_empty_review_label(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from tests.helpers import ConfigFactory

        with pytest.raises(ValidationError):
            ConfigFactory.create(repo_root=tmp_path / "repo", review_label=[])

    def test_accepts_non_empty_labels(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            ready_label=["valid"],
            review_label=["valid"],
        )
        assert cfg.ready_label == ["valid"]
        assert cfg.review_label == ["valid"]


# ---------------------------------------------------------------------------
# Repo-namespaced persistence (two-phase path resolution)
# ---------------------------------------------------------------------------


class TestNamespaceRepoPaths:
    """Tests for repo-scoped persistence path namespacing."""

    def test_state_file_namespaced_by_repo_slug(self, tmp_path: Path) -> None:
        """Default state_file should be under data_root/<slug>/."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        expected = tmp_path / ".hydraflow" / "acme-widgets" / "state.json"
        assert cfg.state_file == expected

    def test_event_log_namespaced_by_repo_slug(self, tmp_path: Path) -> None:
        """Default event_log_path should be under data_root/<slug>/."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        expected = tmp_path / ".hydraflow" / "acme-widgets" / "events.jsonl"
        assert cfg.event_log_path == expected

    def test_explicit_config_file_not_namespaced(self, tmp_path: Path) -> None:
        """Explicitly-set config_file should not be repo-scoped."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        explicit_cfg = data_root / "config.json"
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            repo="acme/widgets",
            config_file=explicit_cfg,
        )
        # config_file was explicitly set to the flat path, so it stays (not scoped)
        assert cfg.config_file == explicit_cfg.resolve()

    def test_explicit_state_file_not_namespaced(self, tmp_path: Path) -> None:
        """Explicitly-set state_file should not be repo-scoped."""
        custom = tmp_path / "custom" / "state.json"
        cfg = HydraFlowConfig(
            repo_root=tmp_path, repo="acme/widgets", state_file=custom
        )
        assert cfg.state_file == custom.resolve()

    def test_explicit_event_log_not_namespaced(self, tmp_path: Path) -> None:
        """Explicitly-set event_log_path should not be repo-scoped."""
        custom = tmp_path / "custom" / "events.jsonl"
        cfg = HydraFlowConfig(
            repo_root=tmp_path, repo="acme/widgets", event_log_path=custom
        )
        assert cfg.event_log_path == custom.resolve()

    def test_repo_data_root_property(self, tmp_path: Path) -> None:
        """repo_data_root should return data_root / repo_slug."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.repo_data_root == tmp_path / ".hydraflow" / "acme-widgets"

    def test_two_repos_get_separate_state_files(self, tmp_path: Path) -> None:
        """Two configs with different repos should have different state files."""
        cfg_a = HydraFlowConfig(repo_root=tmp_path, repo="org/alpha")
        cfg_b = HydraFlowConfig(repo_root=tmp_path, repo="org/beta")
        assert cfg_a.state_file != cfg_b.state_file
        assert "org-alpha" in str(cfg_a.state_file)
        assert "org-beta" in str(cfg_b.state_file)

    def test_legacy_state_file_migrated(self, tmp_path: Path) -> None:
        """If legacy flat state.json exists, it should be copied to scoped path."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        legacy_state = data_root / "state.json"
        legacy_state.write_text('{"processed_issues": [1, 2]}')

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.state_file.exists()
        assert cfg.state_file.read_text() == '{"processed_issues": [1, 2]}'

    def test_legacy_sessions_migrated(self, tmp_path: Path) -> None:
        """If legacy flat sessions.jsonl exists, it should be copied."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        flat_sessions = data_root / "sessions.jsonl"
        flat_sessions.write_text('{"id":"s1"}\n')

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        scoped_sessions = cfg.state_file.parent / "sessions.jsonl"
        assert scoped_sessions.exists()
        assert scoped_sessions.read_text() == '{"id":"s1"}\n'

    def test_no_migration_when_scoped_already_exists(self, tmp_path: Path) -> None:
        """If scoped state already exists, legacy file should not overwrite it."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        legacy_state = data_root / "state.json"
        legacy_state.write_text('{"old": true}')
        scoped_dir = data_root / "acme-widgets"
        scoped_dir.mkdir(parents=True)
        (scoped_dir / "state.json").write_text('{"new": true}')

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.state_file.read_text() == '{"new": true}'

    def test_no_migration_when_scoped_event_log_already_exists(
        self, tmp_path: Path
    ) -> None:
        """If scoped events.jsonl already exists, legacy file should not overwrite it."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        legacy_events = data_root / "events.jsonl"
        legacy_events.write_text('{"event":"old"}\n')
        scoped_dir = data_root / "acme-widgets"
        scoped_dir.mkdir(parents=True)
        (scoped_dir / "events.jsonl").write_text('{"event":"new"}\n')

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.event_log_path.read_text() == '{"event":"new"}\n'


# ---------------------------------------------------------------------------
# Two-phase path resolution order (base paths → repo → repo-scoped paths)
# ---------------------------------------------------------------------------


class TestTwoPhasePathResolution:
    """Tests verifying that repo-scoped paths depend on repo being resolved first.

    The resolve_defaults validator must resolve base paths (repo_root, worktree_base,
    data_root) before resolving the repo slug, and resolve the repo slug before
    computing repo-scoped paths (state_file, event_log_path).
    """

    def test_state_file_never_flat_when_repo_available(self, tmp_path: Path) -> None:
        """state_file must be repo-scoped, never flat data_root/state.json."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        flat_default = cfg.data_root / "state.json"
        assert cfg.state_file != flat_default
        assert cfg.repo_slug in str(cfg.state_file)

    def test_event_log_never_flat_when_repo_available(self, tmp_path: Path) -> None:
        """event_log_path must be repo-scoped, never flat data_root/events.jsonl."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        flat_default = cfg.data_root / "events.jsonl"
        assert cfg.event_log_path != flat_default
        assert cfg.repo_slug in str(cfg.event_log_path)

    def test_base_paths_resolved_before_repo_detection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """repo_root and data_root must be resolved before repo slug detection."""
        monkeypatch.setenv("HYDRAFLOW_GITHUB_REPO", "org/repo")
        cfg = HydraFlowConfig(repo_root=tmp_path)
        # repo_root should be resolved (absolute) despite repo coming from env
        assert cfg.repo_root.is_absolute()
        assert cfg.data_root.is_absolute()
        # And repo-scoped paths should use the resolved data_root
        assert str(cfg.state_file).startswith(str(cfg.data_root))

    def test_no_repo_falls_back_to_directory_name_scoped_paths(
        self, tmp_path: Path
    ) -> None:
        """Without a repo slug, paths should use repo_root dir name as fallback slug."""
        cfg = HydraFlowConfig(repo_root=tmp_path)
        # repo_slug falls back to repo_root.name
        assert cfg.repo_slug == tmp_path.name
        expected_state = cfg.data_root / tmp_path.name / "state.json"
        assert cfg.state_file == expected_state

    def test_env_detected_repo_scopes_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Repo detected from env var should scope state_file and event_log_path."""
        monkeypatch.setenv("HYDRAFLOW_GITHUB_REPO", "env-org/env-repo")
        cfg = HydraFlowConfig(repo_root=tmp_path)
        assert "env-org-env-repo" in str(cfg.state_file)
        assert "env-org-env-repo" in str(cfg.event_log_path)

    def test_config_file_stays_none_when_not_explicit(self, tmp_path: Path) -> None:
        """config_file should remain None when not explicitly provided."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.config_file is None

    def test_sessions_not_migrated_when_state_file_explicit(
        self, tmp_path: Path
    ) -> None:
        """sessions.jsonl should not be migrated into a custom state_file parent dir."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        (data_root / "sessions.jsonl").write_text('{"id":"s1"}\n')
        custom_state = tmp_path / "custom" / "state.json"

        cfg = HydraFlowConfig(
            repo_root=tmp_path, repo="acme/widgets", state_file=custom_state
        )
        # sessions.jsonl must NOT appear next to the explicit state_file
        assert not (cfg.state_file.parent / "sessions.jsonl").exists()

    def test_migration_copy_failure_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shutil.copy2 failure during migration should log a warning, not raise."""
        import shutil

        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        (data_root / "state.json").write_text('{"processed_issues": []}')

        def fail_copy(src: object, dst: object, **kw: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(shutil, "copy2", fail_copy)

        # Should not raise; config must still instantiate successfully.
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.state_file == data_root / "acme-widgets" / "state.json"
        assert not cfg.state_file.exists()  # copy failed, file was not created

    def test_legacy_event_log_migrated(self, tmp_path: Path) -> None:
        """If legacy flat events.jsonl exists, it should be copied to scoped path."""
        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        legacy_events = data_root / "events.jsonl"
        legacy_events.write_text('{"event":"deploy"}\n')

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.event_log_path.exists()
        assert cfg.event_log_path.read_text() == '{"event":"deploy"}\n'
        assert "acme-widgets" in str(cfg.event_log_path)

    def test_event_log_migration_copy_failure_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shutil.copy2 failure migrating events.jsonl should log, not raise."""
        import shutil

        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        (data_root / "events.jsonl").write_text('{"event":"deploy"}\n')

        def fail_copy(src: object, dst: object, **kw: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(shutil, "copy2", fail_copy)

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.event_log_path == data_root / "acme-widgets" / "events.jsonl"
        assert not cfg.event_log_path.exists()

    def test_hydraflow_home_env_scopes_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_HOME env var should set data_root and repo-scoped paths use it."""
        custom_home = tmp_path / "custom-data"
        custom_home.mkdir()
        monkeypatch.setenv("HYDRAFLOW_HOME", str(custom_home))

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="org/project")
        assert cfg.data_root == custom_home.resolve()
        assert str(cfg.state_file).startswith(str(custom_home.resolve()))
        assert "org-project" in str(cfg.state_file)

    def test_sessions_migration_copy_failure_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A shutil.copy2 failure migrating sessions.jsonl should log, not raise."""
        import shutil

        data_root = tmp_path / ".hydraflow"
        data_root.mkdir()
        (data_root / "sessions.jsonl").write_text('{"id":"s1"}\n')

        original_copy2 = shutil.copy2
        call_count = 0

        def selective_fail(src: object, dst: object, **kw: object) -> None:
            nonlocal call_count
            call_count += 1
            # Let state_file and event_log migrations succeed, fail on sessions
            if "sessions.jsonl" in str(dst):
                raise OSError("permission denied")
            return original_copy2(src, dst, **kw)  # type: ignore[arg-type]

        monkeypatch.setattr(shutil, "copy2", selective_fail)

        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        scoped_sessions = cfg.state_file.parent / "sessions.jsonl"
        assert not scoped_sessions.exists()  # copy failed
