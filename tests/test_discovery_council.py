import json
from datetime import UTC, datetime

import pytest
from src.discovery_council import CouncilTally, DiscoveryCouncil
from src.pending_concerns import Concern


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
        raised_in_phase="discover",
        raised_in_stage="prior_stage",
        severity="HIGH",
        concern=text,
        raised_at=datetime.now(UTC),
        must_address_by="discovery_council",
    )


@pytest.mark.asyncio
async def test_critical_from_any_voter_triggers_retry():
    """One voter emits CRITICAL → tally.should_retry is True, CRITICAL forwarded."""
    council = DiscoveryCouncil(
        agents={
            "problem_sharpener": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "CRITICAL",
                            "concern": "issue conflates two distinct problems",
                        }
                    ]
                )
            ),
            "existing_solution_hunter": _ScriptedAgent(_empty_payload()),
            "cheapest_test_advocate": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(discovery_text="any brief", pending_concerns=[])

    assert isinstance(tally, CouncilTally)
    assert tally.should_retry is True
    assert any(c.severity == "CRITICAL" for c in tally.findings)
    assert any(
        "two distinct problems" in c.concern
        for c in tally.findings
        if c.severity == "CRITICAL"
    )


@pytest.mark.asyncio
async def test_overlapping_high_triggers_retry():
    """Two voters land on string-similar HIGH findings → retry."""
    council = DiscoveryCouncil(
        agents={
            "problem_sharpener": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "HIGH",
                            "concern": "no underlying pain statement is named",
                        }
                    ]
                )
            ),
            "existing_solution_hunter": _ScriptedAgent(
                _payload(
                    [
                        {
                            "severity": "HIGH",
                            "concern": "no underlying pain statement is named",
                        }
                    ]
                )
            ),
            "cheapest_test_advocate": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(discovery_text="any brief", pending_concerns=[])

    assert tally.should_retry is True


@pytest.mark.asyncio
async def test_lone_high_forwards_as_medium_no_retry():
    """A single voter's lone HIGH is downgraded to MEDIUM, no retry triggered."""
    council = DiscoveryCouncil(
        agents={
            "problem_sharpener": _ScriptedAgent(
                _payload(
                    [{"severity": "HIGH", "concern": "pain statement is hand-wavy"}]
                )
            ),
            "existing_solution_hunter": _ScriptedAgent(_empty_payload()),
            "cheapest_test_advocate": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(discovery_text="any brief", pending_concerns=[])

    assert tally.should_retry is False
    matching = [c for c in tally.findings if "hand-wavy" in c.concern]
    assert len(matching) == 1
    assert matching[0].severity == "MEDIUM"


@pytest.mark.asyncio
async def test_no_findings_converges():
    """All three voters empty → no retry, no findings."""
    council = DiscoveryCouncil(
        agents={
            "problem_sharpener": _ScriptedAgent(_empty_payload()),
            "existing_solution_hunter": _ScriptedAgent(_empty_payload()),
            "cheapest_test_advocate": _ScriptedAgent(_empty_payload()),
        }
    )

    tally = await council.deliberate(discovery_text="solid brief", pending_concerns=[])

    assert tally.should_retry is False
    assert tally.findings == []


@pytest.mark.asyncio
async def test_pending_concerns_propagate_to_voter_prompts():
    """Carryover concern id + text must appear in each voter's user_message."""
    sharpener_agent = _ScriptedAgent(_empty_payload())
    hunter_agent = _ScriptedAgent(_empty_payload())
    cheapest_agent = _ScriptedAgent(_empty_payload())

    council = DiscoveryCouncil(
        agents={
            "problem_sharpener": sharpener_agent,
            "existing_solution_hunter": hunter_agent,
            "cheapest_test_advocate": cheapest_agent,
        }
    )

    pending = [
        _make_carryover_concern("DISCOVER-ASSUMP-001", "scope unclear"),
        _make_carryover_concern("DISCOVER-ASSUMP-002", "runner must be async"),
    ]

    await council.deliberate(discovery_text="brief body", pending_concerns=pending)

    for agent in (sharpener_agent, hunter_agent, cheapest_agent):
        msg = agent.last_user_message
        assert msg is not None
        assert "DISCOVER-ASSUMP-001" in msg
        assert "scope unclear" in msg
        assert "DISCOVER-ASSUMP-002" in msg
        assert "runner must be async" in msg
