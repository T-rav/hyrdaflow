"""Tests for dx/hydraflow/config.py — Validation constraints, labels, field bounds."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import HydraFlowConfig, build_credentials

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# (field_name, min_val, max_val, default_val)
_BOUNDED_INT_FIELDS = [
    ("batch_size", 1, 50, 15),
    ("max_workers", 1, 10, 1),
    ("max_triagers", 1, 10, 1),
    ("max_planners", 1, 10, 1),
    ("max_reviewers", 1, 10, 1),
    ("max_hitl_workers", 1, 5, 1),
    ("dashboard_port", 1024, 65535, 5555),
    ("ci_check_timeout", 30, 3600, 600),
    ("ci_poll_interval", 5, 120, 30),
    ("max_ci_fix_attempts", 0, 5, 2),
    ("max_review_fix_attempts", 0, 5, 2),
    ("max_pre_quality_review_attempts", 0, 5, 3),
    ("min_review_findings", 0, 20, 3),
    ("min_plan_words", 50, 2000, 200),
    ("max_merge_conflict_fix_attempts", 0, 5, 3),
    ("max_new_files_warning", 1, 20, 5),
    ("rc_cadence_hours", 1, 168, 4),
    ("staging_promotion_interval", 30, 3600, 300),
    ("staging_rc_retention_days", 1, 90, 7),
]

_BOUNDED_INT_IDS = [f[0] for f in _BOUNDED_INT_FIELDS]


def _make_cfg(tmp_path: Path, **overrides: object) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        **overrides,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# HydraFlowConfig – validation constraints (parametrized)
# ---------------------------------------------------------------------------


class TestBoundedIntFields:
    """Parametrized tests for Pydantic field constraints (ge/le) across all bounded int fields."""

    @pytest.mark.parametrize(
        "field,min_val,max_val,default", _BOUNDED_INT_FIELDS, ids=_BOUNDED_INT_IDS
    )
    def test_default_value(
        self,
        tmp_path: Path,
        field: str,
        min_val: int,
        max_val: int,
        default: int,
    ) -> None:
        cfg = _make_cfg(tmp_path)
        assert getattr(cfg, field) == default

    @pytest.mark.parametrize(
        "field,min_val,max_val,default", _BOUNDED_INT_FIELDS, ids=_BOUNDED_INT_IDS
    )
    def test_minimum_boundary_accepted(
        self,
        tmp_path: Path,
        field: str,
        min_val: int,
        max_val: int,
        default: int,
    ) -> None:
        cfg = _make_cfg(tmp_path, **{field: min_val})
        assert getattr(cfg, field) == min_val

    @pytest.mark.parametrize(
        "field,min_val,max_val,default", _BOUNDED_INT_FIELDS, ids=_BOUNDED_INT_IDS
    )
    def test_maximum_boundary_accepted(
        self,
        tmp_path: Path,
        field: str,
        min_val: int,
        max_val: int,
        default: int,
    ) -> None:
        cfg = _make_cfg(tmp_path, **{field: max_val})
        assert getattr(cfg, field) == max_val

    @pytest.mark.parametrize(
        "field,min_val,max_val,default", _BOUNDED_INT_FIELDS, ids=_BOUNDED_INT_IDS
    )
    def test_below_minimum_raises(
        self,
        tmp_path: Path,
        field: str,
        min_val: int,
        max_val: int,
        default: int,
    ) -> None:
        with pytest.raises(ValueError):
            _make_cfg(tmp_path, **{field: min_val - 1})

    @pytest.mark.parametrize(
        "field,min_val,max_val,default", _BOUNDED_INT_FIELDS, ids=_BOUNDED_INT_IDS
    )
    def test_above_maximum_raises(
        self,
        tmp_path: Path,
        field: str,
        min_val: int,
        max_val: int,
        default: int,
    ) -> None:
        with pytest.raises(ValueError):
            _make_cfg(tmp_path, **{field: max_val + 1})


# ---------------------------------------------------------------------------
# HydraFlowConfig – validation constraints (non-parametrized edge cases)
# ---------------------------------------------------------------------------


class TestHydraFlowConfigValidationConstraints:
    """Edge-case tests that don't fit the uniform min/max/default pattern."""

    # batch_size: ge=1, le=50 — representative boundary check kept for clarity

    def test_batch_size_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = _make_cfg(tmp_path, batch_size=1)
        assert cfg.batch_size == 1

    def test_batch_size_above_maximum_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            _make_cfg(tmp_path, batch_size=51)


