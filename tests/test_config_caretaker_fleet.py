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
