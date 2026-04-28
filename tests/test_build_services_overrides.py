"""build_services() accepts adapter overrides for sandbox use.

Production callers pass nothing → real adapters constructed.
Sandbox callers pass Fakes → those Fakes appear in the registry.

Task 1.8 of the sandbox-tier scenario testing implementation plan: the
overrides are the injection seam for ``mockworld.sandbox_main`` (Task
1.10) so the sandbox can wire FakeGitHub / FakeWorkspace / FakeIssueStore
/ FakeIssueFetcher into a real ``ServiceRegistry`` without any
conditional in the production code path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from config import HydraFlowConfig
from events import EventBus
from mockworld.fakes import FakeGitHub, FakeIssueFetcher, FakeIssueStore, FakeWorkspace
from service_registry import WorkerRegistryCallbacks, build_services
from state import StateTracker


def _make_callbacks() -> WorkerRegistryCallbacks:
    return WorkerRegistryCallbacks(
        update_status=lambda *args, **kwargs: None,
        is_enabled=lambda name: True,
        get_interval=lambda name: 60,
    )


def test_build_services_uses_real_adapters_when_no_overrides(
    config: HydraFlowConfig,
) -> None:
    """Production behavior: no overrides → real adapter classes."""
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop = asyncio.Event()
    callbacks = _make_callbacks()

    svc = build_services(config, bus, state, stop, callbacks)

    # Real adapters: not Fakes (the marker attribute is class-level on
    # every Fake; absence ⇒ real adapter).
    assert getattr(svc.prs, "_is_fake_adapter", False) is False
    assert getattr(svc.workspaces, "_is_fake_adapter", False) is False
    assert getattr(svc.store, "_is_fake_adapter", False) is False
    assert getattr(svc.fetcher, "_is_fake_adapter", False) is False


def test_build_services_uses_overrides_when_provided(
    config: HydraFlowConfig, tmp_path: Path
) -> None:
    """Sandbox behavior: explicit overrides used unchanged."""
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop = asyncio.Event()
    callbacks = _make_callbacks()

    fake_gh = FakeGitHub()
    fake_ws = FakeWorkspace(base_path=tmp_path / "workspaces")
    fake_fetcher = FakeIssueFetcher(fake_gh)
    fake_store = FakeIssueStore(fake_gh, bus)

    svc = build_services(
        config,
        bus,
        state,
        stop,
        callbacks,
        prs=fake_gh,
        workspaces=fake_ws,
        store=fake_store,
        fetcher=fake_fetcher,
    )

    assert svc.prs is fake_gh
    assert svc.workspaces is fake_ws
    assert svc.store is fake_store
    assert svc.fetcher is fake_fetcher


def test_build_services_uses_runners_override(config: HydraFlowConfig) -> None:
    """Sandbox behavior: explicit ``runners=`` replaces the four LLM-backed runners."""
    from mockworld.fakes import FakeLLM

    bus = EventBus()
    state = StateTracker(config.state_file)
    stop = asyncio.Event()
    callbacks = _make_callbacks()

    fake_llm = FakeLLM()

    svc = build_services(
        config,
        bus,
        state,
        stop,
        callbacks,
        runners=fake_llm,
    )

    assert svc.triage is fake_llm.triage_runner
    assert svc.planners is fake_llm.planners
    assert svc.agents is fake_llm.agents
    assert svc.reviewers is fake_llm.reviewers

    # Phases were constructed AFTER the runners override — they should
    # hold the Fake, not the real runner. This pins the override's
    # placement (lines 357-360 in service_registry.py): if it ever moves
    # to end-of-function, phase wiring would silently regress.
    assert svc.triager._triage is fake_llm.triage_runner
    assert svc.planner_phase._planners is fake_llm.planners
    assert svc.implementer._agents is fake_llm.agents
    assert svc.reviewer._reviewers is fake_llm.reviewers


@pytest.mark.parametrize(
    "override_kwargs,attr,expected_real",
    [
        ({}, "prs", True),
        ({}, "workspaces", True),
        ({}, "store", True),
        ({}, "fetcher", True),
    ],
)
def test_build_services_overrides_default_to_none(
    config: HydraFlowConfig,
    override_kwargs: dict,
    attr: str,
    expected_real: bool,
) -> None:
    """Sanity: when no override passed, real adapter constructed (no-Fake marker)."""
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop = asyncio.Event()
    callbacks = _make_callbacks()

    svc = build_services(config, bus, state, stop, callbacks, **override_kwargs)

    is_fake = getattr(getattr(svc, attr), "_is_fake_adapter", False)
    assert is_fake is (not expected_real)