# ---------------------------------------------------------------------------
# HydraFlowConfig – gh_token resolution
# ---------------------------------------------------------------------------


class TestBuildCredentialsGhToken:
    def test_gh_token_default_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert build_credentials(cfg).gh_token == ""

    def test_gh_token_picks_up_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_GH_TOKEN", "ghp_from_env")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert build_credentials(cfg).gh_token == "ghp_from_env"

    def test_gh_token_picks_up_dotenv_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        (tmp_path / ".env").write_text("HYDRAFLOW_GH_TOKEN=ghp_from_dotenv\n")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert build_credentials(cfg).gh_token == "ghp_from_dotenv"

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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert build_credentials(cfg).gh_token == "ghp_from_dotenv"


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
    def test_git_user_name_default_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == ""

    def test_git_user_email_default_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_git_identity_env(monkeypatch)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_email == ""

    def test_git_user_name_explicit_value_preserved(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            git_user_name="Bot",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "Bot"

    def test_git_user_email_explicit_value_preserved(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            git_user_email="bot@example.com",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_user_name == "Dotenv Bot"
        assert cfg.git_user_email == "dotenv-bot@example.com"


# ---------------------------------------------------------------------------
# HydraFlowConfig – hitl_active_label env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigHitlActiveLabel:
    def test_hitl_active_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_HITL_ACTIVE", "env-active")
        cfg = HydraFlowConfig(
            hitl_active_label=["explicit-active"],
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_active_label == ["explicit-active"]


# ---------------------------------------------------------------------------
# HydraFlowConfig – dup_label
# ---------------------------------------------------------------------------


class TestHydraFlowConfigDupLabel:
    def test_dup_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["hydraflow-dup"]

    def test_dup_label_custom_value(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            dup_label=["my-dup"],
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["my-dup"]

    def test_dup_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_DUP", "env-dup")
        cfg = HydraFlowConfig(
            dup_label=["explicit-dup"],
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.dup_label == ["explicit-dup"]


class TestHydraFlowConfigEpicChildLabel:
    def test_epic_child_label_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["hydraflow-epic-child"]

    def test_epic_child_label_custom_value(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            epic_child_label=["my-epic-child"],
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["my-epic-child"]

    def test_epic_child_label_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LABEL_EPIC_CHILD", "env-epic-child")
        cfg = HydraFlowConfig(
            epic_child_label=["explicit-epic-child"],
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.epic_child_label == ["explicit-epic-child"]


# ---------------------------------------------------------------------------
# HydraFlowConfig – min_plan_words env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMinPlanWords:
    def test_min_plan_words_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 200

    def test_min_plan_words_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_PLAN_WORDS", "300")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_plan_words == 100


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_review_fix_attempts env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxReviewFixAttempts:
    def test_max_review_fix_attempts_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_FIX_ATTEMPTS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_fix_attempts == 1


class TestHydraFlowConfigMaxPreQualityReviewAttempts:
    def test_max_pre_quality_review_attempts_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_PRE_QUALITY_REVIEW_ATTEMPTS", "4")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_pre_quality_review_attempts == 2


# ---------------------------------------------------------------------------
# HydraFlowConfig – min_review_findings env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMinReviewFindings:
    def test_min_review_findings_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.min_review_findings == 1


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_merge_conflict_fix_attempts env var override
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxMergeConflictFixAttempts:
    def test_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 1

    def test_env_var_invalid_value_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_MERGE_CONFLICT_FIX_ATTEMPTS", "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_merge_conflict_fix_attempts == 3


class TestHydraFlowConfigLitePlanLabels:
    def test_lite_plan_labels_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.lite_plan_labels == ["bug", "typo", "docs"]

    def test_lite_plan_labels_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_LITE_PLAN_LABELS", "hotfix,patch")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.lite_plan_labels == ["custom"]

    def test_pr_unstick_interval_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_interval == 3600

    def test_pr_unstick_batch_size_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_batch_size == 10

    def test_pr_unstick_interval_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_PR_UNSTICK_INTERVAL", "1800")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_interval == 1800

    def test_pr_unstick_batch_size_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_PR_UNSTICK_BATCH_SIZE", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.pr_unstick_batch_size == 5


# ---------------------------------------------------------------------------
# HydraFlowConfig – threshold configuration
# ---------------------------------------------------------------------------


class TestHydraFlowConfigThresholds:
    def test_quality_fix_rate_threshold_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(0.5)

    def test_approval_rate_threshold_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.approval_rate_threshold == pytest.approx(0.5)

    def test_hitl_rate_threshold_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_rate_threshold == pytest.approx(0.2)

    def test_custom_quality_fix_rate_threshold(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            quality_fix_rate_threshold=0.8,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(0.8)

    def test_custom_approval_rate_threshold(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            approval_rate_threshold=0.7,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.approval_rate_threshold == pytest.approx(0.7)

    def test_custom_hitl_rate_threshold(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            hitl_rate_threshold=0.1,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.hitl_rate_threshold == pytest.approx(0.1)

    def test_threshold_below_zero_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                quality_fix_rate_threshold=-0.1,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_threshold_above_one_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            HydraFlowConfig(
                quality_fix_rate_threshold=1.1,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_threshold_boundary_zero(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            quality_fix_rate_threshold=0.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(0.0)

    def test_threshold_boundary_one(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            quality_fix_rate_threshold=1.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_fix_rate_threshold == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# HydraFlowConfig – test_command field
# ---------------------------------------------------------------------------


class TestHydraFlowConfigTestCommand:
    def test_test_command_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "make test"

    def test_test_command_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            test_command="npm test",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "npm test"

    def test_test_command_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TEST_COMMAND", "pytest -x")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.test_command == "cargo test"


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_issue_body_chars field
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxIssueBodyChars:
    def test_max_issue_body_chars_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_body_chars == 10_000

    def test_max_issue_body_chars_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_issue_body_chars=5_000,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_body_chars == 5_000


# ---------------------------------------------------------------------------
# HydraFlowConfig – max_review_diff_chars field
# ---------------------------------------------------------------------------


class TestHydraFlowConfigMaxReviewDiffChars:
    def test_max_review_diff_chars_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_diff_chars == 15_000

    def test_max_review_diff_chars_custom(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            max_review_diff_chars=30_000,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_review_diff_chars == 25_000


# ---------------------------------------------------------------------------
# max_issue_attempts
# ---------------------------------------------------------------------------


class TestMaxIssueAttempts:
    def test_default_is_three(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_attempts == 3

    def test_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_ISSUE_ATTEMPTS", "5")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_issue_attempts == 4


class TestUpdatedIntervalDefaults:
    """Verify updated default intervals for memory_sync and metrics."""

    def test_memory_sync_default_is_3600(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_sync_interval == 3600

    def test_memory_sync_max_increased_to_14400(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            memory_sync_interval=14400,
        )
        assert cfg.memory_sync_interval == 14400

    def test_memory_sync_env_override_with_new_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MEMORY_SYNC_INTERVAL", "900")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.memory_sync_interval == 900


# ---------------------------------------------------------------------------
# Transcript summarization config
# ---------------------------------------------------------------------------


class TestTranscriptSummarizationConfig:
    def test_default_enabled(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summarization_enabled is True

    def test_default_model(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summary_model == "haiku"

    def test_default_max_chars(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.max_transcript_summary_chars == 50_000

    def test_env_var_enabled_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summarization_enabled is False

    def test_env_var_enabled_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARIZATION_ENABLED", "0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.transcript_summarization_enabled is False

    def test_env_var_max_chars_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_MAX_TRANSCRIPT_SUMMARY_CHARS", "20000")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_max_chars_validation_max(self, tmp_path: Path) -> None:
        """max_transcript_summary_chars must be <= 500_000."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                max_transcript_summary_chars=1_000_000,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_explicit_value_overrides_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL", "sonnet")
        cfg = HydraFlowConfig(
            transcript_summary_model="opus",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        # Explicit "opus" != default "haiku", so env var should NOT override
        assert cfg.transcript_summary_model == "opus"


# ---------------------------------------------------------------------------
# Label list validation — empty labels must be rejected
# ---------------------------------------------------------------------------


class TestLabelValidation:
    @pytest.mark.parametrize(
        "field",
        [
            "ready_label",
            "review_label",
            "hitl_label",
            "hitl_active_label",
            "fixed_label",
            "dup_label",
            "epic_label",
            "epic_child_label",
            "find_label",
            "planner_label",
            "parked_label",
            "diagnose_label",
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
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_label_env_var_empty_string_does_not_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_LABEL_READY='' should not override to empty list."""
        monkeypatch.setenv("HYDRAFLOW_LABEL_READY", "")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.ready_label == ["hydraflow-ready"]

    def test_verify_label_default(self, tmp_path: Path) -> None:
        """verify_label should default to ['hydraflow-verify']."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.verify_label == ["hydraflow-verify"]

    def test_verify_label_in_all_pipeline_labels(self, tmp_path: Path) -> None:
        """verify_label should appear in all_pipeline_labels."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert "hydraflow-verify" in cfg.all_pipeline_labels


class TestTimeoutConfigFields:
    def test_agent_timeout_default(self) -> None:
        config = HydraFlowConfig(repo="test/repo")
        assert config.agent_timeout == 3600

    def test_transcript_summary_timeout_default(self) -> None:
        config = HydraFlowConfig(repo="test/repo")
        assert config.transcript_summary_timeout == 120

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


# ---------------------------------------------------------------------------
# ADR review interval bounds
# ---------------------------------------------------------------------------


class TestAdrReviewIntervalBounds:
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
    def test_quality_timeout_default(self, tmp_path: Path) -> None:
        """quality_timeout should default to 3600."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.quality_timeout == 3600

    def test_git_command_timeout_default(self, tmp_path: Path) -> None:
        """git_command_timeout should default to 30."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.git_command_timeout == 30

    def test_summarizer_timeout_default(self, tmp_path: Path) -> None:
        """summarizer_timeout should default to 120."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.summarizer_timeout == 120

    def test_error_output_max_chars_default(self, tmp_path: Path) -> None:
        """error_output_max_chars should default to 3000."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.error_output_max_chars == 3000

    def test_quality_timeout_custom(self, tmp_path: Path) -> None:
        """quality_timeout should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            quality_timeout=1800,
        )
        assert cfg.quality_timeout == 1800

    def test_git_command_timeout_custom(self, tmp_path: Path) -> None:
        """git_command_timeout should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            git_command_timeout=60,
        )
        assert cfg.git_command_timeout == 60

    def test_summarizer_timeout_custom(self, tmp_path: Path) -> None:
        """summarizer_timeout should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            summarizer_timeout=300,
        )
        assert cfg.summarizer_timeout == 300

    def test_error_output_max_chars_custom(self, tmp_path: Path) -> None:
        """error_output_max_chars should accept a custom value within range."""
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            error_output_max_chars=5000,
        )
        assert cfg.error_output_max_chars == 5000

    def test_quality_timeout_below_minimum_rejected(self, tmp_path: Path) -> None:
        """quality_timeout below ge=60 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 60"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                quality_timeout=10,
            )

    def test_quality_timeout_above_maximum_rejected(self, tmp_path: Path) -> None:
        """quality_timeout above le=7200 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 7200"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                quality_timeout=10000,
            )

    def test_git_command_timeout_below_minimum_rejected(self, tmp_path: Path) -> None:
        """git_command_timeout below ge=5 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 5"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                git_command_timeout=1,
            )

    def test_summarizer_timeout_below_minimum_rejected(self, tmp_path: Path) -> None:
        """summarizer_timeout below ge=30 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="greater than or equal to 30"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
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
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                error_output_max_chars=100,
            )

    def test_git_command_timeout_above_maximum_rejected(self, tmp_path: Path) -> None:
        """git_command_timeout above le=120 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 120"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                git_command_timeout=300,
            )

    def test_summarizer_timeout_above_maximum_rejected(self, tmp_path: Path) -> None:
        """summarizer_timeout above le=600 should be rejected by Pydantic."""
        with pytest.raises(ValueError, match="less than or equal to 600"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
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
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                error_output_max_chars=50_000,
            )


# ---------------------------------------------------------------------------
# PR Unsticker config fields
# ---------------------------------------------------------------------------


class TestUnstickConfigFields:
    def test_unstick_auto_merge_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_auto_merge is True

    def test_unstick_all_causes_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_all_causes is True

    def test_unstick_auto_merge_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_UNSTICK_AUTO_MERGE", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_auto_merge is False

    def test_unstick_all_causes_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_UNSTICK_ALL_CAUSES", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.unstick_all_causes is False


# --- all_pipeline_labels ---


class TestAllPipelineLabels:
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

    def test_rejects_empty_parked_label(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from tests.helpers import ConfigFactory

        with pytest.raises(ValidationError):
            ConfigFactory.create(repo_root=tmp_path / "repo", parked_label=[])

    def test_rejects_empty_diagnose_label(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        from tests.helpers import ConfigFactory

        with pytest.raises(ValidationError):
            ConfigFactory.create(repo_root=tmp_path / "repo", diagnose_label=[])

    def test_accepts_non_empty_labels(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            ready_label=["valid"],
            review_label=["valid"],
        )
        assert cfg.ready_label == ["valid"]
        assert cfg.review_label == ["valid"]

    def test_accepts_custom_parked_label(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo", parked_label=["custom-parked"]
        )
        assert cfg.parked_label == ["custom-parked"]

    def test_accepts_custom_diagnose_label(self, tmp_path: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo", diagnose_label=["custom-diagnose"]
        )
        assert cfg.diagnose_label == ["custom-diagnose"]


class TestAgentToolFields:
    def test_tool_defaults(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.implementation_tool == "claude"
        assert cfg.review_tool == "claude"
        assert cfg.planner_tool == "claude"
        assert cfg.triage_tool == "gemini"
        assert cfg.transcript_summary_tool == "claude"
        assert cfg.ac_tool == "claude"
        assert cfg.verification_judge_tool == "claude"
        assert cfg.system_tool == "inherit"
        assert cfg.background_tool == "inherit"

    def test_tool_env_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Legacy HYDRAFLOW_*_TOOL vars are gone; use combo syntax instead.
        monkeypatch.setenv("HYDRAFLOW_IMPLEMENT", "codex:gpt-5-codex")
        monkeypatch.setenv("HYDRAFLOW_REVIEW", "codex:gpt-5-codex")
        monkeypatch.setenv("HYDRAFLOW_PLANNER", "codex:gpt-5-codex")
        monkeypatch.setenv("HYDRAFLOW_TRIAGE", "codex:gpt-5-codex")
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY", "codex:gpt-5-codex")
        monkeypatch.setenv("HYDRAFLOW_AC", "codex:gpt-5-codex")
        # verification_judge has no env var — it auto-syncs to review_tool.
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.implementation_tool == "codex"
        assert cfg.model == "gpt-5-codex"
        assert cfg.review_tool == "codex"
        assert cfg.planner_tool == "codex"
        assert cfg.triage_tool == "codex"
        assert cfg.transcript_summary_tool == "codex"
        assert cfg.ac_tool == "codex"
        assert cfg.verification_judge_tool == "codex"

    def test_tool_env_overrides_accept_pi(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Legacy HYDRAFLOW_*_TOOL vars are gone; use combo syntax instead.
        # Note: subskill_tool and debug_tool have no dedicated combo var;
        # they are set via system_tool profile propagation.
        monkeypatch.setenv("HYDRAFLOW_IMPLEMENT", "pi:pi-model")
        monkeypatch.setenv("HYDRAFLOW_REVIEW", "pi:pi-model")
        monkeypatch.setenv("HYDRAFLOW_PLANNER", "pi:pi-model")
        monkeypatch.setenv("HYDRAFLOW_TRIAGE", "pi:pi-model")
        monkeypatch.setenv("HYDRAFLOW_TRANSCRIPT_SUMMARY", "pi:pi-model")
        monkeypatch.setenv("HYDRAFLOW_AC", "pi:pi-model")
        # verification_judge has no env var — it auto-syncs to review_tool.
        monkeypatch.setenv("HYDRAFLOW_SYSTEM", "pi:pi-model")
        monkeypatch.setenv("HYDRAFLOW_BACKGROUND", "pi:pi-model")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.implementation_tool == "pi"
        assert cfg.review_tool == "pi"
        assert cfg.planner_tool == "pi"
        assert cfg.triage_tool == "pi"
        assert cfg.transcript_summary_tool == "pi"
        assert cfg.ac_tool == "pi"
        assert cfg.verification_judge_tool == "pi"
        assert cfg.system_tool == "pi"
        assert cfg.background_tool == "pi"

    def test_profile_tool_overrides_apply_to_defaults(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            system_tool="codex",
            system_model="gpt-5-codex",
            background_tool="codex",
            background_model="gpt-5-codex",
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

    def test_profile_model_overrides_apply_to_defaults(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            system_tool="codex",
            system_model="gpt-5-codex",
            background_tool="codex",
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

    def test_profile_overrides_do_not_clobber_explicit_per_field(
        self, tmp_path: Path
    ) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
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
            workspace_base=tmp_path / "wt",
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
