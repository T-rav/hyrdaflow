"""Tests for dx/hydraflow/config.py — Core config: defaults, custom values, path resolution, repo detection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import (
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
            workspace_base=explicit_root / "wt",
            state_file=explicit_root / "state.json",
        )

        # Assert
        assert cfg.repo_root == explicit_root

    def test_explicit_workspace_base_is_preserved(self, tmp_path: Path) -> None:
        # Arrange
        explicit_root = tmp_path / "repo"
        explicit_wt = tmp_path / "worktrees"

        # Act
        cfg = HydraFlowConfig(
            repo_root=explicit_root,
            workspace_base=explicit_wt,
            state_file=explicit_root / "state.json",
        )

        # Assert
        assert cfg.workspace_base == explicit_wt

    def test_explicit_state_file_is_preserved(self, tmp_path: Path) -> None:
        # Arrange
        explicit_root = tmp_path / "repo"
        explicit_state = tmp_path / "custom-state.json"

        # Act
        cfg = HydraFlowConfig(
            repo_root=explicit_root,
            workspace_base=explicit_root / "wt",
            state_file=explicit_state,
        )

        # Assert
        assert cfg.state_file == explicit_state

    def test_default_workspace_base_derived_from_repo_root(
        self, tmp_path: Path
    ) -> None:
        """When workspace_base is left as Path('.'), it should default to ~/.hydraflow/worktrees."""
        # Arrange
        git_root = tmp_path / "hydra"
        git_root.mkdir()
        (git_root / ".git").mkdir()

        # Act – pass repo_root explicitly but leave workspace_base and state_file at their defaults (Path("."))
        cfg = HydraFlowConfig(repo_root=git_root)

        # Assert
        assert (
            cfg.workspace_base == Path("~/.hydraflow/worktrees").expanduser().resolve()
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

    def test_auto_detected_workspace_base_uses_hydraflow_worktrees_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auto-derived workspace_base should be ~/.hydraflow/worktrees."""
        # Arrange
        git_root = tmp_path / "repo"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        monkeypatch.chdir(git_root)

        # Act
        cfg = HydraFlowConfig()

        # Assert
        assert (
            cfg.workspace_base == Path("~/.hydraflow/worktrees").expanduser().resolve()
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
# HydraFlowConfig – branch_for_issue / workspace_path_for_issue helpers
# ---------------------------------------------------------------------------


class TestBranchForIssue:
    """Tests for HydraFlowConfig.branch_for_issue()."""

    def test_returns_canonical_branch_name(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.branch_for_issue(42) == "agent/issue-42"

    def test_single_digit_issue(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.branch_for_issue(1) == "agent/issue-1"

    def test_large_issue_number(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.branch_for_issue(99999) == "agent/issue-99999"


class TestWorktreePathForIssue:
    """Tests for HydraFlowConfig.workspace_path_for_issue()."""

    def test_returns_path_under_workspace_base(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="org/my-repo",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert (
            cfg.workspace_path_for_issue(42)
            == tmp_path / "wt" / "org-my-repo" / "issue-42"
        )

    def test_single_digit_issue(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="org/my-repo",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert (
            cfg.workspace_path_for_issue(1)
            == tmp_path / "wt" / "org-my-repo" / "issue-1"
        )

    def test_uses_configured_workspace_base(self, tmp_path: Path) -> None:
        custom_base = tmp_path / "custom-worktrees"
        cfg = HydraFlowConfig(
            repo="org/proj",
            repo_root=tmp_path,
            workspace_base=custom_base,
            state_file=tmp_path / "s.json",
        )
        assert cfg.workspace_path_for_issue(7) == custom_base / "org-proj" / "issue-7"

    def test_repo_slug_from_repo(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo="acme/widgets",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo_slug == "acme-widgets"

    def test_repo_slug_fallback_to_dir_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_GITHUB_REPO", raising=False)
        monkeypatch.setattr("config._detect_repo_slug", lambda _repo_root: "")
        cfg = HydraFlowConfig(
            repo="",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo_slug == tmp_path.name


# ---------------------------------------------------------------------------
# resolve_defaults model validator
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.repo == "explicit-org/explicit-repo"

    def test_resolve_defaults_data_poll_interval_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DATA_POLL_INTERVAL", "120")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.data_poll_interval == 120


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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.log_dir == tmp_path / ".hydraflow" / "logs"

    def test_plans_dir_returns_hydraflow_plans_under_repo_root(
        self, tmp_path: Path
    ) -> None:
        """plans_dir should return repo_root / .hydraflow / plans."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.plans_dir == tmp_path / ".hydraflow" / "plans"

    def test_memory_dir_returns_hydraflow_memory_under_repo_root(
        self, tmp_path: Path
    ) -> None:
        """memory_dir should return repo_root / .hydraflow / memory."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_dir == tmp_path / ".hydraflow" / "memory"

    def test_directory_properties_follow_repo_root(self, tmp_path: Path) -> None:
        """All directory properties should be anchored to whatever repo_root is."""
        custom_root = tmp_path / "custom" / "root"
        custom_root.mkdir(parents=True)
        cfg = HydraFlowConfig(
            repo_root=custom_root,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.log_dir.parent.parent == custom_root
        assert cfg.plans_dir.parent.parent == custom_root
        assert cfg.memory_dir.parent.parent == custom_root


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
# Two-phase path resolution order (base paths -> repo -> repo-scoped paths)
# ---------------------------------------------------------------------------


class TestTwoPhasePathResolution:
    """Tests verifying that repo-scoped paths depend on repo being resolved first.

    The resolve_defaults validator must resolve base paths (repo_root, workspace_base,
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a repo slug, paths should use repo_root dir name as fallback slug."""
        monkeypatch.delenv("HYDRAFLOW_GITHUB_REPO", raising=False)
        monkeypatch.setattr("config._detect_repo_slug", lambda _repo_root: "")
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


# ---------------------------------------------------------------------------
# ADR-0021 invariants: persistence layout matches documented architecture
# ---------------------------------------------------------------------------


class TestADR0021PersistenceLayout:
    """Tests that config path properties match the layout documented in ADR-0021.

    ADR-0021 documents:
    - state_file, event_log_path are repo-scoped under data_root/<slug>/
    - log_dir, plans_dir, memory_dir are flat under data_root/ (ADR-0010 target)
    - repo_data_root = data_root / repo_slug
    - resolve_defaults runs 7 resolution steps in order
    """

    def test_log_dir_is_flat_not_repo_scoped(self, tmp_path: Path) -> None:
        """log_dir must be data_root/'logs' (flat), not under repo_slug/."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.log_dir == cfg.data_root / "logs"
        assert cfg.repo_slug not in cfg.log_dir.parts

    def test_plans_dir_is_flat_not_repo_scoped(self, tmp_path: Path) -> None:
        """plans_dir must be data_root/'plans' (flat), not under repo_slug/."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.plans_dir == cfg.data_root / "plans"
        assert cfg.repo_slug not in cfg.plans_dir.parts

    def test_memory_dir_is_flat_not_repo_scoped(self, tmp_path: Path) -> None:
        """memory_dir must be data_root/'memory' (flat), not under repo_slug/."""
        cfg = HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")
        assert cfg.memory_dir == cfg.data_root / "memory"
        assert cfg.repo_slug not in cfg.memory_dir.parts

    def test_resolve_defaults_calls_all_seven_steps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve_defaults must call all 7 resolution steps in order."""
        import config as config_module

        call_order: list[str] = []

        step_names = [
            "_resolve_base_paths",
            "_resolve_repo_and_identity",
            "_resolve_repo_scoped_paths",
            "_apply_env_overrides",
            "_apply_profile_overrides",
            "_harmonize_tool_model_defaults",
            "_validate_docker",
        ]

        originals = {name: getattr(config_module, name) for name in step_names}

        for name in step_names:
            original = originals[name]

            def make_wrapper(fn_name: str, fn: object) -> object:
                def wrapper(cfg: object) -> object:
                    call_order.append(fn_name)
                    return fn(cfg)  # type: ignore[operator]

                return wrapper

            monkeypatch.setattr(config_module, name, make_wrapper(name, original))

        HydraFlowConfig(repo_root=tmp_path, repo="acme/widgets")

        assert call_order == step_names
