"""Tests for the explicit tribal_recorder.record_tribal_knowledge tool."""

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
async def test_record_tribal_knowledge_routes_through_judge_and_stores(tmp_path):
    from memory_judge import MemoryJudge
    from tribal_recorder import record_tribal_knowledge

    cfg = _fake_config(tmp_path)
    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='{"score": 0.9, "verdict": "accept", "reason": "ok"}'
    )
    judge_cfg = MagicMock()
    judge_cfg.background_tool = "claude"
    judge_cfg.memory_judge_model = "haiku"
    judge_cfg.agent_timeout = 60
    judge = MemoryJudge(config=judge_cfg, runner=runner, threshold=0.7)

    await record_tribal_knowledge(
        principle="Background loops must rehydrate state on restart, not reset.",
        rationale="A 2025 incident wiped pending work when a loop reset its dedup set.",
        failure_mode="Pending work is reprocessed or lost on every deploy.",
        scope="src/*_loop.py",
        source="test",
        config=cfg,
        judge=judge,
    )

    items_path = cfg.data_path("memory", "items.jsonl")
    assert items_path.exists()
    lines = items_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert "rehydrate state" in record["principle"]
    assert record["scope"] == "src/*_loop.py"


@pytest.mark.asyncio
async def test_record_tribal_knowledge_rejects_via_judge(tmp_path):
    from memory_judge import MemoryJudge
    from tribal_recorder import record_tribal_knowledge

    cfg = _fake_config(tmp_path)
    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='{"score": 0.1, "verdict": "reject", "reason": "trivial"}'
    )
    judge_cfg = MagicMock()
    judge_cfg.background_tool = "claude"
    judge_cfg.memory_judge_model = "haiku"
    judge_cfg.agent_timeout = 60
    judge = MemoryJudge(config=judge_cfg, runner=runner, threshold=0.7)

    await record_tribal_knowledge(
        principle="A trivial implementation detail not worth keeping forever.",
        rationale="Just changed a variable name in one place.",
        failure_mode="Nothing meaningful happens if ignored.",
        scope="src/whatever.py",
        source="test",
        config=cfg,
        judge=judge,
    )

    items_path = cfg.data_path("memory", "items.jsonl")
    rejected_path = cfg.data_path("memory", "rejected.jsonl")
    assert not items_path.exists() or items_path.read_text() == ""
    assert rejected_path.exists()
