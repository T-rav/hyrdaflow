"""Quota — Anthropic credit-exhaustion simulation."""

from __future__ import annotations

import pytest

from tests.scenarios.behaviors.quota import Quota, QuotaExceeded
from tests.scenarios.fakes.fake_llm import FakeLLM


async def test_quota_decrements_on_each_call() -> None:
    llm = FakeLLM()
    wrapped = Quota(llm.agents, budget=2, methods=["run"])
    assert wrapped.remaining == 2

    class _Task:
        id = 1

    await wrapped.run(_Task(), worktree_path="/tmp", branch="b")
    assert wrapped.remaining == 1


async def test_quota_exhausted_raises() -> None:
    llm = FakeLLM()
    wrapped = Quota(llm.agents, budget=1, methods=["run"])

    class _Task:
        id = 1

    await wrapped.run(_Task(), worktree_path="/tmp", branch="b")
    with pytest.raises(QuotaExceeded, match="resume_at"):
        await wrapped.run(_Task(), worktree_path="/tmp", branch="b")
