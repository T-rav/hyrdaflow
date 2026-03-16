"""Tests for dx/hydraflow/config.py — Validation constraints, labels, field bounds."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import HydraFlowConfig

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
        assert cfg.max_pre_quality_review_attempts == 3

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
# HydraFlowConfig – dup_label
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
        monkeypatch.setenv("HYDRAFLOW_MAX_PRE_QUALITY_REVIEW_ATTEMPTS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_pre_quality_review_attempts == 4

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
# HydraFlowConfig – max_merge_conflict_fix_attempts env var override
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

    def test_verify_label_default(self, tmp_path: Path) -> None:
        """verify_label should default to ['hydraflow-verify']."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.verify_label == ["hydraflow-verify"]

    def test_verify_label_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_LABEL_VERIFY should override verify_label."""
        monkeypatch.setenv("HYDRAFLOW_LABEL_VERIFY", "custom-verify")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.verify_label == ["custom-verify"]

    def test_verify_label_in_all_pipeline_labels(self, tmp_path: Path) -> None:
        """verify_label should appear in all_pipeline_labels."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert "hydraflow-verify" in cfg.all_pipeline_labels


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
# ConfigFactory — dead parameter cleanup (issue #2792)
# ---------------------------------------------------------------------------


class TestConfigFactoryDeadParameterCleanup:
    """Verify the removed adr_auto_triage field is not exposed by ConfigFactory."""

    def test_adr_auto_triage_not_in_config_factory_signature(self) -> None:
        """adr_auto_triage was removed from HydraFlowConfig; the factory must not accept it."""
        from tests.helpers import ConfigFactory

        sig = inspect.signature(ConfigFactory.create)
        assert "adr_auto_triage" not in sig.parameters

    def test_config_factory_creates_valid_config_after_cleanup(self) -> None:
        """ConfigFactory.create() still produces a valid HydraFlowConfig without adr_auto_triage."""
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create()
        assert isinstance(cfg, HydraFlowConfig)
        assert not hasattr(cfg, "adr_auto_triage"), (
            "adr_auto_triage must not exist on HydraFlowConfig"
        )
