"""Tests for the HydraFlowConfig combo env var restructure."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig, _parse_combo


def test_triage_tool_accepts_gemini() -> None:
    cfg = HydraFlowConfig(triage_tool="gemini", triage_model="gemini-3-pro")
    assert cfg.triage_tool == "gemini"
    assert cfg.triage_model == "gemini-3-pro"


def test_implementation_tool_accepts_gemini() -> None:
    cfg = HydraFlowConfig(implementation_tool="gemini", model="gemini-3-pro")
    assert cfg.implementation_tool == "gemini"


def test_system_tool_accepts_gemini() -> None:
    cfg = HydraFlowConfig(system_tool="gemini")
    assert cfg.system_tool == "gemini"


def test_invalid_tool_rejected() -> None:
    with pytest.raises(ValidationError):
        HydraFlowConfig(triage_tool="bogus")


def test_parse_combo_basic() -> None:
    assert _parse_combo("HYDRAFLOW_IMPLEMENT", "claude:opus") == ("claude", "opus")


def test_parse_combo_gemini() -> None:
    assert _parse_combo("HYDRAFLOW_TRIAGE", "gemini:gemini-3-pro") == (
        "gemini",
        "gemini-3-pro",
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
        os.environ, {"HYDRAFLOW_TRIAGE": "gemini:gemini-3-pro"}, clear=False
    ):
        cfg = HydraFlowConfig()
        assert cfg.triage_tool == "gemini"
        assert cfg.triage_model == "gemini-3-pro"


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
