"""Tests for service_registry.py — ServiceRegistry and build_services factory."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from events import EventBus
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

    def test_store_uses_fetcher(self, config: HydraFlowConfig) -> None:
        """IssueStore should be initialized with the fetcher."""
        bus = EventBus()
        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()
        callbacks = _make_callbacks()

        registry = build_services(config, bus, state, stop_event, callbacks)

        assert registry.store._fetcher is registry.fetcher
