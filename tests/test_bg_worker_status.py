"""Tests for background worker status tracking and API endpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType
from models import (
    BackgroundWorkersResponse,
    BackgroundWorkerState,
    BackgroundWorkerStatus,
    BGWorkerHealth,
    MetricsResponse,
)
from state import StateTracker
from tests.conftest import make_state


class TestEventTypes:
    """Verify the new EventType members exist with correct values."""

    def test_memory_sync_event_type(self) -> None:
        assert EventType.MEMORY_SYNC == "memory_sync"

    def test_metrics_update_event_type(self) -> None:
        assert EventType.METRICS_UPDATE == "metrics_update"

    def test_background_worker_status_event_type(self) -> None:
        assert EventType.BACKGROUND_WORKER_STATUS == "background_worker_status"


class TestBackgroundWorkerStatusModel:
    """Verify BackgroundWorkerStatus Pydantic model."""

    def test_default_status_is_disabled(self) -> None:
        status = BackgroundWorkerStatus(name="test", label="Test")
        assert status.status == "disabled"
        assert status.description == ""
        assert status.last_run is None
        assert status.details == {}

    def test_full_model_serializes_correctly(self) -> None:
        status = BackgroundWorkerStatus(
            name="memory_sync",
            label="Memory Manager",
            status=BGWorkerHealth.OK,
            last_run="2026-02-20T10:30:00Z",
            details={"item_count": 12, "digest_chars": 2400},
        )
        data = status.model_dump()
        assert data["name"] == "memory_sync"
        assert data["label"] == "Memory Manager"
        assert data["description"] == ""
        assert data["status"] == "ok"
        assert data["last_run"] == "2026-02-20T10:30:00Z"
        assert data["details"]["item_count"] == 12

    def test_workers_response_model(self) -> None:
        resp = BackgroundWorkersResponse(
            workers=[
                BackgroundWorkerStatus(name="a", label="A", status=BGWorkerHealth.OK),
                BackgroundWorkerStatus(name="b", label="B"),
            ]
        )
        data = resp.model_dump()
        assert len(data["workers"]) == 2
        assert data["workers"][0]["status"] == "ok"
        assert data["workers"][1]["status"] == "disabled"


class TestMetricsResponseModel:
    """Verify MetricsResponse Pydantic model."""

    def test_default_metrics_response(self) -> None:
        resp = MetricsResponse()
        data = resp.model_dump()
        assert data["lifetime"]["issues_completed"] == 0
        assert data["lifetime"]["prs_merged"] == 0
        assert data["rates"] == {}

    def test_metrics_with_rates(self) -> None:
        from models import LifetimeStats

        resp = MetricsResponse(
            lifetime=LifetimeStats(issues_completed=10, prs_merged=8),
            rates={"merge_rate": 0.8},
        )
        data = resp.model_dump()
        assert data["rates"]["merge_rate"] == 0.8


class TestOrchestratorBgWorkerTracking:
    """Verify orchestrator background worker state tracking."""

    def test_update_stores_state(self, config, event_bus: EventBus) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.update_bg_worker_status("memory_sync", "ok", {"item_count": 5})

        states = orch.get_bg_worker_states()
        assert "memory_sync" in states
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["details"]["item_count"] == 5
        assert states["memory_sync"]["last_run"] is not None

    def test_get_returns_copy(self, config, event_bus: EventBus) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.update_bg_worker_status("metrics", "ok")

        states1 = orch.get_bg_worker_states()
        states2 = orch.get_bg_worker_states()
        assert states1 is not states2

    def test_update_replaces_previous(self, config, event_bus: EventBus) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.update_bg_worker_status("memory_sync", "ok", {"count": 1})
        orch.update_bg_worker_status("memory_sync", "error", {"count": 2})

        states = orch.get_bg_worker_states()
        assert states["memory_sync"]["status"] == "error"
        assert states["memory_sync"]["details"]["count"] == 2

    def test_empty_states_initially(self, config, event_bus: EventBus) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.get_bg_worker_states() == {}

    def test_restore_bg_worker_states_from_state_on_startup(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Verify _restore_state hydrates in-memory heartbeat cache from persisted state."""
        from orchestrator import HydraFlowOrchestrator

        # Arrange: pre-populate a StateTracker with a persisted heartbeat
        state = StateTracker(tmp_path / "state.json")
        state.set_bg_worker_state(
            "memory_sync",
            BackgroundWorkerState(
                name="memory_sync",
                status="ok",
                last_run="2026-02-20T10:00:00Z",
                details={"item_count": 5},
            ),
        )

        # Act: create a new orchestrator with the same state, then restore
        orch = HydraFlowOrchestrator(config, event_bus=event_bus, state=state)
        orch._restore_state()

        # Assert: in-memory states reflect persisted data
        states = orch.get_bg_worker_states()
        assert "memory_sync" in states
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["last_run"] == "2026-02-20T10:00:00Z"
        assert states["memory_sync"]["details"]["item_count"] == 5

    def test_backfill_bg_worker_states_from_events(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Verify _restore_state backfills missing workers from event bus history."""
        from events import EventType, HydraFlowEvent
        from orchestrator import HydraFlowOrchestrator

        # Arrange: inject a BACKGROUND_WORKER_STATUS event into the bus history
        event_bus._history.append(
            HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                data={
                    "worker": "memory_sync",
                    "status": "ok",
                    "last_run": "2026-02-20T09:00:00Z",
                    "details": {"item_count": 3},
                },
            )
        )

        # Act: create orchestrator with empty persisted state and restore
        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch._restore_state()

        # Assert: state was backfilled from event history
        states = orch.get_bg_worker_states()
        assert "memory_sync" in states
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["last_run"] == "2026-02-20T09:00:00Z"
        assert states["memory_sync"]["details"]["item_count"] == 3


class TestBgWorkerEnabled:
    """Tests for is_bg_worker_enabled / set_bg_worker_enabled."""

    def test_is_bg_worker_enabled_defaults_to_true(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.is_bg_worker_enabled("memory_sync") is True

    def test_set_bg_worker_enabled_false(self, config, event_bus: EventBus) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.set_bg_worker_enabled("memory_sync", False)
        assert orch.is_bg_worker_enabled("memory_sync") is False

    def test_set_bg_worker_enabled_true_after_disable(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.set_bg_worker_enabled("metrics", False)
        orch.set_bg_worker_enabled("metrics", True)
        assert orch.is_bg_worker_enabled("metrics") is True

    def test_get_bg_worker_states_includes_enabled_flag(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.update_bg_worker_status("memory_sync", "ok")
        orch.set_bg_worker_enabled("memory_sync", False)

        states = orch.get_bg_worker_states()
        assert states["memory_sync"]["enabled"] is False


class TestSystemWorkersEndpoint:
    """Tests for GET /api/system/workers."""

    def _make_router(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
        orch=None,
    ):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)

        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: orch,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _find_endpoint(self, router, path: str):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_returns_all_workers(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data["workers"]) == 11
        names = [w["name"] for w in data["workers"]]
        assert names == [
            "triage",
            "plan",
            "implement",
            "review",
            "memory_sync",
            "retrospective",
            "metrics",
            "review_insights",
            "pipeline_poller",
            "pr_unsticker",
            "report_issue",
        ]
        assert all(
            isinstance(w["description"], str) and w["description"]
            for w in data["workers"]
        )

    @pytest.mark.asyncio
    async def test_returns_disabled_when_no_orchestrator(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path, orch=None)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)
        for w in data["workers"]:
            assert w["status"] == "disabled"
            assert w["last_run"] is None

    @pytest.mark.asyncio
    async def test_returns_tracked_state(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.update_bg_worker_status("memory_sync", "ok", {"item_count": 12})

        router = self._make_router(config, event_bus, state, tmp_path, orch=orch)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        ms = next(w for w in data["workers"] if w["name"] == "memory_sync")
        assert ms["status"] == "ok"
        assert ms["details"]["item_count"] == 12
        assert ms["last_run"] is not None

        # Others should still be disabled
        retro = next(w for w in data["workers"] if w["name"] == "retrospective")
        assert retro["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_returns_persisted_state_without_orchestrator(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        state.set_bg_worker_state(
            "memory_sync",
            BackgroundWorkerState(
                name="memory_sync",
                status="ok",
                last_run="2026-02-20T10:00:00Z",
                details={"count": 7},
            ),
        )

        router = self._make_router(config, event_bus, state, tmp_path, orch=None)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        ms = next(w for w in data["workers"] if w["name"] == "memory_sync")
        assert ms["status"] == "ok"
        assert ms["last_run"] == "2026-02-20T10:00:00Z"
        assert ms["details"]["count"] == 7


class TestMetricsEndpoint:
    """Tests for GET /api/metrics."""

    @pytest.mark.asyncio
    async def test_returns_lifetime_stats(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from dashboard_routes import create_router
        from pr_manager import PRManager

        state.record_issue_completed()
        state.record_issue_completed()
        state.record_pr_merged()

        pr_mgr = PRManager(config, event_bus)
        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

        endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/metrics"
                and hasattr(route, "endpoint")
            ):
                endpoint = route.endpoint
                break

        assert endpoint is not None
        response = await endpoint()
        data = json.loads(response.body)
        assert data["lifetime"]["issues_completed"] == 2
        assert data["lifetime"]["prs_merged"] == 1
        assert data["rates"]["merge_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_returns_empty_rates_when_no_issues(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/metrics":
                endpoint = route.endpoint
                break

        assert endpoint is not None
        response = await endpoint()
        data = json.loads(response.body)
        assert data["rates"] == {}
        assert data["lifetime"]["issues_completed"] == 0


class TestRouteRegistration:
    """Verify new routes are registered."""

    def test_system_workers_and_metrics_routes_registered(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

        paths = {route.path for route in router.routes}
        assert "/api/system/workers" in paths
        assert "/api/metrics" in paths


class TestBackgroundWorkerStatusIntervalFields:
    """Tests for interval_seconds and next_run fields on BackgroundWorkerStatus."""

    def test_default_interval_fields_are_none(self) -> None:
        status = BackgroundWorkerStatus(name="test", label="Test")
        assert status.interval_seconds is None
        assert status.next_run is None

    def test_interval_fields_serialize(self) -> None:
        status = BackgroundWorkerStatus(
            name="memory_sync",
            label="Memory Manager",
            status=BGWorkerHealth.OK,
            interval_seconds=3600,
            next_run="2026-02-20T11:30:00+00:00",
        )
        data = status.model_dump()
        assert data["interval_seconds"] == 3600
        assert data["next_run"] == "2026-02-20T11:30:00+00:00"


class TestSystemWorkersEndpointIntervals:
    """Tests for interval data in GET /api/system/workers."""

    def _make_router(self, config, event_bus, tmp_path, orch=None):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        state = make_state(tmp_path)
        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: orch,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_workers_include_interval_seconds(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        router = self._make_router(config, event_bus, tmp_path, orch=orch)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        ms = next(w for w in data["workers"] if w["name"] == "memory_sync")
        assert ms["interval_seconds"] == config.memory_sync_interval

        metrics = next(w for w in data["workers"] if w["name"] == "metrics")
        assert metrics["interval_seconds"] == config.metrics_sync_interval

        # Pipeline workers should have poll_interval
        triage = next(w for w in data["workers"] if w["name"] == "triage")
        assert triage["interval_seconds"] == config.poll_interval

    @pytest.mark.asyncio
    async def test_workers_include_next_run(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.update_bg_worker_status("memory_sync", "ok", {"count": 1})
        router = self._make_router(config, event_bus, tmp_path, orch=orch)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        ms = next(w for w in data["workers"] if w["name"] == "memory_sync")
        assert ms["next_run"] is not None  # computed from last_run + interval
        assert ms["last_run"] is not None

    @pytest.mark.asyncio
    async def test_pr_unsticker_has_interval_seconds(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        router = self._make_router(config, event_bus, tmp_path, orch=orch)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        unsticker = next(w for w in data["workers"] if w["name"] == "pr_unsticker")
        assert unsticker["interval_seconds"] == config.pr_unstick_interval

    @pytest.mark.asyncio
    async def test_pr_unsticker_has_interval_without_orchestrator(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, tmp_path, orch=None)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        unsticker = next(w for w in data["workers"] if w["name"] == "pr_unsticker")
        assert unsticker["interval_seconds"] == config.pr_unstick_interval

    @pytest.mark.asyncio
    async def test_event_driven_workers_have_no_interval(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        router = self._make_router(config, event_bus, tmp_path, orch=orch)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        retro = next(w for w in data["workers"] if w["name"] == "retrospective")
        assert retro["interval_seconds"] is None

        ri = next(w for w in data["workers"] if w["name"] == "review_insights")
        assert ri["interval_seconds"] is None

    @pytest.mark.asyncio
    async def test_next_run_none_when_no_last_run(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        router = self._make_router(config, event_bus, tmp_path, orch=orch)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)

        ms = next(w for w in data["workers"] if w["name"] == "memory_sync")
        assert ms["next_run"] is None  # no last_run yet


class TestBgWorkerIntervalEndpoint:
    """Tests for POST /api/control/bg-worker/interval endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path, get_orch=None):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=get_orch or (lambda: None),
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _find_endpoint(self, router, path):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_interval_update_requires_fields(
        self, config, event_bus, tmp_path
    ) -> None:
        from unittest.mock import MagicMock

        state = make_state(tmp_path)
        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "memory_sync"})
        assert response.status_code == 400

        response = await endpoint({"interval_seconds": 3600})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_interval_update_rejects_non_editable_worker(
        self, config, event_bus, tmp_path
    ) -> None:
        from unittest.mock import MagicMock

        state = make_state(tmp_path)
        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")

        response = await endpoint({"name": "retrospective", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "not editable" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_update_validates_range(
        self, config, event_bus, tmp_path
    ) -> None:
        from unittest.mock import MagicMock

        state = make_state(tmp_path)
        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")

        # Too low for memory_sync (min 10)
        response = await endpoint({"name": "memory_sync", "interval_seconds": 5})
        assert response.status_code == 422

        # Too high (max 14400)
        response = await endpoint({"name": "memory_sync", "interval_seconds": 99999})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_interval_update_success(self, config, event_bus, tmp_path) -> None:
        from unittest.mock import MagicMock

        state = make_state(tmp_path)
        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")

        response = await endpoint({"name": "memory_sync", "interval_seconds": 7200})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["name"] == "memory_sync"
        assert data["interval_seconds"] == 7200
        mock_orch.set_bg_worker_interval.assert_called_once_with("memory_sync", 7200)

    @pytest.mark.asyncio
    async def test_interval_update_returns_error_without_orchestrator(
        self, config, event_bus, tmp_path
    ) -> None:
        state = make_state(tmp_path)
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "memory_sync", "interval_seconds": 3600})
        assert response.status_code == 400

    def test_interval_route_is_registered(self, config, event_bus, tmp_path) -> None:
        state = make_state(tmp_path)
        router = self._make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker/interval" in paths


