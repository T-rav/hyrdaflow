"""Back-compat shim — Fakes have moved to ``src/mockworld/fakes/``.

This module exists so legacy ``from tests.scenarios.fakes import MockWorld``
(and the other 5 names below) keeps working until ``mock_world.py`` and
``scenario_result.py`` themselves move to ``src/mockworld/`` in a later
task of the sandbox-tier scenario track. Remove this file in the same
commit that relocates ``mock_world.py``.

See ``docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md``
Component 2 (move-table) for the lifecycle.
"""

from __future__ import annotations


def __getattr__(name: str):  # noqa: PLR0911
    if name == "MockWorld":
        from tests.scenarios.fakes.mock_world import MockWorld

        return MockWorld
    if name == "FakeGitHub":
        from mockworld.fakes.fake_github import FakeGitHub

        return FakeGitHub
    if name == "FakeLLM":
        from mockworld.fakes.fake_llm import FakeLLM

        return FakeLLM
    if name == "FakeWorkspace":
        from mockworld.fakes.fake_workspace import FakeWorkspace

        return FakeWorkspace
    if name == "FakeSentry":
        from mockworld.fakes.fake_sentry import FakeSentry

        return FakeSentry
    if name == "FakeClock":
        from mockworld.fakes.fake_clock import FakeClock

        return FakeClock
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
