"""Builds a real AgentRunner wired to FakeSubprocessRunner for scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from events import EventBus
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner

if TYPE_CHECKING:
    from agent import AgentRunner


def build_real_agent_runner(
    *,
    docker: FakeDocker,
    event_bus: EventBus,
    tmp_path: Path,  # noqa: ARG001 — reserved for future config needs
) -> AgentRunner:
    """Construct a real AgentRunner wired to FakeSubprocessRunner(docker)."""
    from agent import AgentRunner  # noqa: PLC0415 — avoid circular import at collection
    from tests.helpers import ConfigFactory, CredentialsFactory

    config = ConfigFactory.create()
    credentials = CredentialsFactory.create()

    return AgentRunner(
        config=config,
        event_bus=event_bus,
        runner=FakeSubprocessRunner(docker),
        credentials=credentials,
        wiki_store=None,
    )
