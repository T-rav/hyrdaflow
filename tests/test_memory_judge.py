"""Tests for the MemoryJudge LLM-backed filing quality gate."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class _FakeResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def _fake_config():
    cfg = MagicMock()
    cfg.background_tool = "claude"
    cfg.memory_judge_model = "haiku"
    cfg.agent_timeout = 60
    return cfg


@pytest.mark.asyncio
async def test_judge_accepts_durable_principle():
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='{"score": 0.85, "verdict": "accept", "reason": "durable invariant"}'
    )

    judge = MemoryJudge(config=_fake_config(), runner=runner, threshold=0.7)
    verdict = await judge.evaluate(
        principle="The main branch is protected; never push directly.",
        rationale="Branch protection enforced after force-push wiped work.",
        failure_mode="Direct pushes rejected; agent loops on retry.",
        scope="all",
    )
    assert verdict.accepted is True
    assert verdict.score == 0.85


@pytest.mark.asyncio
async def test_judge_rejects_implementation_detail():
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='{"score": 0.2, "verdict": "reject", "reason": "single-issue impl detail"}'
    )

    judge = MemoryJudge(config=_fake_config(), runner=runner, threshold=0.7)
    verdict = await judge.evaluate(
        principle="Renamed foo to bar in PR #5741.",
        rationale="To match new naming convention.",
        failure_mode="Tests fail.",
        scope="src/foo.py",
    )
    assert verdict.accepted is False


@pytest.mark.asyncio
async def test_judge_strips_markdown_fenced_json():
    """Claude wraps JSON in ```json...``` fences even when told not to.

    The parser must strip the fence and extract the inner object.
    Real-world failure surfaced during the first end-to-end prune run.
    """
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='```json\n{"score": 0.85, "verdict": "accept", "reason": "real durable rule"}\n```'
    )
    judge = MemoryJudge(config=_fake_config(), runner=runner, threshold=0.7)
    verdict = await judge.evaluate(
        principle="Background loops must rehydrate state on restart, not reset.",
        rationale="A 2025 incident wiped pending work.",
        failure_mode="Pending work is reprocessed or lost on every deploy.",
        scope="src/*_loop.py",
    )
    assert verdict.accepted is True
    assert verdict.score == 0.85
    assert "durable" in verdict.reason


@pytest.mark.asyncio
async def test_judge_extracts_json_from_prose_prelude():
    """If Claude adds a prose prelude before the JSON, extract the object."""
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(
        stdout='Sure, here is my evaluation:\n{"score": 0.2, "verdict": "reject", "reason": "noise"}'
    )
    judge = MemoryJudge(config=_fake_config(), runner=runner, threshold=0.7)
    verdict = await judge.evaluate(
        principle="x" * 20, rationale="x" * 20, failure_mode="x" * 20, scope="x"
    )
    assert verdict.accepted is False
    assert verdict.score == 0.2


@pytest.mark.asyncio
async def test_judge_handles_malformed_response_as_reject():
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.return_value = _FakeResult(stdout="not json at all")

    judge = MemoryJudge(config=_fake_config(), runner=runner, threshold=0.7)
    verdict = await judge.evaluate(
        principle="x" * 20, rationale="x" * 20, failure_mode="x" * 20, scope="x"
    )
    assert verdict.accepted is False
    assert "malformed" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_judge_treats_runner_failure_as_reject():
    from memory_judge import MemoryJudge

    runner = AsyncMock()
    runner.run_simple.side_effect = TimeoutError("boom")

    judge = MemoryJudge(config=_fake_config(), runner=runner, threshold=0.7)
    verdict = await judge.evaluate(
        principle="x" * 20, rationale="x" * 20, failure_mode="x" * 20, scope="x"
    )
    assert verdict.accepted is False
    assert "judge runner error" in verdict.reason.lower()
