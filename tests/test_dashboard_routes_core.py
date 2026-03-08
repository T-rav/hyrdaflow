"""Tests for dashboard_routes.py — core route setup, SPA, WebSocket, intent, report."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


class TestCreateRouter:
    """Tests for create_router factory function."""

    def test_create_router_returns_api_router(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from fastapi import APIRouter

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

        assert isinstance(router, APIRouter)

    def test_router_registers_expected_routes(
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

        expected_paths = {
            "/",
            "/api/state",
            "/api/stats",
            "/api/queue",
            "/api/pipeline",
            "/api/metrics",
            "/api/metrics/github",
            "/api/issues/history",
            "/api/events",
            "/api/prs",
            "/api/hitl",
            "/api/human-input",
            "/api/human-input/{issue_number}",
            "/api/control/start",
            "/api/control/stop",
            "/api/control/status",
            "/api/control/config",
            "/api/control/bg-worker",
            "/api/system/workers",
            "/api/hitl/{issue_number}/correct",
            "/api/hitl/{issue_number}/skip",
            "/api/hitl/{issue_number}/close",
            "/api/issues/outcomes",
            "/api/timeline",
            "/api/timeline/issue/{issue_num}",
            "/api/intent",
            "/api/report",
            "/api/review-insights",
            "/api/retrospectives",
            "/api/memories",
            "/api/sessions",
            "/api/sessions/{session_id}",
            "/api/request-changes",
            "/api/runs",
            "/api/runs/{issue_number}",
            "/api/runs/{issue_number}/{timestamp}/{filename}",
            "/api/runtimes",
            "/api/runtimes/{slug}",
            "/api/runtimes/{slug}/start",
            "/api/runtimes/{slug}/stop",
            "/api/crates",
            "/api/crates/active",
            "/api/crates/{crate_number}",
            "/api/crates/{crate_number}/items",
            "/api/epics",
            "/api/epics/{epic_number}",
            "/api/epics/{epic_number}/release",
            "/ws",
            "/{path:path}",
        }

        assert expected_paths.issubset(paths)

        # Verify approve-memory route is registered
        assert "/api/hitl/{issue_number}/approve-memory" in paths


class TestStartOrchestratorBroadcast:
    """Tests that /api/control/start broadcasts orchestrator_status running event."""

    @pytest.mark.asyncio
    async def test_start_publishes_orchestrator_status_running(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """POST /api/control/start should publish orchestrator_status with running."""
        from unittest.mock import MagicMock as SyncMock

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)

        def set_orch(o):
            pass

        def set_task(t):
            t.cancel()  # Cancel the actual run task to avoid side effects

        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=set_orch,
            set_run_task=set_task,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

        # Subscribe to the event bus before calling start
        queue = event_bus.subscribe()

        # Find and call the start endpoint
        start_endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/control/start"
                and hasattr(route, "endpoint")
            ):
                start_endpoint = route.endpoint
                break

        assert start_endpoint is not None

        # Mock the orchestrator module to prevent actual orchestrator creation
        mock_orch = SyncMock()
        mock_orch.running = False
        mock_orch.run = AsyncMock(return_value=None)

        import orchestrator as orch_module

        original_class = orch_module.HydraFlowOrchestrator
        orch_module.HydraFlowOrchestrator = lambda *a, **kw: mock_orch  # type: ignore[assignment,misc]
        try:
            response = await start_endpoint()
        finally:
            orch_module.HydraFlowOrchestrator = original_class  # type: ignore[assignment]

        import json

        data = json.loads(response.body)
        assert data["status"] == "started"

        # Verify that orchestrator_status event was published with reset flag
        event = queue.get_nowait()
        assert event.type == "orchestrator_status"
        assert event.data["status"] == "running"
        assert event.data["reset"] is True


# ---------------------------------------------------------------------------
# POST /api/intent
# ---------------------------------------------------------------------------


class TestSubmitIntentEndpoint:
    """Tests for POST /api/intent."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        ), pr_mgr

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
    async def test_submit_intent_creates_issue(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import IntentRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(return_value=123)  # type: ignore[method-assign]
        endpoint = self._find_endpoint(router, "/api/intent")
        request = IntentRequest(text="Add a new feature for dark mode")
        response = await endpoint(request)
        data = json.loads(response.body)
        assert data["issue_number"] == 123
        assert data["title"] == "Add a new feature for dark mode"

    @pytest.mark.asyncio
    async def test_submit_intent_returns_error_on_failure(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from models import IntentRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(return_value=0)  # type: ignore[method-assign]
        endpoint = self._find_endpoint(router, "/api/intent")
        request = IntentRequest(text="Add something")
        response = await endpoint(request)
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/report
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /api/report
# ---------------------------------------------------------------------------


class TestSubmitReportEndpoint:
    """Tests for POST /api/report."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        ), pr_mgr

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
    async def test_submit_report_queues_report(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import ReportIssueRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/report")
        request = ReportIssueRequest(description="Button is broken")
        response = await endpoint(request)
        data = json.loads(response.body)
        assert data["issue_number"] == 0
        assert data["title"] == "[Bug Report] Button is broken"
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_submit_report_enqueues_in_state(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from models import ReportIssueRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/report")
        request = ReportIssueRequest(
            description="UI glitch",
            screenshot_base64="iVBORw0KGgo=",
            environment={"source": "dashboard"},
        )
        await endpoint(request)
        reports = state.get_pending_reports()
        assert len(reports) == 1
        assert reports[0].description == "UI glitch"
        assert reports[0].screenshot_base64 == "iVBORw0KGgo="
        assert reports[0].environment["source"] == "dashboard"


# ---------------------------------------------------------------------------
# GET /api/human-input and POST /api/human-input/{issue_number}
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SPA endpoints: / and /{path:path}
# ---------------------------------------------------------------------------


class TestSPAEndpoints:
    """Tests for SPA serving endpoints."""

    def _make_router(
        self, config, event_bus, state, tmp_path, ui_dist=None, template_dir=None
    ):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=ui_dist or (tmp_path / "no-dist"),
            template_dir=template_dir or (tmp_path / "no-templates"),
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
    async def test_index_returns_placeholder_when_no_dist(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/")
        response = await endpoint()
        assert "HydraFlow Dashboard" in response.body.decode()

    @pytest.mark.asyncio
    async def test_index_serves_react_dist(
        self, config, event_bus, state, tmp_path
    ) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html>React App</html>")
        router = self._make_router(config, event_bus, state, tmp_path, ui_dist=dist_dir)
        endpoint = self._find_endpoint(router, "/")
        response = await endpoint()
        assert "React App" in response.body.decode()

    @pytest.mark.asyncio
    async def test_spa_catchall_returns_404_for_api_paths(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/{path:path}")
        response = await endpoint("api/nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket /ws
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# WebSocket /ws
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    """Tests for WebSocket /ws endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
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

    def test_websocket_route_is_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/ws" in paths

    @pytest.mark.asyncio
    async def test_websocket_accepts_and_sends_history(
        self, config, event_bus: EventBus, state, tmp_path
    ) -> None:
        from fastapi import WebSocket
        from fastapi.websockets import WebSocketDisconnect

        from tests.conftest import EventFactory

        # Publish an event before connecting
        await event_bus.publish(EventFactory.create(data={"init": True}))

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/ws":
                endpoint = route.endpoint
                break
        assert endpoint is not None

        # Create a mock WebSocket
        mock_ws = AsyncMock(spec=WebSocket)
        sent_texts: list[str] = []
        mock_ws.send_text = AsyncMock(side_effect=sent_texts.append)

        # After sending history, simulate disconnect on live event read
        async def get_then_disconnect():
            raise WebSocketDisconnect()

        # We need to mock the subscription context manager
        import asyncio

        q: asyncio.Queue = asyncio.Queue()
        q.get = AsyncMock(side_effect=WebSocketDisconnect)  # type: ignore[method-assign]

        with patch.object(event_bus, "subscription") as mock_sub:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=q)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_sub.return_value = mock_ctx

            await endpoint(mock_ws)

        mock_ws.accept.assert_called_once()
        # At least one history event should have been sent
        assert len(sent_texts) >= 1


# ---------------------------------------------------------------------------
# Repo-scoped API contract tests
# ---------------------------------------------------------------------------


class TestResolveRuntime:
    """Tests for the _resolve_runtime helper inside create_router."""

    def _make_router_with_registry(self, config, event_bus, state, tmp_path, registry):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
            registry=registry,
        )

    @pytest.mark.asyncio
    async def test_state_endpoint_without_repo_param_uses_default(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """GET /api/state with no repo param returns default state."""
        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=None
        )
        ep = next(r for r in router.routes if getattr(r, "path", "") == "/api/state")
        resp = await ep.endpoint()
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_state_endpoint_with_unknown_repo_raises(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """GET /api/state?repo=unknown should raise ValueError."""
        mock_registry = MagicMock()
        mock_registry.get.return_value = None  # Unknown repo
        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(r for r in router.routes if getattr(r, "path", "") == "/api/state")
        with pytest.raises(ValueError, match="Unknown repo"):
            await ep.endpoint(repo="unknown-slug")

    @pytest.mark.asyncio
    async def test_state_endpoint_with_valid_repo_uses_runtime(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """GET /api/state?repo=slug should use the runtime's state."""
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {"repo_state": True}

        mock_runtime = MagicMock()
        mock_runtime.config = config
        mock_runtime.state = mock_state
        mock_runtime.event_bus = event_bus
        mock_runtime.orchestrator = None

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_runtime

        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(r for r in router.routes if getattr(r, "path", "") == "/api/state")
        resp = await ep.endpoint(repo="org-repo")
        assert resp.status_code == 200
        mock_state.to_dict.assert_called_once()


class TestRuntimeLifecycleEndpoints:
    """Tests for /api/runtimes/* lifecycle endpoints."""

    def _make_router_with_registry(self, config, event_bus, state, tmp_path, registry):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
            registry=registry,
        )

    @pytest.mark.asyncio
    async def test_list_runtimes_empty_without_registry(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=None
        )
        ep = next(r for r in router.routes if getattr(r, "path", "") == "/api/runtimes")
        resp = await ep.endpoint()
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_runtimes_returns_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.current_session_id = "sess-1"

        mock_runtime = MagicMock()
        mock_runtime.slug = "org-repo"
        mock_runtime.config.repo = "org/repo"
        mock_runtime.running = True
        mock_runtime.orchestrator = mock_orch

        mock_registry = MagicMock()
        mock_registry.all = [mock_runtime]

        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(r for r in router.routes if getattr(r, "path", "") == "/api/runtimes")
        resp = await ep.endpoint()
        import json

        data = json.loads(resp.body)
        assert len(data["runtimes"]) == 1
        assert data["runtimes"][0]["slug"] == "org-repo"
        assert data["runtimes"][0]["running"] is True

    @pytest.mark.asyncio
    async def test_get_runtime_status_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(
            r
            for r in router.routes
            if getattr(r, "path", "") == "/api/runtimes/{slug}"
            and "GET" in getattr(r, "methods", set())
        )
        resp = await ep.endpoint(slug="nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_start_runtime_already_running(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_runtime = MagicMock()
        mock_runtime.running = True

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_runtime

        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(
            r
            for r in router.routes
            if getattr(r, "path", "") == "/api/runtimes/{slug}/start"
        )
        resp = await ep.endpoint(slug="org-repo")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_stop_runtime_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_runtime = MagicMock()
        mock_runtime.running = True
        mock_runtime.stop = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_runtime

        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(
            r
            for r in router.routes
            if getattr(r, "path", "") == "/api/runtimes/{slug}/stop"
        )
        resp = await ep.endpoint(slug="org-repo")
        assert resp.status_code == 200
        mock_runtime.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_runtime_stops_and_removes(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_runtime = MagicMock()
        mock_runtime.running = True
        mock_runtime.stop = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_runtime

        router = self._make_router_with_registry(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = next(
            r
            for r in router.routes
            if getattr(r, "path", "") == "/api/runtimes/{slug}"
            and "DELETE" in getattr(r, "methods", set())
        )
        resp = await ep.endpoint(slug="org-repo")
        assert resp.status_code == 200
        mock_runtime.stop.assert_awaited_once()
        mock_registry.remove.assert_called_once_with("org-repo")


# ---------------------------------------------------------------------------
# GET /api/review-insights
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /api/control/stop
# ---------------------------------------------------------------------------


class TestStopOrchestratorEndpoint:
    """Tests for POST /api/control/stop."""

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
    async def test_stop_returns_error_when_not_running(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/control/stop")
        response = await endpoint()
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_stop_calls_request_stop(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.running = True
        mock_orch.request_stop = AsyncMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/stop")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["status"] == "stopping"
        mock_orch.request_stop.assert_called_once()


# ---------------------------------------------------------------------------
# SPA endpoints: / and /{path:path}
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/human-input and POST /api/human-input/{issue_number}
# ---------------------------------------------------------------------------


class TestHumanInputEndpoints:
    """Tests for human-input endpoints."""

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
    async def test_get_human_input_empty_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/human-input")
        response = await endpoint()
        data = json.loads(response.body)
        assert data == {}

    @pytest.mark.asyncio
    async def test_get_human_input_returns_requests(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.human_input_requests = {"42": {"question": "Which approach?"}}
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/human-input")
        response = await endpoint()
        data = json.loads(response.body)
        assert "42" in data

    @pytest.mark.asyncio
    async def test_provide_human_input_calls_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.provide_human_input = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/human-input/{issue_number}")
        response = await endpoint(42, {"answer": "Use approach A"})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        mock_orch.provide_human_input.assert_called_once_with(42, "Use approach A")

    @pytest.mark.asyncio
    async def test_provide_human_input_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/human-input/{issue_number}")
        response = await endpoint(42, {"answer": "anything"})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/control/stop
# ---------------------------------------------------------------------------
