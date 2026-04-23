"""Tests for the HydraFlowConfig combo env var restructure."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig


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
