"""AgentTraceBuilder preset tests — credit_exhaustion, hitl_escalation, parse_error.

Each preset must produce a DISTINCT error payload so tests can differentiate
between credit-exhaustion vs hitl-escalation vs parse-error in assertions.
Bare success/failure shape is proved by `test_agent_trace_builder.py`; this
file verifies the presets carry identifying information.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.trace import AgentTraceBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


def test_credit_exhaustion_then_recovery_carries_distinct_error(
    world: MockWorld,
) -> None:
    AgentTraceBuilder().credit_exhaustion_then_recovery().for_phase(
        "implement"
    ).for_issue(1).at(world)
    scripts = world._llm.agents._scripts.get(1)
    assert scripts is not None and len(scripts) == 2

    # First is a CREDIT-EXHAUSTION failure, not a generic failure.
    first = scripts[0]
    assert getattr(first, "success", True) is False
    assert "credit" in (getattr(first, "error", "") or "").lower(), (
        f"credit_exhaustion_then_recovery first result should identify itself "
        f"as credit-exhausted, got error={getattr(first, 'error', None)!r}"
    )
    # Second is recovery (plain success).
    assert getattr(scripts[1], "success", False) is True


def test_hitl_escalation_carries_reason(world: MockWorld) -> None:
    AgentTraceBuilder().hitl_escalation(reason="unclear scope").for_phase(
        "plan"
    ).for_issue(2).at(world)
    scripts = world._llm.planners._scripts.get(2)
    assert scripts is not None and len(scripts) == 1

    first = scripts[0]
    assert getattr(first, "success", True) is False
    # The reason must be threaded into the scripted error so scenarios can
    # assert WHICH hitl escalation fired.
    assert "unclear scope" in (getattr(first, "error", "") or ""), (
        f"hitl_escalation(reason=...) must record the reason on the result, "
        f"got error={getattr(first, 'error', None)!r}"
    )


def test_parse_error_mid_stream_carries_distinct_error(world: MockWorld) -> None:
    AgentTraceBuilder().parse_error_mid_stream().for_phase("implement").for_issue(3).at(
        world
    )
    scripts = world._llm.agents._scripts.get(3)
    assert scripts is not None and len(scripts) == 1

    first = scripts[0]
    assert getattr(first, "success", True) is False
    assert "parse" in (getattr(first, "error", "") or "").lower(), (
        f"parse_error_mid_stream must identify itself in result.error, "
        f"got error={getattr(first, 'error', None)!r}"
    )


def test_presets_produce_distinct_errors(world: MockWorld) -> None:
    """The 3 presets must produce DIFFERENT error strings — no collisions."""
    AgentTraceBuilder().credit_exhaustion_then_recovery().for_phase(
        "implement"
    ).for_issue(10).at(world)
    AgentTraceBuilder().hitl_escalation(reason="scope-X").for_phase("plan").for_issue(
        11
    ).at(world)
    AgentTraceBuilder().parse_error_mid_stream().for_phase("implement").for_issue(
        12
    ).at(world)

    credit_err = world._llm.agents._scripts[10][0].error
    hitl_err = world._llm.planners._scripts[11][0].error
    parse_err = world._llm.agents._scripts[12][0].error

    assert len({credit_err, hitl_err, parse_err}) == 3, (
        f"preset errors collide: credit={credit_err!r} hitl={hitl_err!r} "
        f"parse={parse_err!r}"
    )