class TestOrchestratorIntervalManagement:
    """Tests for set_bg_worker_interval/get_bg_worker_interval."""

    def test_get_returns_config_default_when_no_override(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.get_bg_worker_interval("memory_sync") == config.memory_sync_interval
        assert orch.get_bg_worker_interval("metrics") == config.metrics_sync_interval

    def test_set_stores_and_returns_override(self, config, event_bus: EventBus) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        orch.set_bg_worker_interval("memory_sync", 1800)
        assert orch.get_bg_worker_interval("memory_sync") == 1800

    def test_set_persists_to_state(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        state = StateTracker(tmp_path / "state.json")
        orch = HydraFlowOrchestrator(config, event_bus=event_bus, state=state)
        orch.set_bg_worker_interval("metrics", 600)

        intervals = state.get_worker_intervals()
        assert intervals["metrics"] == 600

    def test_pr_unsticker_returns_pr_unstick_interval(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.get_bg_worker_interval("pr_unsticker") == config.pr_unstick_interval

    def test_pipeline_poller_returns_5_as_default(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.get_bg_worker_interval("pipeline_poller") == 5

    def test_unknown_worker_returns_poll_interval(
        self, config, event_bus: EventBus
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config, event_bus=event_bus)
        assert orch.get_bg_worker_interval("unknown") == config.poll_interval
