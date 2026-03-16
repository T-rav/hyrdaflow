"""Tests for dashboard — init."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus
from tests.conftest import make_orchestrator_mock

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for HydraFlowDashboard.__init__."""

    def test_stores_config(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._config is config

    def test_stores_event_bus(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._bus is event_bus

    def test_stores_state(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._state is state

    def test_stores_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)

        assert dashboard._orchestrator is orch

    def test_orchestrator_defaults_to_none(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._orchestrator is None

    def test_server_task_starts_as_none(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._server_task is None

    def test_app_starts_as_none(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._app is None

    def test_run_task_starts_as_none(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        assert dashboard._run_task is None


# ---------------------------------------------------------------------------
# POST /api/control/start
# ---------------------------------------------------------------------------


class TestControlStartEndpoint:
    """Tests for the POST /api/control/start route."""

    def test_start_returns_started(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)

        with patch("orchestrator.HydraFlowOrchestrator") as MockOrch:
            mock_orch_inst = AsyncMock()
            mock_orch_inst.run = AsyncMock(return_value=None)
            mock_orch_inst.running = False
            mock_orch_inst.stop = MagicMock()
            MockOrch.return_value = mock_orch_inst

            response = client.post("/api/control/start")

        assert response.status_code == 200
        assert response.json()["status"] == "started"

    def test_start_returns_409_when_already_running(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True, run_status="running")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/control/start")

        assert response.status_code == 409
        assert "already running" in response.json()["error"]


# ---------------------------------------------------------------------------
# POST /api/control/stop
# ---------------------------------------------------------------------------


class TestControlStopEndpoint:
    """Tests for the POST /api/control/stop route."""

    def test_stop_returns_400_when_not_running(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/control/stop")

        assert response.status_code == 400
        assert "not running" in response.json()["error"]

    def test_stop_returns_stopping_when_running(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True, run_status="running")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/control/stop")

        assert response.status_code == 200
        assert response.json()["status"] == "stopping"
        orch.request_stop.assert_called_once()

    def test_stop_returns_400_when_orchestrator_not_running(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=False, run_status="idle")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/control/stop")

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/control/status
# ---------------------------------------------------------------------------


class TestControlStatusEndpoint:
    """Tests for the GET /api/control/status route."""

    def test_status_returns_idle_when_no_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/control/status")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "idle"

    def test_status_returns_running_when_orchestrator_active(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True, run_status="running")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/control/status")

        assert response.status_code == 200
        assert response.json()["status"] == "running"

    def test_status_includes_app_version(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from app_version import get_app_version
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/control/status")

        assert response.status_code == 200
        body = response.json()
        assert body["config"]["app_version"] == get_app_version()

    _STATUS_CONFIG_FIELDS = [
        "repo",
        "ready_label",
        "find_label",
        "planner_label",
        "review_label",
        "hitl_label",
        "hitl_active_label",
        "fixed_label",
        "max_planners",
        "max_reviewers",
        "max_hitl_workers",
    ]

    @pytest.mark.parametrize("config_field", _STATUS_CONFIG_FIELDS)
    def test_status_includes_config_info(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state,
        config_field: str,
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/control/status")

        body = response.json()
        assert body["config"][config_field] == getattr(config, config_field)
