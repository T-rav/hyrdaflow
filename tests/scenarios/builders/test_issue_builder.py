"""IssueBuilder unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scenarios.builders.issue import IssueBuilder
from tests.scenarios.fakes.mock_world import MockWorld


@pytest.fixture
def world(tmp_path: Path) -> MockWorld:
    return MockWorld(tmp_path)


def test_defaults_produce_valid_issue(world: MockWorld) -> None:
    issue = IssueBuilder().at(world)
    assert issue.number >= 1
    assert issue.title != ""
    assert "hydraflow-find" in issue.labels


def test_fluent_chaining_is_immutable() -> None:
    a = IssueBuilder().titled("A")
    b = a.titled("B")
    # Each mutation returns a new builder; original unchanged
    assert a._title == "A"
    assert b._title == "B"


def test_at_world_seeds_github(world: MockWorld) -> None:
    issue = (
        IssueBuilder().numbered(42).titled("Fix X").labeled("hydraflow-ready").at(world)
    )
    stored = world.github.issue(42)
    assert stored.title == "Fix X"
    assert "hydraflow-ready" in stored.labels
    assert issue is stored


def test_auto_numbering_is_unique(world: MockWorld) -> None:
    first = IssueBuilder().at(world)
    second = IssueBuilder().at(world)
    assert first.number != second.number
