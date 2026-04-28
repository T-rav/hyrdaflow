"""MockWorld.apply_seed populates the wired Fakes from a MockWorldSeed."""

from __future__ import annotations

import pytest

from mockworld.seed import MockWorldSeed


@pytest.mark.asyncio
async def test_apply_seed_populates_github_issues(mock_world) -> None:
    seed = MockWorldSeed(
        issues=[
            {"number": 1, "title": "first", "body": "b", "labels": ["x"]},
            {"number": 2, "title": "second", "body": "b", "labels": ["y"]},
        ],
    )

    mock_world.apply_seed(seed)

    assert {i.number for i in mock_world._github._issues.values()} == {1, 2}


@pytest.mark.asyncio
async def test_apply_seed_populates_phase_scripts(mock_world) -> None:
    seed = MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b", "labels": ["x"]}],
        scripts={
            "plan": {1: [{"success": True}]},
        },
    )

    mock_world.apply_seed(seed)

    # FakeLLM has the plan script populated for issue 1.
    assert 1 in mock_world._llm.planners._scripts
