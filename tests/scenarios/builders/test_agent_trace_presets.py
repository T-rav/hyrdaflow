"""AgentTraceBuilder preset tests — credit_exhaustion, hitl_escalation, parse_error."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.trace import AgentTraceBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


def test_credit_exhaustion_then_recovery_scripts_two_results(world: MockWorld) -> None:
    AgentTraceBuilder().credit_exhaustion_then_recovery().for_phase(
        "implement"
    ).for_issue(1).at(world)
    scripts = world._llm.agents._scripts.get(1)
    assert scripts is not None and len(scripts) == 2
    # First is a failure (simulated credit exhaustion outcome)
    assert getattr(scripts[0], "success", True) is False
    # Second is a success (recovery)
    assert getattr(scripts[1], "success", False) is True


def test_hitl_escalation_scripts_failure(world: MockWorld) -> None:
    AgentTraceBuilder().hitl_escalation(reason="unclear scope").for_phase(
        "plan"
    ).for_issue(2).at(world)
    scripts = world._llm.planners._scripts.get(2)
    assert scripts is not None and len(scripts) == 1
    # HITL escalation is a plan failure with a reason
    assert getattr(scripts[0], "success", True) is False


def test_parse_error_mid_stream_scripts_failure(world: MockWorld) -> None:
    AgentTraceBuilder().parse_error_mid_stream().for_phase("implement").for_issue(3).at(
        world
    )
    scripts = world._llm.agents._scripts.get(3)
    assert scripts is not None and len(scripts) == 1
    assert getattr(scripts[0], "success", True) is False
