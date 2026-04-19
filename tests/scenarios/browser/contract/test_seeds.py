"""Tests that seed helpers populate MockWorld's state deterministically."""

from __future__ import annotations

import pytest

from tests.scenarios.browser.contract.seeds import (
    seed_empty_pipeline,
    seed_populated_pipeline,
)
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_browser


async def test_populated_seed_adds_expected_issues(tmp_path):
    world = MockWorld(tmp_path, clock_start="2025-06-15T12:00:00Z")
    seed_populated_pipeline(world)

    # Mirrors the current JS seedPipelineIssues values
    assert world.github.issue(201).title == "Add rate limiting to API"
    assert world.github.issue(208).title == "Migrate legacy DB schema"
    assert world.github.pr_for_issue(207) is not None
    assert world.github.pr_for_issue(190).merged is True


async def test_empty_seed_leaves_world_idle(tmp_path):
    world = MockWorld(tmp_path, clock_start="2025-06-15T12:00:00Z")
    seed_empty_pipeline(world)

    # Accessing a non-existent issue raises KeyError
    with pytest.raises(KeyError):
        world.github.issue(201)
    # No PRs seeded
    assert world.github.pr_for_issue(207) is None
