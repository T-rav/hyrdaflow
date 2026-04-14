"""PRBuilder unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.pr import PRBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


async def test_pr_for_issue_is_linked(world: MockWorld) -> None:
    issue = IssueBuilder().numbered(1).at(world)
    pr = (
        await PRBuilder()
        .for_issue(issue.number)
        .on_branch("hydraflow/1-test")
        .at(world)
    )
    linked = world.github.pr_for_issue(1)
    assert linked is pr
    assert pr.branch == "hydraflow/1-test"


async def test_ci_status_is_recorded(world: MockWorld) -> None:
    IssueBuilder().numbered(2).at(world)
    pr = await PRBuilder().for_issue(2).with_ci_status("failure").at(world)
    assert pr.ci_status == "failure"


async def test_mergeable_flag_defaults_true(world: MockWorld) -> None:
    IssueBuilder().numbered(3).at(world)
    pr = await PRBuilder().for_issue(3).at(world)
    assert pr.mergeable is True


def test_chaining_is_immutable() -> None:
    a = PRBuilder().for_issue(1)
    b = a.for_issue(2)
    assert a._issue_number == 1
    assert b._issue_number == 2
