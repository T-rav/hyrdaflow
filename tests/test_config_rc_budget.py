"""Tests for RCBudgetLoop config fields (spec §4.8)."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_rc_budget_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYDRAFLOW_RC_BUDGET_INTERVAL", raising=False)
    monkeypatch.delenv("HYDRAFLOW_RC_BUDGET_THRESHOLD_RATIO", raising=False)
    monkeypatch.delenv("HYDRAFLOW_RC_BUDGET_SPIKE_RATIO", raising=False)
    cfg = HydraFlowConfig()
    assert cfg.rc_budget_interval == 14400
    assert cfg.rc_budget_threshold_ratio == 1.5
    assert cfg.rc_budget_spike_ratio == 2.0


def test_rc_budget_interval_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_RC_BUDGET_INTERVAL", "3600")
    cfg = HydraFlowConfig()
    assert cfg.rc_budget_interval == 3600


def test_rc_budget_threshold_ratio_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HYDRAFLOW_RC_BUDGET_THRESHOLD_RATIO", "1.25")
    cfg = HydraFlowConfig()
    assert cfg.rc_budget_threshold_ratio == 1.25


def test_rc_budget_spike_ratio_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_RC_BUDGET_SPIKE_RATIO", "3.0")
    cfg = HydraFlowConfig()
    assert cfg.rc_budget_spike_ratio == 3.0


def test_rc_budget_interval_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_interval=30)  # below 3600 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_interval=10_000_000)  # above 604800 max


def test_rc_budget_threshold_ratio_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_threshold_ratio=0.5)  # below 1.0 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_threshold_ratio=10.0)  # above 5.0 max


def test_rc_budget_spike_ratio_bounds() -> None:
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_spike_ratio=0.5)  # below 1.0 minimum
    with pytest.raises(ValueError):
        HydraFlowConfig(rc_budget_spike_ratio=20.0)  # above 10.0 max
