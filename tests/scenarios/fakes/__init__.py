"""Stateful fakes for scenario testing.

Fakes are imported lazily so Task 1 can scaffold the directory without
requiring all fake modules to exist yet (they land in Tasks 2-5).
"""

from __future__ import annotations


def __getattr__(name: str):  # noqa: PLR0911
    if name == "MockWorld":
        from tests.scenarios.fakes.mock_world import MockWorld

        return MockWorld
    if name == "FakeGitHub":
        from tests.scenarios.fakes.fake_github import FakeGitHub

        return FakeGitHub
    if name == "FakeLLM":
        from tests.scenarios.fakes.fake_llm import FakeLLM

        return FakeLLM
    if name == "FakeHindsight":
        from tests.scenarios.fakes.fake_hindsight import FakeHindsight

        return FakeHindsight
    if name == "FakeWorkspace":
        from tests.scenarios.fakes.fake_workspace import FakeWorkspace

        return FakeWorkspace
    if name == "FakeSentry":
        from tests.scenarios.fakes.fake_sentry import FakeSentry

        return FakeSentry
    if name == "FakeClock":
        from tests.scenarios.fakes.fake_clock import FakeClock

        return FakeClock
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
