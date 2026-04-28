"""FakeIssueFetcher — backs IssueFetcherPort from in-memory FakeGitHub state."""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher


@pytest.mark.asyncio
async def test_fetch_returns_issues_seeded_in_github() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    gh.add_issue(2, "second", "body", labels=["hydraflow-ready"])
    fetcher = FakeIssueFetcher(github=gh)

    issues = await fetcher.fetch_open_issues_by_label("hydraflow-ready")

    assert {i.number for i in issues} == {1, 2}


@pytest.mark.asyncio
async def test_fetch_excludes_issues_without_label() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "tagged", "body", labels=["hydraflow-ready"])
    gh.add_issue(2, "untagged", "body", labels=[])
    fetcher = FakeIssueFetcher(github=gh)

    issues = await fetcher.fetch_open_issues_by_label("hydraflow-ready")

    assert [i.number for i in issues] == [1]
