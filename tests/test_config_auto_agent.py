"""Auto-agent config field defaults (spec §5.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig


def test_defaults() -> None:
    c = HydraFlowConfig()
    assert c.auto_agent_preflight_enabled is True
    assert c.auto_agent_preflight_interval == 120
    assert c.auto_agent_max_attempts == 3
    assert c.auto_agent_skip_sublabels == ["principles-stuck", "cultural-check"]
    assert c.auto_agent_cost_cap_usd is None
    assert c.auto_agent_wall_clock_cap_s is None
    assert c.auto_agent_daily_budget_usd is None
    assert "lead engineer" in c.auto_agent_persona


def test_interval_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_preflight_interval=30)
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_preflight_interval=601)


def test_max_attempts_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_max_attempts=0)
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_max_attempts=11)
