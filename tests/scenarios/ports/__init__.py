"""Test-side Port protocols for the scenario framework.

Production ports live in ``src/ports.py``. This module re-exports the ones
scenario tests touch and adds test-only ports that have no production twin.
"""

from __future__ import annotations

from ports import (  # noqa: F401 — production port re-exports
    AgentPort,
    IssueFetcherPort,
    IssueStorePort,
    PRPort,
    StateBackendPort,
    WorkspacePort,
)
from tests.scenarios.ports.clock_port import ClockPort
from tests.scenarios.ports.docker_port import DockerPort
from tests.scenarios.ports.fs_port import FSLock, FSPort
from tests.scenarios.ports.git_port import GitPort
from tests.scenarios.ports.hindsight_port import HindsightPort
from tests.scenarios.ports.http_port import HTTPPort, HTTPResponse
from tests.scenarios.ports.llm_port import (
    AgentRunnerPort,
    LLMPort,
    PlannerRunnerPort,
    ReviewRunnerPort,
    TriageRunnerPort,
)
from tests.scenarios.ports.sentry_port import SentryPort

__all__ = [
    "AgentPort",
    "AgentRunnerPort",
    "ClockPort",
    "DockerPort",
    "FSLock",
    "FSPort",
    "GitPort",
    "HindsightPort",
    "HTTPPort",
    "HTTPResponse",
    "IssueFetcherPort",
    "IssueStorePort",
    "LLMPort",
    "PRPort",
    "PlannerRunnerPort",
    "ReviewRunnerPort",
    "SentryPort",
    "StateBackendPort",
    "TriageRunnerPort",
    "WorkspacePort",
]
