"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub + in-memory cache."""

from __future__ import annotations

import pytest

from events import EventBus
from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_store import FakeIssueStore


@pytest.mark.asyncio
async def test_get_returns_issue_from_underlying_github() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    issue = await store.get(1)

    assert issue.number == 1
    assert issue.title == "first"


@pytest.mark.asyncio
async def test_transition_updates_label() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    await store.transition(1, "hydraflow-ready", "hydraflow-planning")

    assert "hydraflow-ready" not in gh._issues[1].labels
    assert "hydraflow-planning" in gh._issues[1].labels
