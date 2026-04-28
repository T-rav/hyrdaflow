"""Flaky — injects deterministic failures for N of M calls."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from tests.scenarios.behaviors.flaky import Flaky, FlakyError


async def test_first_n_calls_fail_then_succeed() -> None:
    gh = FakeGitHub()
    wrapped = Flaky(gh, fail_first=2, methods=["get_pr_diff"])
    with pytest.raises(FlakyError):
        await wrapped.get_pr_diff(1)
    with pytest.raises(FlakyError):
        await wrapped.get_pr_diff(1)
    # Third call succeeds.
    assert await wrapped.get_pr_diff(1) == "diff --git a/x b/x"


async def test_unwatched_methods_pass_through() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "A", "B")
    wrapped = Flaky(gh, fail_first=5, methods=["get_pr_diff"])
    assert wrapped.issue(1).title == "A"
