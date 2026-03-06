"""Tests for service_registry.py — ServiceRegistry and build_services factory."""

from __future__ import annotations

import asyncio
import sys
from operator import attrgetter
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from unittest.mock import patch

from events import EventBus, EventType, HydraFlowEvent
from service_registry import OrchestratorCallbacks, ServiceRegistry, build_services
from state import StateTracker


def _make_callbacks() -> OrchestratorCallbacks:
    """Create a stub OrchestratorCallbacks."""
    return OrchestratorCallbacks(
        sync_active_issue_numbers=lambda: None,
        update_bg_worker_status=lambda *args, **kwargs: None,
        is_bg_worker_enabled=lambda name: True,
        sleep_or_stop=AsyncMock(),
        get_bg_worker_interval=lambda name: 60,
    )


class TestBuildServices:
    """Tests for the build_services factory function."""

    def test_returns_service_registry(self, config: HydraFlowConfig) -> None:
        """build_services should return a ServiceRegistry instance."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert isinstance(registry, ServiceRegistry)

    def test_all_fields_are_set(self, config: HydraFlowConfig) -> None:
        """All ServiceRegistry fields should be non-None."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        for field_name in ServiceRegistry.__dataclass_fields__:
            assert getattr(registry, field_name) is not None, f"{field_name} is None"

    def test_agents_runner_is_shared(self, config: HydraFlowConfig) -> None:
        """Agents, planners, reviewers, and HITL runner should share the subprocess runner."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert registry.agents._runner is registry.subprocess_runner
        assert registry.planners._runner is registry.subprocess_runner
        assert registry.reviewers._runner is registry.subprocess_runner
        # Verify the runner type matches the expected execution mode
        from docker_runner import get_docker_runner

        runner = get_docker_runner(config)
        assert type(registry.subprocess_runner) is type(runner)

    def test_store_uses_fetcher(self, config: HydraFlowConfig) -> None:
        """IssueStore should be initialized with the fetcher."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        from issue_fetcher import GitHubTaskFetcher

        assert isinstance(registry.store._fetcher, GitHubTaskFetcher)
        assert registry.store._fetcher._fetcher is registry.fetcher

    def test_uses_get_docker_runner(self, config: HydraFlowConfig) -> None:
        """build_services should use get_docker_runner to create the subprocess runner."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        with patch("service_registry.get_docker_runner") as mock_factory:
            from execution import get_default_runner

            mock_factory.return_value = get_default_runner()
            build_services(config, bus, state, stop_event, callbacks)

        mock_factory.assert_called_once_with(config)


class TestServiceRegistryWiring:
    """Integration checks for ServiceRegistry wiring and shared dependencies."""

    _BUS_TARGETS = [
        ("triage phase", attrgetter("triager._bus")),
        ("plan phase", attrgetter("planner_phase._bus")),
        ("review phase", attrgetter("reviewer._bus")),
        ("hitl phase", attrgetter("hitl_phase._bus")),
        ("agents runner", attrgetter("agents._bus")),
        ("planners runner", attrgetter("planners._bus")),
        ("reviewers runner", attrgetter("reviewers._bus")),
        ("hitl runner", attrgetter("hitl_runner._bus")),
        ("triage runner", attrgetter("triage._bus")),
        ("pr manager", attrgetter("prs._bus")),
        ("issue store", attrgetter("store._bus")),
        # Note: ImplementPhase is intentionally absent — it does not accept event_bus
        # in its constructor; events flow through its sub-runners (agents._bus, etc.).
    ]
    _STATE_TARGETS = [
        ("triage phase", attrgetter("triager._state")),
        ("plan phase", attrgetter("planner_phase._state")),
        ("implement phase", attrgetter("implementer._state")),
        ("review phase", attrgetter("reviewer._state")),
        ("hitl phase", attrgetter("hitl_phase._state")),
    ]
    _STOP_EVENT_TARGETS = [
        ("triage phase", attrgetter("triager._stop_event")),
        ("plan phase", attrgetter("planner_phase._stop_event")),
        ("implement phase", attrgetter("implementer._stop_event")),
        ("review phase", attrgetter("reviewer._stop_event")),
        ("hitl phase", attrgetter("hitl_phase._stop_event")),
    ]
    # Explicit list of phase objects (not runners) that can publish on the shared bus.
    # Kept separate from _BUS_TARGETS to avoid a fragile index-based slice.
    _PHASE_BUS_PUBLISHERS = [
        ("triage phase", attrgetter("triager._bus")),
        ("plan phase", attrgetter("planner_phase._bus")),
        ("review phase", attrgetter("reviewer._bus")),
        ("hitl phase", attrgetter("hitl_phase._bus")),
    ]

    @staticmethod
    def _build_registry(
        config: HydraFlowConfig,
    ) -> tuple[ServiceRegistry, EventBus, StateTracker, asyncio.Event]:
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()
        registry = build_services(config, bus, state, stop_event, callbacks)
        return registry, bus, state, stop_event

    def test_phases_share_event_bus(self, config: HydraFlowConfig) -> None:
        registry, bus, _, _ = self._build_registry(config)

        for label, getter in self._BUS_TARGETS:
            assert getter(registry) is bus, (
                f"{label} is not using the shared EventBus instance"
            )

    def test_phases_share_state_tracker(self, config: HydraFlowConfig) -> None:
        registry, _, state, _ = self._build_registry(config)

        for label, getter in self._STATE_TARGETS:
            assert getter(registry) is state, f"{label} is not sharing StateTracker"

    def test_phases_share_stop_event(self, config: HydraFlowConfig) -> None:
        registry, _, _, stop_event = self._build_registry(config)

        for label, getter in self._STOP_EVENT_TARGETS:
            assert getter(registry) is stop_event, f"{label} not wired to stop_event"

    async def test_event_bus_propagation(self, config: HydraFlowConfig) -> None:
        registry, bus, _, _ = self._build_registry(config)
        queue = bus.subscribe()

        try:
            for label, getter in self._PHASE_BUS_PUBLISHERS:
                event = HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT, data={"source": label}
                )
                await getter(registry).publish(event)

                received = await asyncio.wait_for(queue.get(), timeout=1)
                assert received is event, f"{label} did not publish via shared EventBus"
        finally:
            bus.unsubscribe(queue)
