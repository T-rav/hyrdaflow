"""Unit tests for src.shape_expert_council.ShapeExpertCouncil.

The legacy direction-vote logic in :mod:`expert_council` is untouched
by Task 9; this module covers the parallel concern-shape adapter that
emits ``list[Concern]`` per the uniform earlier-adversarial pipeline
contract.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pending_concerns import Concern
from src.shape_expert_council import CouncilTally, ShapeExpertCouncil


class _ScriptedAgent:
    """Returns a fixed JSON payload and records the user_message it was called with."""

    def __init__(self, payload: str):
        self.payload = payload
        self.last_system_prompt: str | None = None
        self.last_user_message: str | None = None

    async def run(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return self.payload


def _payload(findings: list[dict[str, str]]) -> str:
    return json.dumps({"findings": findings})


def _empty_payload() -> str:
    return _payload([])


def _make_carryover_concern(cid: str, text: str) -> Concern:
    return Concern(
        id=cid,
        raised_in_phase="shape",
        raised_in_stage="prior_stage",
        severity="HIGH",
        concern=text,
        raised_at=datetime.now(UTC),
        must_address_by="shape_expert_council",
    )


@pytest.mark.asyncio
async def test_critical_from_any_voter_triggers_retry() -> None:
    """One voter emits CRITICAL → should_retry is True, CRITICAL forwarded."""
    council = ShapeExpertCouncil(
        agents={
            "user_advocate": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "CRITICAL",
                            "concern": "user flow is unworkable",
                        }
                    ]
                )
            ),
            "tech_lead": _ScriptedAgent(_empty_payload()),
            "product_strategist": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(shape_content="any shape", pending_concerns=[])

    assert isinstance(tally, CouncilTally)
    assert tally.should_retry is True
    critical = [c for c in tally.findings if c.severity == "CRITICAL"]
    assert critical and "unworkable" in critical[0].concern


@pytest.mark.asyncio
async def test_overlapping_high_triggers_retry() -> None:
    council = ShapeExpertCouncil(
        agents={
            "user_advocate": _ScriptedAgent(
                _payload(
                    [{"severity": "HIGH", "concern": "no user research underpins this"}]
                )
            ),
            "tech_lead": _ScriptedAgent(
                _payload(
                    [{"severity": "HIGH", "concern": "no user research underpins this"}]
                )
            ),
            "product_strategist": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(shape_content="any shape", pending_concerns=[])

    assert tally.should_retry is True


@pytest.mark.asyncio
async def test_lone_high_forwards_as_medium_no_retry() -> None:
    """A single voter's lone HIGH is downgraded to MEDIUM, no retry triggered."""
    council = ShapeExpertCouncil(
        agents={
            "user_advocate": _ScriptedAgent(
                _payload([{"severity": "HIGH", "concern": "UX is too clever"}])
            ),
            "tech_lead": _ScriptedAgent(_empty_payload()),
            "product_strategist": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(shape_content="any shape", pending_concerns=[])

    assert tally.should_retry is False
    matching = [c for c in tally.findings if "too clever" in c.concern]
    assert len(matching) == 1
    assert matching[0].severity == "MEDIUM"


@pytest.mark.asyncio
async def test_no_findings_converges() -> None:
    council = ShapeExpertCouncil(
        agents={
            "user_advocate": _ScriptedAgent(_empty_payload()),
            "tech_lead": _ScriptedAgent(_empty_payload()),
            "product_strategist": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(shape_content="solid shape", pending_concerns=[])

    assert tally.should_retry is False
    assert tally.findings == []


@pytest.mark.asyncio
async def test_concern_id_and_stage_anchors() -> None:
    """Each voter's findings get ``SHAPE-{ROLE_UPPER}-{i:03d}`` ids and the
    role-specific ``raised_in_stage``.
    """
    council = ShapeExpertCouncil(
        agents={
            "user_advocate": _ScriptedAgent(
                _payload(
                    [
                        {"severity": "MEDIUM", "concern": "u1"},
                        {"severity": "MEDIUM", "concern": "u2"},
                    ]
                )
            ),
            "tech_lead": _ScriptedAgent(
                _payload([{"severity": "MEDIUM", "concern": "t1"}])
            ),
            "product_strategist": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(shape_content="any", pending_concerns=[])

    ua_ids = sorted(
        c.id for c in tally.findings if c.raised_in_stage == "shape_user_advocate"
    )
    tl_ids = sorted(
        c.id for c in tally.findings if c.raised_in_stage == "shape_tech_lead"
    )
    assert ua_ids == ["SHAPE-USER_ADVOCATE-001", "SHAPE-USER_ADVOCATE-002"]
    assert tl_ids == ["SHAPE-TECH_LEAD-001"]
    assert all(c.raised_in_phase == "shape" for c in tally.findings)
    assert all(c.must_address_by == "plan" for c in tally.findings)


@pytest.mark.asyncio
async def test_pending_concerns_propagate_to_voter_prompts() -> None:
    """Carryover concern id + text must appear in each voter's user_message."""
    ua_agent = _ScriptedAgent(_empty_payload())
    tl_agent = _ScriptedAgent(_empty_payload())
    ps_agent = _ScriptedAgent(_empty_payload())

    council = ShapeExpertCouncil(
        agents={
            "user_advocate": ua_agent,
            "tech_lead": tl_agent,
            "product_strategist": ps_agent,
        }
    )

    pending = [
        _make_carryover_concern("SHAPE-CHAL-001", "differentiator weak"),
        _make_carryover_concern("DISC-ASSUMP-002", "scope unclear"),
    ]

    await council.deliberate(shape_content="proposal", pending_concerns=pending)

    for agent in (ua_agent, tl_agent, ps_agent):
        msg = agent.last_user_message
        assert msg is not None
        assert "SHAPE-CHAL-001" in msg
        assert "differentiator weak" in msg
        assert "DISC-ASSUMP-002" in msg
        assert "scope unclear" in msg
