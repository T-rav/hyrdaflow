"""Builds a real AgentRunner wired to FakeSubprocessRunner for scenarios."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from events import EventBus
from tests.scenarios.fakes.fake_docker import FakeDocker
from tests.scenarios.fakes.fake_hindsight import FakeHindsight
from tests.scenarios.fakes.fake_subprocess_runner import FakeSubprocessRunner

if TYPE_CHECKING:
    from agent import AgentRunner


def build_real_agent_runner(
    *,
    docker: FakeDocker,
    hindsight: FakeHindsight,  # noqa: ARG001 — accepted for MockWorld API symmetry; AgentRunner receives None because FakeHindsight cannot satisfy HindsightClient
    event_bus: EventBus,
    tmp_path: Path,  # noqa: ARG001 — reserved for future config needs
) -> AgentRunner:
    """Construct a real AgentRunner wired to FakeSubprocessRunner(docker).

    Hindsight is ``None`` — ``FakeHindsight`` does not satisfy the real
    ``HindsightClient`` type; scenario tests drive hindsight via FakeLLM.
    """
    from agent import AgentRunner  # noqa: PLC0415 — avoid circular import at collection
    from tests.helpers import ConfigFactory, CredentialsFactory

    config = ConfigFactory.create()
    credentials = CredentialsFactory.create()

    return AgentRunner(
        config=config,
        event_bus=event_bus,
        runner=FakeSubprocessRunner(docker),
        hindsight=None,
        credentials=credentials,
        wiki_store=None,
    )
