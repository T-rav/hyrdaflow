"""Property-based invariant tests.

Each test draws 50-100 generated world states and asserts a framework-level
invariant. Failures reveal builder or fake bugs that single hand-rolled
scenarios wouldn't catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.builders.pr import PRBuilder
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.fuzz.strategies import (
    issue_builders,
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


@given(num=st.integers(min_value=1, max_value=9_999))
@_DEFAULT_SETTINGS
async def test_pr_builder_links_to_issue(tmp_path: Path, num: int) -> None:
    """For any drawn issue number, seeding its PR produces an issue-linked FakePR."""
    world = MockWorld(tmp_path)
    IssueBuilder().numbered(num).at(world)
    pr = await PRBuilder().for_issue(num).at(world)
    assert pr.issue_number == num


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


_VALID_STAGE_LABELS = [
    "hydraflow-find",
    "hydraflow-triage",
    "hydraflow-plan",
    "hydraflow-ready",
    "hydraflow-review",
    "hydraflow-done",
    "hydraflow-hitl",
]

_VALID_STAGES = ["find", "triage", "plan", "ready", "review", "done", "hitl"]


@given(
    initial=st.sampled_from(_VALID_STAGE_LABELS),
    target=st.sampled_from(_VALID_STAGES),
)
@_DEFAULT_SETTINGS
async def test_fake_github_transition_maintains_single_stage_label(
    initial: str,
    target: str,
) -> None:
    """After any valid transition, the issue carries exactly one stage label."""
    gh = FakeGitHub()
    gh.add_issue(1, "title", "body", labels=[initial, "other-label"])

    await gh.transition(1, target)

    labels = gh.issue(1).labels
    stage_labels = [lbl for lbl in labels if lbl.startswith("hydraflow-")]
    assert len(stage_labels) == 1, f"expected one stage label; got {stage_labels}"


@given(num_prs=st.integers(min_value=1, max_value=10))
@_DEFAULT_SETTINGS
async def test_fake_github_pr_numbers_unique(num_prs: int) -> None:
    """Every create_pr call produces a unique PR number."""
    gh = FakeGitHub()
    seen: set[int] = set()

    for i in range(num_prs):
        gh.add_issue(i + 1, f"title-{i}", "body", labels=["hydraflow-ready"])
        issue_obj = type("_Issue", (), {"number": i + 1})()
        pr_info = await gh.create_pr(issue_obj, f"feat/issue-{i + 1}")
        assert pr_info.number not in seen, (
            f"duplicate PR number {pr_info.number} on iteration {i}"
        )
        seen.add(pr_info.number)
