import json
from datetime import UTC, datetime

import pytest
from src.pending_concerns import Concern
from src.plan_council import CouncilTally, PlanCouncil


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
        raised_in_phase="plan",
        raised_in_stage="prior_stage",
        severity="HIGH",
        concern=text,
        raised_at=datetime.now(UTC),
        must_address_by="plan_council",
    )


@pytest.mark.asyncio
async def test_critical_from_any_voter_triggers_retry():
    """One voter emits CRITICAL → tally.should_retry is True, CRITICAL forwarded."""
    council = PlanCouncil(
        agents={
            "builder": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "CRITICAL",
                            "concern": "task 3 references nonexistent file",
                        }
                    ]
                )
            ),
            "tester": _ScriptedAgent(_empty_payload()),
            "risk_skeptic": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(plan_text="any plan", pending_concerns=[])

    assert isinstance(tally, CouncilTally)
    assert tally.should_retry is True
    assert any(c.severity == "CRITICAL" for c in tally.findings)
    assert any(
        "nonexistent file" in c.concern
        for c in tally.findings
        if c.severity == "CRITICAL"
    )


@pytest.mark.asyncio
async def test_overlapping_high_triggers_retry():
    """Two voters land on string-similar HIGH findings → retry."""
    council = PlanCouncil(
        agents={
            "builder": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "HIGH",
                            "concern": "task 4 has no acceptance criteria",
                        }
                    ]
                )
            ),
            "tester": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "HIGH",
                            "concern": "task 4 has no acceptance criteria",
                        }
                    ]
                )
            ),
            "risk_skeptic": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(plan_text="any plan", pending_concerns=[])

    assert tally.should_retry is True


@pytest.mark.asyncio
async def test_lone_high_forwards_as_medium_no_retry():
    """A single voter's lone HIGH is downgraded to MEDIUM, no retry triggered."""
    council = PlanCouncil(
        agents={
            "builder": _ScriptedAgent(
                _payload([{"severity": "HIGH", "concern": "task 2 is hand-wavy"}])
            ),
            "tester": _ScriptedAgent(_empty_payload()),
            "risk_skeptic": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(plan_text="any plan", pending_concerns=[])

    assert tally.should_retry is False
    matching = [c for c in tally.findings if "hand-wavy" in c.concern]
    assert len(matching) == 1
    assert matching[0].severity == "MEDIUM"


@pytest.mark.asyncio
async def test_no_findings_converges():
    """All three voters empty → no retry, no findings."""
    council = PlanCouncil(
        agents={
            "builder": _ScriptedAgent(_empty_payload()),
            "tester": _ScriptedAgent(_empty_payload()),
            "risk_skeptic": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(plan_text="solid plan", pending_concerns=[])

    assert tally.should_retry is False
    assert tally.findings == []


@pytest.mark.asyncio
async def test_pending_concerns_propagate_to_voter_prompts():
    """Carryover concern id + text must appear in each voter's user_message."""
    builder_agent = _ScriptedAgent(_empty_payload())
    tester_agent = _ScriptedAgent(_empty_payload())
    risk_agent = _ScriptedAgent(_empty_payload())

    council = PlanCouncil(
        agents={
            "builder": builder_agent,
            "tester": tester_agent,
            "risk_skeptic": risk_agent,
        }
    )

    pending = [
        _make_carryover_concern("DISCOVER-EXPERT-001", "scope unclear"),
        _make_carryover_concern("PLAN-ASSUMP-002", "runner must be async"),
    ]

    await council.deliberate(plan_text="plan body", pending_concerns=pending)

    for agent in (builder_agent, tester_agent, risk_agent):
        msg = agent.last_user_message
        assert msg is not None
        assert "DISCOVER-EXPERT-001" in msg
        assert "scope unclear" in msg
        assert "PLAN-ASSUMP-002" in msg
        assert "runner must be async" in msg
