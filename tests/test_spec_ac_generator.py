import json

import pytest
from src.spec_ac_generator import SpecACGenerator


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


@pytest.mark.asyncio
async def test_extracts_observable_criteria_from_agent_output():
    payload = json.dumps(
        {
            "acceptance_criteria": [
                "Given input X, run() returns Y",
                "When malformed JSON arrives, draft() returns []",
            ]
        }
    )
    generator = SpecACGenerator(agent=_StubAgent(payload))

    criteria = await generator.draft(plan_text="any plan body")

    assert criteria == [
        "Given input X, run() returns Y",
        "When malformed JSON arrives, draft() returns []",
    ]


@pytest.mark.asyncio
async def test_malformed_json_returns_empty_list():
    generator = SpecACGenerator(agent=_StubAgent(payload="not json <<<"))

    criteria = await generator.draft(plan_text="any plan body")

    assert criteria == []
