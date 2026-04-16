"""Latency — adds clock-driven delay to listed methods."""

from __future__ import annotations

from tests.scenarios.behaviors.latency import Latency
from tests.scenarios.fakes.fake_clock import FakeClock
from tests.scenarios.fakes.fake_github import FakeGitHub


async def test_latency_advances_clock() -> None:
    gh = FakeGitHub()
    clock = FakeClock(start=1000.0)
    wrapped = Latency(gh, clock=clock, delay_seconds=0.5, methods=["get_pr_diff"])
    assert clock.now() == 1000.0
    await wrapped.get_pr_diff(1)
    assert clock.now() == 1000.5


async def test_unwatched_method_does_not_advance() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "A", "B")
    clock = FakeClock(start=500.0)
    wrapped = Latency(gh, clock=clock, delay_seconds=0.1, methods=["get_pr_diff"])
    _ = wrapped.issue(1)
    assert clock.now() == 500.0
