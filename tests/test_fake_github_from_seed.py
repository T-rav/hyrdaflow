"""FakeGitHub.from_seed — construct a FakeGitHub from a MockWorldSeed."""

from __future__ import annotations

from mockworld.fakes import FakeGitHub
from mockworld.seed import MockWorldSeed


def test_from_seed_populates_issues() -> None:
    seed = MockWorldSeed(
        issues=[
            {"number": 1, "title": "first", "body": "body1", "labels": ["x"]},
            {"number": 2, "title": "second", "body": "body2", "labels": ["y"]},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert set(gh._issues.keys()) == {1, 2}
    assert gh._issues[1].title == "first"
    assert gh._issues[2].labels == ["y"]


def test_from_seed_populates_prs() -> None:
    seed = MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b", "labels": []}],
        prs=[
            {
                "number": 100,
                "issue_number": 1,
                "branch": "hf/issue-1",
                "ci_status": "pass",
                "merged": False,
                "labels": ["wip"],
            },
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert 100 in gh._prs
    assert gh._prs[100].branch == "hf/issue-1"
    assert "wip" in gh._prs[100].labels


def test_from_seed_handles_empty_seed() -> None:
    gh = FakeGitHub.from_seed(MockWorldSeed())
    assert gh._issues == {}
    assert gh._prs == {}
