import json
from datetime import UTC, datetime

import pytest
from src.pending_concerns import Concern
from src.spec_judge import JudgeResult, SpecJudge


class _StubAgent:
    """Returns a canned payload and records the prompts it was called with."""

    def __init__(self, payload: str):
        self.payload = payload
        self.last_system_prompt: str | None = None
        self.last_user_message: str | None = None

    async def run(self, system_prompt: str, user_message: str) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        return self.payload


def _make_pending_concern(cid: str, text: str) -> Concern:
    return Concern(
        id=cid,
        raised_in_phase="plan",
        raised_in_stage="prior_stage",
        severity="HIGH",
        concern=text,
        raised_at=datetime.now(UTC),
        must_address_by="spec_judge",
    )


@pytest.mark.asyncio
async def test_pass_verdict_when_ac_are_concrete_and_testable():
    payload = json.dumps({"verdict": "PASS", "findings": []})
    judge = SpecJudge(agent=_StubAgent(payload))

    result = await judge.evaluate(
        plan_text="a plan",
        acceptance_criteria=["AC1: concrete and testable"],
    )

    assert isinstance(result, JudgeResult)
    assert result.verdict == "PASS"
    assert result.findings == []


@pytest.mark.asyncio
async def test_fail_verdict_with_findings():
    payload = json.dumps(
        {
            "verdict": "FAIL",
            "findings": [
                {
                    "severity": "HIGH",
                    "concern": "AC2 says 'reasonable' — not observable",
                }
            ],
        }
    )
    judge = SpecJudge(agent=_StubAgent(payload))

    result = await judge.evaluate(
        plan_text="a plan",
        acceptance_criteria=["AC1 ok", "AC2 says 'reasonable performance'"],
    )

    assert result.verdict == "FAIL"
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "HIGH"
    assert "reasonable" in finding.concern
    assert finding.id == "SPEC-JUDGE-001"
    assert finding.raised_in_phase == "plan"
    assert finding.raised_in_stage == "spec_judge"
    assert finding.must_address_by == "implement"


@pytest.mark.asyncio
async def test_pending_concerns_appear_in_agent_user_message():
    agent = _StubAgent(payload=json.dumps({"verdict": "PASS", "findings": []}))
    judge = SpecJudge(agent=agent)

    pending = [
        _make_pending_concern("PLAN-ASSUMP-001", "runner shape unverified"),
        _make_pending_concern("PLAN-BUILDER-002", "AC4 lacks input data"),
    ]

    await judge.evaluate(
        plan_text="plan body",
        acceptance_criteria=["AC1", "AC2"],
        pending_concerns=pending,
    )

    msg = agent.last_user_message
    assert msg is not None
    assert "PLAN-ASSUMP-001" in msg
    assert "runner shape unverified" in msg
    assert "PLAN-BUILDER-002" in msg
    assert "AC4 lacks input data" in msg
