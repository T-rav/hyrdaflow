"""Unit tests for src.shape_challenger.ShapeChallenger.

Covers the concern-shape adapter introduced by Task 9 of the
earlier-adversarial pipeline: AgentLike → list[Concern] with the
SHAPE-CHAL-{i:03d} id convention and must_address_by == "expert_council".
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pending_concerns import Concern
from src.shape_challenger import (
    SHAPE_CHALLENGER_PROMPT,
    ChallengerOutput,
    ShapeChallenger,
)


class _ScriptedAgent:
    """Returns a fixed JSON payload and records the system/user prompts."""

    def __init__(self, payload: str):
        self.payload = payload
        self.last_system_prompt: str | None = None
        self.last_user_message: str | None = None

    async def run(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return self.payload


class _CrashingAgent:
    async def run(self, _system: str, _user: str) -> str:
        raise RuntimeError("agent boom")


def _payload(findings: list[dict[str, str]]) -> str:
    return json.dumps({"findings": findings})


def _make_carryover_concern(cid: str, text: str) -> Concern:
    return Concern(
        id=cid,
        raised_in_phase="discover",
        raised_in_stage="assumption_surfacer",
        severity="HIGH",
        concern=text,
        raised_at=datetime.now(UTC),
        must_address_by="shape",
    )


@pytest.mark.asyncio
async def test_emits_well_shaped_concerns() -> None:
    """Adapter produces SHAPE-CHAL-{i:03d} concerns with the right anchors."""
    agent = _ScriptedAgent(
        _payload(
            [
                {"severity": "CRITICAL", "concern": "differentiator is hand-waved"},
                {"severity": "MEDIUM", "concern": "MVP scope quietly drifts"},
            ]
        )
    )
    challenger = ShapeChallenger(agent=agent)

    out: ChallengerOutput = await challenger.run(
        shape_content="some proposal", carryover_concerns=[]
    )

    assert len(out.findings) == 2
    assert [c.id for c in out.findings] == ["SHAPE-CHAL-001", "SHAPE-CHAL-002"]
    assert all(c.raised_in_phase == "shape" for c in out.findings)
    assert all(c.raised_in_stage == "shape_challenger" for c in out.findings)
    assert all(c.must_address_by == "expert_council" for c in out.findings)
    severities = [c.severity for c in out.findings]
    assert severities == ["CRITICAL", "MEDIUM"]


@pytest.mark.asyncio
async def test_empty_findings_when_proposal_is_clean() -> None:
    agent = _ScriptedAgent(_payload([]))
    challenger = ShapeChallenger(agent=agent)

    out = await challenger.run(shape_content="solid proposal", carryover_concerns=[])

    assert out.findings == []


@pytest.mark.asyncio
async def test_soft_fails_on_malformed_json() -> None:
    """Malformed agent output returns an empty findings list, no exception."""
    agent = _ScriptedAgent("not json {{")
    challenger = ShapeChallenger(agent=agent)

    out = await challenger.run(shape_content="any", carryover_concerns=[])

    assert out.findings == []


@pytest.mark.asyncio
async def test_soft_fails_on_agent_crash() -> None:
    """A crashing agent returns an empty findings list — no propagation."""
    challenger = ShapeChallenger(agent=_CrashingAgent())

    out = await challenger.run(shape_content="any", carryover_concerns=[])

    assert out.findings == []


@pytest.mark.asyncio
async def test_carryover_concerns_appear_in_user_message() -> None:
    """Pending concerns from earlier stages get threaded into the prompt."""
    agent = _ScriptedAgent(_payload([]))
    challenger = ShapeChallenger(agent=agent)

    pending = [
        _make_carryover_concern("DISC-PROBLEM_SHARPENER-001", "scope unclear"),
        _make_carryover_concern("SHAPE-ASSUMP-002", "implicit cost assumption"),
    ]

    await challenger.run(shape_content="proposal body", carryover_concerns=pending)

    msg = agent.last_user_message
    assert msg is not None
    assert "DISC-PROBLEM_SHARPENER-001" in msg
    assert "scope unclear" in msg
    assert "SHAPE-ASSUMP-002" in msg
    assert "implicit cost assumption" in msg
    assert agent.last_system_prompt == SHAPE_CHALLENGER_PROMPT
