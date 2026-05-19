import json
from datetime import UTC, datetime

import pytest
from src.assumption_surfacer import AssumptionSurfacer, SurfacerOutput
from src.pending_concerns import Concern


class _StubAgent:
    """Captures the user_message passed to run() and returns a canned payload."""

    def __init__(self, payload: str):
        self.payload = payload
        self.last_system_prompt: str | None = None
        self.last_user_message: str | None = None

    async def run(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return self.payload


def _make_carryover_concern(cid: str, text: str) -> Concern:
    return Concern(
        id=cid,
        raised_in_phase="discover",
        raised_in_stage="prior_stage",
        severity="HIGH",
        concern=text,
        raised_at=datetime.now(UTC),
        must_address_by="assumption_surfacer",
    )


@pytest.mark.asyncio
async def test_returns_assumptions_and_concerns_from_agent_json():
    payload = json.dumps(
        {
            "assumptions": ["we assume the runner is async"],
            "concerns": [
                {
                    "severity": "HIGH",
                    "concern": "runner may be sync; planner would mis-shape",
                    "must_address_by": "planner",
                }
            ],
        }
    )
    surfacer = AssumptionSurfacer(agent=_StubAgent(payload), phase="plan")

    out = await surfacer.run(
        issue_body="Add X",
        research_context="prior PR notes",
        carryover_concerns=[],
    )

    assert isinstance(out, SurfacerOutput)
    assert out.assumptions == ["we assume the runner is async"]
    assert len(out.concerns) == 1
    assert out.concerns[0].severity == "HIGH"
    assert out.concerns[0].concern.startswith("runner may be sync")
    assert out.concerns[0].must_address_by == "planner"


@pytest.mark.asyncio
async def test_carryover_concerns_appear_in_agent_user_message():
    agent = _StubAgent(payload=json.dumps({"assumptions": [], "concerns": []}))
    surfacer = AssumptionSurfacer(agent=agent, phase="plan")

    carryover = [
        _make_carryover_concern("DISCOVER-EXPERT-001", "scope unclear"),
        _make_carryover_concern("DISCOVER-EXPERT-002", "no acceptance test"),
    ]

    await surfacer.run(
        issue_body="anything",
        research_context="research",
        carryover_concerns=carryover,
    )

    msg = agent.last_user_message
    assert msg is not None
    assert "DISCOVER-EXPERT-001" in msg
    assert "scope unclear" in msg
    assert "DISCOVER-EXPERT-002" in msg
    assert "no acceptance test" in msg


@pytest.mark.asyncio
async def test_malformed_json_degrades_to_empty_output():
    surfacer = AssumptionSurfacer(
        agent=_StubAgent(payload="not json at all <<<"),
        phase="plan",
    )

    out = await surfacer.run(
        issue_body="Add X",
        research_context="ctx",
        carryover_concerns=[],
    )

    assert out.assumptions == []
    assert out.concerns == []


@pytest.mark.asyncio
async def test_concern_ids_are_namespaced_by_phase():
    payload = json.dumps(
        {
            "assumptions": ["a"],
            "concerns": [
                {"severity": "MEDIUM", "concern": "c1", "must_address_by": "planner"},
                {"severity": "LOW", "concern": "c2", "must_address_by": "planner"},
            ],
        }
    )

    plan_surfacer = AssumptionSurfacer(agent=_StubAgent(payload), phase="plan")
    plan_out = await plan_surfacer.run("body", "ctx", [])

    discover_surfacer = AssumptionSurfacer(agent=_StubAgent(payload), phase="discover")
    discover_out = await discover_surfacer.run("body", "ctx", [])

    assert [c.id for c in plan_out.concerns] == [
        "PLAN-ASSUMP-001",
        "PLAN-ASSUMP-002",
    ]
    assert [c.id for c in discover_out.concerns] == [
        "DISCOVER-ASSUMP-001",
        "DISCOVER-ASSUMP-002",
    ]


@pytest.mark.asyncio
async def test_concerns_set_raised_in_phase_and_stage():
    payload = json.dumps(
        {
            "assumptions": [],
            "concerns": [
                {"severity": "HIGH", "concern": "c", "must_address_by": "planner"}
            ],
        }
    )
    surfacer = AssumptionSurfacer(agent=_StubAgent(payload), phase="discover")

    out = await surfacer.run("body", "ctx", [])

    assert len(out.concerns) == 1
    assert out.concerns[0].raised_in_phase == "discover"
    assert out.concerns[0].raised_in_stage == "assumption_surfacer"
