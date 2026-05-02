"""Tests for dashboard — static."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from events import EventBus, EventType, HydraFlowEvent
from tests.conftest import make_orchestrator_mock

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Static file serving and template cleanup (issue #24)
# ---------------------------------------------------------------------------


class TestStaticDashboardJS:
    def test_static_dashboard_js_is_served(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /static/dashboard.js returns 200 when the static dir exists."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        # Create a real static/ dir with a dashboard.js file
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        js_file = static_dir / "dashboard.js"
        js_file.write_text("// dashboard JS")

        dashboard = HydraFlowDashboard(config, event_bus, state, static_dir=static_dir)
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/static/dashboard.js")

        assert response.status_code == 200
        assert "// dashboard JS" in response.text


class TestFallbackTemplateExternalJS:
    def test_fallback_template_references_external_js(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The fallback HTML includes a script tag pointing to /static/dashboard.js."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(
            config,
            event_bus,
            state,
            ui_dist_dir=tmp_path / "no-dist",
            static_dir=tmp_path / "no-static",
        )
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/")

        body = response.text
        assert 'src="/static/dashboard.js"' in body

    def test_fallback_template_has_no_inline_onclick(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The fallback HTML must not contain any inline onclick attributes."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(
            config,
            event_bus,
            state,
            ui_dist_dir=tmp_path / "no-dist",
            static_dir=tmp_path / "no-static",
        )
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/")

        body = response.text
        assert "onclick=" not in body

    def test_fallback_template_has_no_inline_script_block(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The fallback template should not have a large inline <script> block."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(
            config,
            event_bus,
            state,
            ui_dist_dir=tmp_path / "no-dist",
            static_dir=tmp_path / "no-static",
        )
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/")

        body = response.text
        # The template should not have inline JS with WebSocket logic
        assert "new WebSocket" not in body
        assert "function handleEvent" not in body


# ---------------------------------------------------------------------------
# SPA catch-all route (issue #298)
# ---------------------------------------------------------------------------


class TestSPACatchAll:
    def test_spa_catchall_returns_html_for_system_path(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """GET /system should return 200 with HTML (SPA fallback)."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/system")

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_spa_catchall_returns_html_for_arbitrary_path(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """GET /foo/bar should return 200 with HTML (SPA fallback)."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/foo/bar")

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_spa_catchall_does_not_catch_api_routes(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """GET /api/nonexistent should return 404, not SPA HTML."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/nonexistent")

        assert response.status_code == 404

    def test_spa_catchall_does_not_catch_ws_path(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """GET /ws should not return SPA HTML."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/ws")

        # The catch-all guard returns 404 for the bare /ws path,
        # preventing SPA HTML from being served at the WebSocket endpoint.
        assert response.status_code != 200
        assert "text/html" not in response.headers.get("content-type", "")

    def test_spa_catchall_serves_root_level_static_file(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /logo.png should serve the file from ui/dist/ if it exists."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        # Create a fake ui/dist/ with a static file and index.html
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html><body>SPA</body></html>")
        (dist_dir / "logo.png").write_bytes(b"fake-png-data")

        dashboard = HydraFlowDashboard(config, event_bus, state, ui_dist_dir=dist_dir)
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/logo.png")

        assert response.status_code == 200
        assert response.content == b"fake-png-data"

    def test_spa_catchall_html_contains_expected_content(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """The SPA catch-all should serve the same index.html as GET /."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        root_response = client.get("/")
        catchall_response = client.get("/system")

        assert root_response.text == catchall_response.text

    def test_spa_catchall_blocks_symlink_escape(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Symlinks inside ui/dist/ pointing outside must not be served."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        # Create a fake ui/dist/ with index.html
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html><body>SPA</body></html>")

        # Create a sensitive file outside dist_dir
        (tmp_path / "secret.txt").write_text("sensitive data")

        # Create a symlink inside dist_dir pointing outside
        (dist_dir / "escape.txt").symlink_to(tmp_path / "secret.txt")

        dashboard = HydraFlowDashboard(config, event_bus, state, ui_dist_dir=dist_dir)
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/escape.txt")

        # The symlink target resolves outside dist_dir; the is_relative_to
        # jail check must reject it and serve SPA HTML instead.
        assert response.status_code == 200
        assert "sensitive data" not in response.text
        assert "text/html" in response.headers.get("content-type", "")

    def test_spa_catchall_does_not_catch_assets_prefix(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """GET /assets/nonexistent should return 404, not SPA HTML."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/assets/nonexistent.js")

        assert response.status_code == 404

    def test_api_state_still_works_with_catchall(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """Existing API routes must not be affected by the catch-all."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/state")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, dict)


# ---------------------------------------------------------------------------
# GET /api/pipeline/stats
# ---------------------------------------------------------------------------


class TestPipelineStatsRoute:
    def test_pipeline_stats_returns_empty_dict_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/pipeline/stats")

        assert response.json() == {}

    def test_pipeline_stats_returns_valid_pipeline_stats_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard
        from models import PipelineStats, StageStats, ThroughputStats

        stats = PipelineStats(
            timestamp="2026-02-28T00:00:00Z",
            stages={"triage": StageStats(queued=3, active=1)},
            throughput=ThroughputStats(triage=2.5),
            uptime_seconds=120.0,
        )
        orch = make_orchestrator_mock(running=True)
        orch.build_pipeline_stats = MagicMock(return_value=stats)
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/pipeline/stats")

        body = response.json()
        assert body["timestamp"] == "2026-02-28T00:00:00Z"
        assert body["stages"]["triage"]["queued"] == 3
        assert body["stages"]["triage"]["active"] == 1
        assert body["throughput"]["triage"] == 2.5
        assert body["uptime_seconds"] == 120.0

    def test_pipeline_stats_includes_queue_field(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard
        from models import PipelineStats

        stats = PipelineStats(timestamp="2026-02-28T00:00:00Z")
        orch = make_orchestrator_mock(running=True)
        orch.build_pipeline_stats = MagicMock(return_value=stats)
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/pipeline/stats")

        body = response.json()
        assert "queue" in body
        assert "throughput" in body

    def test_pipeline_stats_repo_param_ignored_without_registry(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """Without a registry, the ?repo= param is silently ignored (backward compat)."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/pipeline/stats?repo=some-org/some-repo")

        assert response.status_code == 200
        assert response.json() == {}


class TestPipelineStatsWebSocketForwarding:
    def test_pipeline_stats_event_type_exists(self) -> None:
        assert hasattr(EventType, "PIPELINE_STATS")
        assert EventType.PIPELINE_STATS.value == "pipeline_stats"

    def test_pipeline_stats_event_can_be_published(self, event_bus: EventBus) -> None:
        from models import PipelineStats

        stats = PipelineStats(timestamp="2026-02-28T00:00:00Z")
        event = HydraFlowEvent(
            type=EventType.PIPELINE_STATS,
            data=stats.model_dump(),
        )
        # Should not raise
        assert event.type == EventType.PIPELINE_STATS
        assert event.data["timestamp"] == "2026-02-28T00:00:00Z"


# ---------------------------------------------------------------------------
# Registry forwarding
# ---------------------------------------------------------------------------


class TestRegistryForwarding:
    def test_create_app_passes_registry_to_create_router(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        mock_registry = MagicMock()

        with patch("dashboard_routes.create_router") as mock_create_router:
            mock_create_router.return_value = MagicMock()
            dashboard = HydraFlowDashboard(
                config, event_bus, state, registry=mock_registry
            )
            dashboard.create_app()

            mock_create_router.assert_called_once()
            call_kwargs = mock_create_router.call_args
            assert call_kwargs.kwargs.get("registry") is mock_registry

    def test_create_app_default_registry_is_none(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        with patch("dashboard_routes.create_router") as mock_create_router:
            mock_create_router.return_value = MagicMock()
            dashboard = HydraFlowDashboard(config, event_bus, state)
            dashboard.create_app()

            mock_create_router.assert_called_once()
            call_kwargs = mock_create_router.call_args
            assert call_kwargs.kwargs.get("registry") is None

    def test_registry_stored_on_instance(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        mock_registry = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, registry=mock_registry)
        assert dashboard._registry is mock_registry

    def test_registry_defaults_to_none_on_instance(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        assert dashboard._registry is None


# ---------------------------------------------------------------------------
# Circular import guard (issue #5958)
# ---------------------------------------------------------------------------


class TestNoCircularImport:
    """Verify server.py and dashboard.py have no circular import dependency."""

    def test_serve_not_importable_from_dashboard(self) -> None:
        """serve() was removed to break the circular import cycle."""
        import importlib

        mod = importlib.import_module("dashboard")
        assert not hasattr(mod, "serve")

    def test_dashboard_does_not_import_server_at_module_level(self) -> None:
        """dashboard module must not import server at module scope."""
        import importlib
        import sys

        # Remove cached modules so the import runs fresh
        sys.modules.pop("dashboard", None)
        sys.modules.pop("server", None)

        importlib.import_module("dashboard")

        assert "server" not in sys.modules, (
            "dashboard.py imports 'server' at module level, creating a circular dependency"
        )

    def test_server_does_not_import_dashboard_at_module_level(self) -> None:
        """server module must not import dashboard at module scope."""
        import importlib
        import sys

        # Remove cached modules so the import runs fresh
        sys.modules.pop("dashboard", None)
        sys.modules.pop("server", None)

        importlib.import_module("server")

        assert "dashboard" not in sys.modules, (
            "server.py imports 'dashboard' at module level, creating a circular dependency"
        )
