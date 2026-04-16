"""Property-based invariant tests.

Each test draws 50-100 generated world states and asserts a framework-level
invariant. Failures reveal builder or fake bugs that single hand-rolled
scenarios wouldn't catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.pr import PRBuilder
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.fuzz.strategies import (
    issue_builders,
    pr_builders,
    repo_states,
)

pytestmark = pytest.mark.scenario

_DEFAULT_SETTINGS = settings(
    max_examples=50,
    deadline=None,  # disabled — async seeding varies per example
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@given(builder=issue_builders())
@_DEFAULT_SETTINGS
async def test_issue_builder_never_raises(
    tmp_path: Path, builder: IssueBuilder
) -> None:
    """IssueBuilder.at(world) should seed successfully for any valid draw."""
    world = MockWorld(tmp_path)
    issue = builder.at(world)
    # Structural invariants: issue has a number and at least one label
    assert issue.number >= 1
    assert len(issue.labels) >= 1


@given(builder=pr_builders())
@_DEFAULT_SETTINGS
async def test_pr_builder_links_to_issue(tmp_path: Path, builder: PRBuilder) -> None:
    """For any PR draw, seeding its referenced issue then .at() seeds the PR."""
    world = MockWorld(tmp_path)
    issue_num = builder._issue_number
    assert issue_num is not None  # strategy always sets it
    IssueBuilder().numbered(issue_num).at(world)
    pr = await builder.at(world)
    assert pr.issue_number == issue_num


@given(repo=repo_states())
@_DEFAULT_SETTINGS
async def test_repo_state_has_no_orphan_prs(tmp_path: Path, repo) -> None:
    """For any repo state, every PR seeded references a seeded issue.

    Strategy guarantees PRs only point at issues in the same state,
    so this is a tautology — if it EVER fails, the strategy is broken.
    """
    world = MockWorld(tmp_path)
    await repo.at(world)
    # Every PR has a FakePR linked via issue_number
    for pr_builder in repo._prs:
        issue_num = pr_builder._issue_number
        assert world.github.issue(issue_num).number == issue_num


@given(repo=repo_states())
@_DEFAULT_SETTINGS
async def test_repo_state_labels_are_valid(tmp_path: Path, repo) -> None:
    """Every seeded issue carries labels from the valid set."""
    world = MockWorld(tmp_path)
    await repo.at(world)
    valid_labels = {
        "hydraflow-find",
        "hydraflow-ready",
        "hydraflow-planning",
        "hydraflow-implementing",
        "hydraflow-reviewing",
        "hydraflow-done",
        "hydraflow-hitl",
        "hydraflow-ci-failure",
    }
    for issue_builder in repo._issues:
        num = issue_builder._number
        if num is None:
            continue
        got = set(world.github.issue(num).labels)
        assert got.issubset(valid_labels), (
            f"unknown labels on {num}: {got - valid_labels}"
        )
