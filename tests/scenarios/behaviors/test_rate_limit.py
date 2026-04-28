"""RateLimited behavior decorator — wraps any port and injects 403 after budget exhaustion."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from tests.scenarios.behaviors.rate_limit import RateLimited, RateLimitExceeded


async def test_under_budget_passes_through() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "x", "y")
    wrapped = RateLimited(gh, budget=5, methods=["get_pr_diff"])
    # Port method still callable; doesn't touch budget for unlisted methods.
    assert wrapped.issue(1).title == "x"


async def test_exceeds_budget_raises() -> None:
    gh = FakeGitHub()
    wrapped = RateLimited(gh, budget=2, methods=["get_pr_diff"])
    await wrapped.get_pr_diff(1)
    await wrapped.get_pr_diff(1)
    with pytest.raises(RateLimitExceeded, match="budget"):
        await wrapped.get_pr_diff(1)


async def test_budget_refill_restores() -> None:
    gh = FakeGitHub()
    wrapped = RateLimited(gh, budget=1, methods=["get_pr_diff"])
    await wrapped.get_pr_diff(1)
    with pytest.raises(RateLimitExceeded):
        await wrapped.get_pr_diff(1)
    wrapped.refill()
    await wrapped.get_pr_diff(1)  # no raise
