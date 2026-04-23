"""Tests for TrustFleetSanityLoop config fields + env overrides (spec §12.1)."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig


def test_default_values() -> None:
    cfg = HydraFlowConfig()
    assert cfg.trust_fleet_sanity_interval == 600
    assert cfg.loop_anomaly_issues_per_hour == 10
    assert cfg.loop_anomaly_repair_ratio == 2.0
    assert cfg.loop_anomaly_tick_error_ratio == 0.2
    assert cfg.loop_anomaly_staleness_multiplier == 2.0
    assert cfg.loop_anomaly_cost_spike_ratio == 5.0


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYDRAFLOW_TRUST_FLEET_SANITY_INTERVAL", "900")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_ISSUES_PER_HOUR", "25")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_REPAIR_RATIO", "3.5")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_TICK_ERROR_RATIO", "0.5")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_STALENESS_MULTIPLIER", "4.0")
    monkeypatch.setenv("HYDRAFLOW_LOOP_ANOMALY_COST_SPIKE_RATIO", "10.0")
    cfg = HydraFlowConfig()
    assert cfg.trust_fleet_sanity_interval == 900
    assert cfg.loop_anomaly_issues_per_hour == 25
    assert cfg.loop_anomaly_repair_ratio == 3.5
    assert cfg.loop_anomaly_tick_error_ratio == 0.5
    assert cfg.loop_anomaly_staleness_multiplier == 4.0
    assert cfg.loop_anomaly_cost_spike_ratio == 10.0


def test_interval_bounds() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 60"):
        HydraFlowConfig(trust_fleet_sanity_interval=30)
    with pytest.raises(ValueError, match="less than or equal to 3600"):
        HydraFlowConfig(trust_fleet_sanity_interval=86400)


def test_tick_error_ratio_bounded_below_one() -> None:
    with pytest.raises(ValueError, match="less than or equal to 1"):
        HydraFlowConfig(loop_anomaly_tick_error_ratio=1.5)
