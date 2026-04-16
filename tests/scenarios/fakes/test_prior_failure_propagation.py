"""FakeLLM agents runner must capture prior_failure so tests can assert it."""

from __future__ import annotations

from pathlib import Path

from tests.scenarios.fakes.fake_llm import FakeLLM


async def test_prior_failure_is_captured() -> None:
    llm = FakeLLM()

    class _Task:
        id = 42

    await llm.agents.run(
        _Task(),
        worktree_path=Path("/tmp/wt"),
        branch="b",
        prior_failure="build failed: missing dep",
    )

    captured = llm.agents.prior_failures_seen_for(42)
    assert captured == ["build failed: missing dep"]


async def test_prior_failure_defaults_to_empty_list() -> None:
    llm = FakeLLM()
    assert llm.agents.prior_failures_seen_for(999) == []


async def test_multiple_calls_accumulate_prior_failures() -> None:
    llm = FakeLLM()

    class _Task:
        id = 7

    await llm.agents.run(
        _Task(), worktree_path=Path("/tmp"), branch="b", prior_failure="first"
    )
    await llm.agents.run(
        _Task(), worktree_path=Path("/tmp"), branch="b", prior_failure="second"
    )
    assert llm.agents.prior_failures_seen_for(7) == ["first", "second"]
