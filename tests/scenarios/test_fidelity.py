"""Fidelity scenarios — behavior decorators against FakeGitHub / FakeLLM."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_llm import FakeLLM
from tests.scenarios.behaviors import (
    EventuallyConsistent,
    Flaky,
    FlakyError,
    Latency,
    Quota,
    QuotaExceeded,
    RateLimited,
    RateLimitExceeded,
)

pytestmark = pytest.mark.scenario


class TestF1RateLimitBudget:
    async def test_primary_rate_limit_blocks_after_budget(self) -> None:
        gh = RateLimited(FakeGitHub(), budget=2, methods=["get_pr_diff"])
        await gh.get_pr_diff(1)
        await gh.get_pr_diff(1)
        with pytest.raises(RateLimitExceeded):
            await gh.get_pr_diff(1)


class TestF2RateLimitRefill:
    async def test_refill_restores_access(self) -> None:
        gh = RateLimited(FakeGitHub(), budget=1, methods=["get_pr_diff"])
        await gh.get_pr_diff(1)
        with pytest.raises(RateLimitExceeded):
            await gh.get_pr_diff(1)
        gh.refill()
        await gh.get_pr_diff(1)  # ok


class TestF3EventualConsistency:
    async def test_write_is_stale_for_N_reads(self) -> None:
        base = FakeGitHub()
        base.add_issue(1, "A", "body")
        gh = EventuallyConsistent(
            base,
            delay_reads=2,
            watch_writes=["add_labels"],
            watch_reads=["issue"],
        )
        await gh.add_labels(1, ["new"])
        # N stale reads before catch-up
        assert "new" not in gh.issue(1).labels
        assert "new" not in gh.issue(1).labels
        assert "new" in gh.issue(1).labels


class TestF4FlakyRecovery:
    async def test_first_two_fail_third_succeeds(self) -> None:
        gh = Flaky(FakeGitHub(), fail_first=2, methods=["get_pr_diff"])
        for _ in range(2):
            with pytest.raises(FlakyError):
                await gh.get_pr_diff(1)
        assert await gh.get_pr_diff(1) == "diff --git a/x b/x"


class TestF5LatencyAdvancesClock:
    async def test_method_call_advances_fake_clock(self) -> None:
        clock = FakeClock(start=0.0)
        gh = Latency(
            FakeGitHub(), clock=clock, delay_seconds=1.5, methods=["get_pr_diff"]
        )
        await gh.get_pr_diff(1)
        assert clock.now() == 1.5


class TestF6QuotaExhaustion:
    async def test_llm_quota_exhausts_after_budget(self) -> None:
        llm = FakeLLM()
        wrapped = Quota(llm.agents, budget=1, methods=["run"])

        class _Task:
            id = 42

        await wrapped.run(_Task(), worktree_path="/tmp", branch="b")
        with pytest.raises(QuotaExceeded) as exc:
            await wrapped.run(_Task(), worktree_path="/tmp", branch="b")
        assert exc.value.resume_at  # has a resume timestamp


class TestF7StackedRateAndLatency:
    async def test_latency_then_rate_limit(self) -> None:
        # Order: Latency outside, RateLimited inside
        clock = FakeClock(start=0.0)
        gh = Latency(
            RateLimited(FakeGitHub(), budget=2, methods=["get_pr_diff"]),
            clock=clock,
            delay_seconds=0.25,
            methods=["get_pr_diff"],
        )
        await gh.get_pr_diff(1)
        await gh.get_pr_diff(1)
        assert clock.now() == 0.5
        with pytest.raises(RateLimitExceeded):
            await gh.get_pr_diff(1)


class TestF8StackedReverseOrder:
    async def test_rate_limit_then_latency(self) -> None:
        # Order: RateLimited outside, Latency inside
        clock = FakeClock(start=0.0)
        gh = RateLimited(
            Latency(
                FakeGitHub(),
                clock=clock,
                delay_seconds=0.1,
                methods=["get_pr_diff"],
            ),
            budget=1,
            methods=["get_pr_diff"],
        )
        await gh.get_pr_diff(1)
        assert clock.now() == 0.1
        with pytest.raises(RateLimitExceeded):
            await gh.get_pr_diff(1)
        # Latency did NOT advance because outer rate-limit short-circuited.
        assert clock.now() == 0.1


class TestF9UnwatchedPassesThrough:
    async def test_decorators_ignore_unlisted_methods(self) -> None:
        gh = RateLimited(FakeGitHub(), budget=0, methods=["get_pr_diff"])
        gh.add_issue(1, "A", "B")
        assert gh.issue(1).title == "A"


class TestF10FlakyOnlyAffectsListedMethod:
    async def test_flaky_does_not_fail_other_methods(self) -> None:
        base = FakeGitHub()
        base.add_issue(1, "A", "B")
        gh = Flaky(base, fail_first=10, methods=["get_pr_diff"])
        # issue() is unlisted — always succeeds.
        assert gh.issue(1).title == "A"
        # get_pr_diff() fails per budget
        with pytest.raises(FlakyError):
            await gh.get_pr_diff(1)
