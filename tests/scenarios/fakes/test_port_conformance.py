"""Conformance tests — each fake must satisfy its Port protocol.

Uses runtime_checkable isinstance checks. If a fake drifts from its port,
this test flags it immediately.
"""

from __future__ import annotations

from pathlib import Path

from events import EventBus
from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.fakes.fake_sentry import FakeSentry
from tests.scenarios.ports import (
    ClockPort,
    LLMPort,
    PRPort,
    SentryPort,
)


def test_fake_github_satisfies_pr_port() -> None:
    assert isinstance(FakeGitHub(), PRPort)


def test_fake_llm_satisfies_llm_port() -> None:
    assert isinstance(FakeLLM(), LLMPort)


def test_fake_sentry_satisfies_sentry_port() -> None:
    assert isinstance(FakeSentry(), SentryPort)


def test_fake_clock_satisfies_clock_port() -> None:
    import time

    assert isinstance(FakeClock(start=time.time()), ClockPort)


def test_fake_subprocess_runner_satisfies_subprocess_runner() -> None:
    from execution import SubprocessRunner
    from mockworld.fakes.fake_docker import FakeDocker
    from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner

    assert isinstance(FakeSubprocessRunner(FakeDocker()), SubprocessRunner)


def test_real_agent_runner_constructs_via_factory(tmp_path: Path) -> None:
    """Boot smoke — if this fails, AgentRunner API drifted from scenarios."""
    from mockworld.fakes.fake_docker import FakeDocker
    from tests.scenarios.helpers.agent_runner_factory import build_real_agent_runner

    runner = build_real_agent_runner(
        docker=FakeDocker(),
        event_bus=EventBus(),
        tmp_path=tmp_path,
    )
    # We only need the methods that implement_phase actually calls
    assert hasattr(runner, "run")
    assert hasattr(runner, "set_tracing_context")
    assert hasattr(runner, "clear_tracing_context")
