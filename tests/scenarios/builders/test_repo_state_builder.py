"""RepoStateBuilder unit tests — composites issues + PRs."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.pr import PRBuilder
from tests.scenarios.builders.repo import RepoStateBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


async def test_with_issues_seeds_all(world: MockWorld) -> None:
    await (
        RepoStateBuilder()
        .with_issues(
            [
                IssueBuilder().numbered(1).titled("A"),
                IssueBuilder().numbered(2).titled("B"),
            ]
        )
        .at(world)
    )
    assert world.github.issue(1).title == "A"
    assert world.github.issue(2).title == "B"


async def test_with_prs_seeds_all(world: MockWorld) -> None:
    await (
        RepoStateBuilder()
        .with_issues(
            [
                IssueBuilder().numbered(10),
                IssueBuilder().numbered(11),
            ]
        )
        .with_prs(
            [
                PRBuilder().for_issue(10).with_ci_status("failure"),
                PRBuilder().for_issue(11).with_ci_status("success"),
            ]
        )
        .at(world)
    )
    pr10 = world.github.pr_for_issue(10)
    pr11 = world.github.pr_for_issue(11)
    assert pr10 is not None and pr11 is not None
    assert pr10.ci_status == "failure"
    assert pr11.ci_status == "success"


def test_chaining_is_immutable() -> None:
    a = RepoStateBuilder().with_issues([IssueBuilder().numbered(1)])
    b = a.with_issues([IssueBuilder().numbered(2)])
    assert len(a._issues) == 1 and a._issues[0]._number == 1
    assert len(b._issues) == 1 and b._issues[0]._number == 2
