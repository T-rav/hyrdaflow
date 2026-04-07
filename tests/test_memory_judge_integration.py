"""Integration test: file_memory_suggestion routes through the judge."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class _FakeResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def _fake_config(tmp_path):
    from tests.helpers import ConfigFactory

    return ConfigFactory.create(repo_root=tmp_path)


@pytest.mark.asyncio
async def test_rejected_memory_lands_in_rejected_jsonl(tmp_path):
    from memory import file_memory_suggestion
    from memory_judge import MemoryJudge

    cfg = _fake_config(tmp_path)
    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='{"score": 0.1, "verdict": "reject", "reason": "noise"}'
    )
    # Use a MagicMock for config-on-judge so we don't depend on full HydraFlowConfig wiring
    judge_cfg = MagicMock()
    judge_cfg.background_tool = "claude"
    judge_cfg.memory_judge_model = "haiku"
    judge_cfg.agent_timeout = 60
    judge = MemoryJudge(config=judge_cfg, runner=runner, threshold=0.7)

    transcript = (
        "MEMORY_SUGGESTION_START\n"
        "principle: Trivial implementation detail not worth keeping forever.\n"
        "rationale: Just changed a variable name in one PR.\n"
        "failure_mode: Nothing meaningful happens if ignored.\n"
        "scope: src/whatever.py\n"
        "MEMORY_SUGGESTION_END\n"
    )

    await file_memory_suggestion(
        transcript, source="implement", reference="test", config=cfg, judge=judge
    )

    rejected_path = cfg.data_path("memory", "rejected.jsonl")
    items_path = cfg.data_path("memory", "items.jsonl")

    assert rejected_path.exists()
    rejected_lines = rejected_path.read_text().strip().splitlines()
    assert len(rejected_lines) == 1
    record = json.loads(rejected_lines[0])
    assert record["judge_score"] == 0.1
    assert "noise" in record["judge_reason"]
    # The accepted item should NOT have been written.
    assert not items_path.exists() or items_path.read_text() == ""


@pytest.mark.asyncio
async def test_accepted_memory_flows_through_normally(tmp_path):
    from memory import file_memory_suggestion
    from memory_judge import MemoryJudge

    cfg = _fake_config(tmp_path)
    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='{"score": 0.9, "verdict": "accept", "reason": "good"}'
    )
    judge_cfg = MagicMock()
    judge_cfg.background_tool = "claude"
    judge_cfg.memory_judge_model = "haiku"
    judge_cfg.agent_timeout = 60
    judge = MemoryJudge(config=judge_cfg, runner=runner, threshold=0.7)

    transcript = (
        "MEMORY_SUGGESTION_START\n"
        "principle: A genuinely durable architectural rule worth keeping.\n"
        "rationale: Captured after a real production incident.\n"
        "failure_mode: Future agents repeat the same mistake.\n"
        "scope: src/memory.py\n"
        "MEMORY_SUGGESTION_END\n"
    )

    await file_memory_suggestion(
        transcript, source="review", reference="test", config=cfg, judge=judge
    )

    items_path = cfg.data_path("memory", "items.jsonl")
    assert items_path.exists()
    assert len(items_path.read_text().strip().splitlines()) == 1
