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


def test_term_proposer_config_defaults() -> None:
    config = HydraFlowConfig()
    assert config.term_proposer_enabled is True
    assert config.term_proposer_interval == 14400
    assert config.term_proposer_max_per_tick == 10
    assert config.term_proposer_cooldown_seconds == 86400


def test_term_proposer_interval_lower_bound_rejected() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(term_proposer_interval=3599)


def test_term_proposer_interval_upper_bound_rejected() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(term_proposer_interval=86401)


def test_term_proposer_max_per_tick_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(term_proposer_max_per_tick=0)
    with pytest.raises(ValueError):
        HydraFlowConfig(term_proposer_max_per_tick=51)


def test_term_proposer_cooldown_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(term_proposer_cooldown_seconds=3599)
    with pytest.raises(ValueError):
        HydraFlowConfig(term_proposer_cooldown_seconds=604801)


def test_term_proposer_interval_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_TERM_PROPOSER_INTERVAL", "7200")
    cfg = HydraFlowConfig()
    assert cfg.term_proposer_interval == 7200


def test_term_proposer_max_per_tick_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_TERM_PROPOSER_MAX_PER_TICK", "20")
    cfg = HydraFlowConfig()
    assert cfg.term_proposer_max_per_tick == 20


def test_term_proposer_cooldown_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_TERM_PROPOSER_COOLDOWN_SECONDS", "172800")
    cfg = HydraFlowConfig()
    assert cfg.term_proposer_cooldown_seconds == 172800


def test_term_proposer_enabled_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_TERM_PROPOSER_ENABLED", "false")
    cfg = HydraFlowConfig()
    assert cfg.term_proposer_enabled is False
