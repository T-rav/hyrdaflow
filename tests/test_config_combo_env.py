"""Tests for the HydraFlowConfig combo env var restructure."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig, _parse_combo


def test_triage_tool_accepts_gemini() -> None:
    cfg = HydraFlowConfig(triage_tool="gemini", triage_model="gemini-3.1-pro-preview")
    assert cfg.triage_tool == "gemini"
    assert cfg.triage_model == "gemini-3.1-pro-preview"


def test_implementation_tool_accepts_gemini() -> None:
    cfg = HydraFlowConfig(implementation_tool="gemini", model="gemini-3.1-pro-preview")
    assert cfg.implementation_tool == "gemini"


def test_system_tool_accepts_gemini() -> None:
    cfg = HydraFlowConfig(system_tool="gemini", system_model="gemini-3.1-pro-preview")
    assert cfg.system_tool == "gemini"


def test_invalid_tool_rejected() -> None:
    with pytest.raises(ValidationError):
        HydraFlowConfig(triage_tool="bogus")


def test_parse_combo_basic() -> None:
    assert _parse_combo("HYDRAFLOW_IMPLEMENT", "claude:opus") == ("claude", "opus")


def test_parse_combo_gemini() -> None:
    assert _parse_combo("HYDRAFLOW_TRIAGE", "gemini:gemini-3.1-pro-preview") == (
        "gemini",
        "gemini-3.1-pro-preview",
    )


def test_parse_combo_inherit() -> None:
    assert _parse_combo("HYDRAFLOW_SYSTEM", "inherit") == ("inherit", "")


def test_parse_combo_missing_colon_raises() -> None:
    with pytest.raises(ValueError, match="must be 'tool:model'"):
        _parse_combo("HYDRAFLOW_IMPLEMENT", "claude-opus")


def test_parse_combo_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        _parse_combo("HYDRAFLOW_IMPLEMENT", "bogus:opus")


def test_parse_combo_empty_model_raises() -> None:
    with pytest.raises(ValueError, match="model part is empty"):
        _parse_combo("HYDRAFLOW_IMPLEMENT", "claude:")


def test_combo_env_sets_triage_tool_and_model() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_TRIAGE": "gemini:gemini-3.1-pro-preview"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert cfg.triage_tool == "gemini"
        assert cfg.triage_model == "gemini-3.1-pro-preview"


def test_combo_env_sets_implementation_tool_and_model() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_IMPLEMENT": "codex:gpt-5-codex"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert cfg.implementation_tool == "codex"
        assert cfg.model == "gpt-5-codex"


def test_combo_env_review_and_planner() -> None:
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_REVIEW": "claude:sonnet",
            "HYDRAFLOW_PLANNER": "claude:opus",
        },
        clear=False,
    ):
        cfg = HydraFlowConfig()
        assert cfg.review_tool == "claude"
        assert cfg.review_model == "sonnet"
        assert cfg.planner_tool == "claude"
        assert cfg.planner_model == "opus"


def test_combo_env_system_inherit() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_SYSTEM": "inherit"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.system_tool == "inherit"
        assert cfg.system_model == ""


def test_legacy_triage_tool_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_TRIAGE_TOOL": "codex"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.triage_tool == HydraFlowConfig.model_fields["triage_tool"].default


def test_legacy_model_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_MODEL": "gpt-5-codex"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.model == HydraFlowConfig.model_fields["model"].default


def test_legacy_label_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_LABEL_READY": "custom-ready"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.ready_label == HydraFlowConfig.model_fields["ready_label"].default


def test_legacy_max_subskill_attempts_env_var_is_ignored() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_MAX_SUBSKILL_ATTEMPTS": "5"}, clear=False):
        cfg = HydraFlowConfig()
        assert (
            cfg.max_subskill_attempts
            == HydraFlowConfig.model_fields["max_subskill_attempts"].default
        )


def test_legacy_debug_escalation_env_var_is_ignored() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_DEBUG_ESCALATION_ENABLED": "false"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert (
            cfg.debug_escalation_enabled
            == HydraFlowConfig.model_fields["debug_escalation_enabled"].default
        )


def test_harmonize_rejects_gemini_flash_model() -> None:
    with pytest.raises(ValueError, match="flash"):
        HydraFlowConfig(
            implementation_tool="gemini",
            model="gemini-3-flash-preview",
        )


def test_harmonize_rejects_flash_in_triage() -> None:
    with pytest.raises(ValueError, match="flash"):
        HydraFlowConfig(triage_tool="gemini", triage_model="gemini-3-flash-preview")


def test_harmonize_rejects_claude_model_on_gemini_tool() -> None:
    with pytest.raises(ValueError, match="mismatched"):
        HydraFlowConfig(implementation_tool="gemini", model="opus")


def test_harmonize_rejects_codex_model_on_claude_tool() -> None:
    with pytest.raises(ValueError, match="mismatched"):
        HydraFlowConfig(implementation_tool="claude", model="gpt-5-codex")


def test_harmonize_allows_claude_opus() -> None:
    cfg = HydraFlowConfig(implementation_tool="claude", model="opus")
    assert cfg.model == "opus"


def test_harmonize_allows_gemini_pro() -> None:
    cfg = HydraFlowConfig(implementation_tool="gemini", model="gemini-3.1-pro-preview")
    assert cfg.model == "gemini-3.1-pro-preview"


def test_harmonize_allows_codex_gpt() -> None:
    cfg = HydraFlowConfig(implementation_tool="codex", model="gpt-5-codex")
    assert cfg.model == "gpt-5-codex"


def test_triage_defaults_to_gemini_pro() -> None:
    cfg = HydraFlowConfig()
    assert cfg.triage_tool == "gemini"
    assert cfg.triage_model == "gemini-3.1-pro-preview"


def test_combo_env_sets_sentry_tool_and_model() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_SENTRY": "claude:sonnet"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.sentry_tool == "claude"
        assert cfg.sentry_model == "sonnet"


def test_combo_env_sets_code_grooming_tool_and_model() -> None:
    with patch.dict(
        os.environ, {"HYDRAFLOW_CODE_GROOMING": "codex:gpt-5-codex"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert cfg.code_grooming_tool == "codex"
        assert cfg.code_grooming_model == "gpt-5-codex"


def test_combo_env_sets_adr_review_tool_and_model() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_ADR_REVIEW": "claude:opus"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.adr_review_tool == "claude"
        assert cfg.adr_review_model == "opus"


def test_background_cascade_reaches_sentry_code_grooming_adr_review() -> None:
    """HYDRAFLOW_BACKGROUND=claude:sonnet must pin the bg-only workers."""
    with patch.dict(os.environ, {"HYDRAFLOW_BACKGROUND": "claude:sonnet"}, clear=False):
        cfg = HydraFlowConfig()
        assert cfg.sentry_tool == "claude"
        assert cfg.sentry_model == "sonnet"
        assert cfg.code_grooming_tool == "claude"
        assert cfg.code_grooming_model == "sonnet"
        assert cfg.adr_review_tool == "claude"
        assert cfg.adr_review_model == "sonnet"


def test_background_cascade_cross_provider_codex() -> None:
    """HYDRAFLOW_BACKGROUND=codex:gpt-5-codex must cascade tool+model coherently
    to every bg-only worker and pass harmonize's cross-provider check."""
    with patch.dict(
        os.environ, {"HYDRAFLOW_BACKGROUND": "codex:gpt-5-codex"}, clear=False
    ):
        cfg = HydraFlowConfig()
        for stage in ("sentry", "code_grooming", "adr_review"):
            assert getattr(cfg, f"{stage}_tool") == "codex"
            assert getattr(cfg, f"{stage}_model") == "gpt-5-codex"
