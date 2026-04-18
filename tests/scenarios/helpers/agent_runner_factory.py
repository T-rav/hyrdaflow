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
    hindsight: FakeHindsight,  # noqa: ARG001 — passed for API symmetry; AgentRunner takes HindsightClient
    event_bus: EventBus,
    tmp_path: Path,  # noqa: ARG001 — reserved for future config needs
) -> AgentRunner:
    """Construct a real AgentRunner wired to FakeSubprocessRunner(docker).

    Hindsight is ``None`` — ``FakeHindsight`` does not satisfy the real
    ``HindsightClient`` type; scenario tests drive hindsight via FakeLLM.
    """
    from agent import AgentRunner  # noqa: PLC0415 — avoid circular import at collection

    config = _build_scenario_config()
    credentials = _build_scenario_credentials()

    return AgentRunner(
        config=config,
        event_bus=event_bus,
        runner=FakeSubprocessRunner(docker),
        hindsight=None,
        credentials=credentials,
        wiki_store=None,
    )


def _build_scenario_config():  # type: ignore[no-untyped-def]
    """Return a minimal valid HydraFlowConfig via ConfigFactory."""
    from tests.helpers import ConfigFactory

    return ConfigFactory.create(repo="T-rav/test-repo")


def _build_scenario_credentials():  # type: ignore[no-untyped-def]
    """Return a minimal valid Credentials for scenarios."""
    from tests.helpers import CredentialsFactory

    return CredentialsFactory.create()
