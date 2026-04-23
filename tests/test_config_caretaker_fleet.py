"""Tests for caretaker-fleet config fields (Plan 5)."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_flake_tracker_interval_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_FLAKE_TRACKER_INTERVAL", raising=False)
    monkeypatch.delenv("HYDRAFLOW_FLAKE_THRESHOLD", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.flake_tracker_interval == 14400
    assert cfg.flake_threshold == 3


def test_flake_tracker_interval_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_FLAKE_TRACKER_INTERVAL", "3600")
    cfg = HydraFlowConfig()
    assert cfg.flake_tracker_interval == 3600


def test_flake_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_FLAKE_THRESHOLD", "5")
    cfg = HydraFlowConfig()
    assert cfg.flake_threshold == 5


def test_flake_tracker_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(flake_tracker_interval=30)  # below 3600 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(flake_tracker_interval=10_000_000)  # above 30d


def test_flake_threshold_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(flake_threshold=1)  # below 2 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(flake_threshold=100)  # above 20 max


def test_skill_prompt_eval_interval_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_SKILL_PROMPT_EVAL_INTERVAL", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.skill_prompt_eval_interval == 604800


def test_skill_prompt_eval_interval_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_SKILL_PROMPT_EVAL_INTERVAL", "86400")
    cfg = HydraFlowConfig()
    assert cfg.skill_prompt_eval_interval == 86400


def test_skill_prompt_eval_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(skill_prompt_eval_interval=60)  # below 86400 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(skill_prompt_eval_interval=10_000_000)  # above 30d max


def test_fake_coverage_auditor_interval_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HYDRAFLOW_FAKE_COVERAGE_AUDITOR_INTERVAL", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.fake_coverage_auditor_interval == 604800


def test_fake_coverage_auditor_interval_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_FAKE_COVERAGE_AUDITOR_INTERVAL", "86400")
    cfg = HydraFlowConfig()
    assert cfg.fake_coverage_auditor_interval == 86400


def test_fake_coverage_auditor_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(fake_coverage_auditor_interval=60)  # below 86400 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(fake_coverage_auditor_interval=10_000_000)  # above 30d max
