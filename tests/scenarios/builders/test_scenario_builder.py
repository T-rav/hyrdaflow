"""ScenarioBuilder unit tests — compose builders, run pipeline, assert."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.repo import RepoStateBuilder
from tests.scenarios.builders.scenario import ScenarioBuilder
from tests.scenarios.builders.trace import AgentTraceBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


async def test_happy_scenario_runs_and_asserts(world: MockWorld) -> None:
    scenario = (
        ScenarioBuilder("test")
        .given(RepoStateBuilder().with_issues([IssueBuilder().numbered(1)]))
        .and_agent(AgentTraceBuilder().happy_path().for_phase("implement").for_issue(1))
        .and_agent(AgentTraceBuilder().happy_path().for_phase("review").for_issue(1))
        .when_pipeline_runs()
        .expect_issue(1)
        .merged()
    )
    await scenario.run(world)
    pr = world.github.pr_for_issue(1)
    assert pr is not None and pr.merged is True


async def test_failed_expectation_raises(world: MockWorld) -> None:
    scenario = (
        ScenarioBuilder("fail")
        .given(RepoStateBuilder().with_issues([IssueBuilder().numbered(1)]))
        .when_pipeline_runs()
        .expect_issue(999)
        .merged()  # issue 999 does not exist
    )
    with pytest.raises(AssertionError, match="999"):
        await scenario.run(world)
