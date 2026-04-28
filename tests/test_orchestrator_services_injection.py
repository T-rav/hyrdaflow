"""HydraFlowOrchestrator accepts a pre-built ServiceRegistry.

Task 1.9 of the sandbox-tier scenario testing implementation plan: the
``services=`` kwarg is the second half of the DI plumbing. Together with
``build_services()`` overrides (Task 1.8), the sandbox entrypoint
(Task 1.10) can wire Fakes through both layers without any conditional
in the production code path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from config import HydraFlowConfig
from events import EventBus
from mockworld.fakes import FakeGitHub, FakeWorkspace
from orchestrator import HydraFlowOrchestrator
from service_registry import (
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)


def _make_callbacks() -> WorkerRegistryCallbacks:
    return WorkerRegistryCallbacks(
        update_status=lambda *args, **kwargs: None,
        is_enabled=lambda name: True,
        get_interval=lambda name: 60,
    )


def test_orchestrator_uses_supplied_services(
    config: HydraFlowConfig, tmp_path: Path
) -> None:
    """When ``services=`` is passed, the orchestrator skips its internal build."""
    bus = EventBus()
    state = build_state_tracker(config)
    stop = asyncio.Event()
    callbacks = _make_callbacks()
    fake_gh = FakeGitHub()
    fake_ws = FakeWorkspace(base_path=tmp_path / "workspaces")

    pre_built = build_services(
        config,
        bus,
        state,
        stop,
        callbacks,
        prs=fake_gh,
        workspaces=fake_ws,
    )

    orch = HydraFlowOrchestrator(
        config,
        event_bus=bus,
        state=state,
        services=pre_built,
    )

    # The orchestrator stores what we gave it — not a freshly-built registry.
    assert orch._svc is pre_built
    assert orch._svc.prs is fake_gh
    assert orch._svc.workspaces is fake_ws


def test_orchestrator_builds_services_when_not_supplied(
    config: HydraFlowConfig,
) -> None:
    """When no ``services=`` passed, the orchestrator constructs its own (production path)."""
    bus = EventBus()
    state = build_state_tracker(config)

    orch = HydraFlowOrchestrator(config, event_bus=bus, state=state)

    # Internal build happened — registry exists, with real adapters.
    assert orch._svc is not None
    assert getattr(orch._svc.prs, "_is_fake_adapter", False) is False
    assert getattr(orch._svc.workspaces, "_is_fake_adapter", False) is False
