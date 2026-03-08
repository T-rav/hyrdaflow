"""Tests for dashboard_routes.py — control and config endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


class TestControlStatusImproveLabel:
    """Tests that /api/control/status includes improve_label."""

    @pytest.mark.asyncio
    async def test_control_status_includes_improve_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /api/control/status should include improve_label from config."""
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

        get_control_status = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/control/status"
                and hasattr(route, "endpoint")
            ):
                get_control_status = route.endpoint  # type: ignore[union-attr]
                break

        assert get_control_status is not None
        response = await get_control_status()
        import json

        data = json.loads(response.body)
        assert "config" in data
        assert "improve_label" in data["config"]
        assert data["config"]["improve_label"] == config.improve_label


class TestControlStatusMaxTriagers:
    """Tests that /api/control/status includes max_triagers."""

    @pytest.mark.asyncio
    async def test_control_status_includes_max_triagers(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /api/control/status should include max_triagers from config."""
        import json

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

        get_control_status = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/control/status"
                and hasattr(route, "endpoint")
            ):
                get_control_status = route.endpoint
                break

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert "config" in data
        assert data["config"]["max_triagers"] == config.max_triagers


class TestControlStatusAppVersion:
    """Tests that /api/control/status includes app_version."""

    @pytest.mark.asyncio
    async def test_control_status_includes_app_version(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        import json

        from app_version import get_app_version
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

        get_control_status = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/control/status"
                and hasattr(route, "endpoint")
            ):
                get_control_status = route.endpoint  # type: ignore[union-attr]
                break

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["app_version"] == get_app_version()

    @pytest.mark.asyncio
    async def test_control_status_includes_cached_update_details(
        self, config, event_bus: EventBus, state, tmp_path: Path, monkeypatch
    ) -> None:
        import json

        from dashboard_routes import create_router
        from hf_cli.update_check import UpdateCheckResult
        from pr_manager import PRManager

        monkeypatch.setattr(
            "dashboard_routes.load_cached_update_result",
            lambda **_kwargs: UpdateCheckResult(
                current_version="0.9.0",
                latest_version="0.9.2",
                update_available=True,
                error=None,
            ),
        )

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

        get_control_status = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/control/status"
                and hasattr(route, "endpoint")
            ):
                get_control_status = route.endpoint  # type: ignore[union-attr]
                break

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["latest_version"] == "0.9.2"
        assert data["config"]["update_available"] is True


class TestControlStatusMemoryAutoApprove:
    """Tests that /api/control/status includes memory_auto_approve."""

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
    async def test_control_status_includes_memory_auto_approve_default(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /api/control/status should include memory_auto_approve (default False)."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        get_control_status = self._find_endpoint(router, "/api/control/status")
        assert get_control_status is not None

        response = await get_control_status()
        data = json.loads(response.body)
        assert "config" in data
        assert data["config"]["memory_auto_approve"] is False

    @pytest.mark.asyncio
    async def test_control_status_reflects_memory_auto_approve_true(
        self, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /api/control/status should reflect True when config has it enabled."""
        import json

        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        router = self._make_router(cfg, event_bus, state, tmp_path)
        get_control_status = self._find_endpoint(router, "/api/control/status")
        assert get_control_status is not None

        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["memory_auto_approve"] is True


class TestPatchConfigMemoryAutoApprove:
    """Tests that PATCH /api/control/config accepts memory_auto_approve."""

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
    async def test_patch_config_enables_memory_auto_approve(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH /api/control/config with memory_auto_approve=True should update config."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        patch_config = self._find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        assert config.memory_auto_approve is False
        response = await patch_config({"memory_auto_approve": True})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["updated"]["memory_auto_approve"] is True
        assert config.memory_auto_approve is True

    @pytest.mark.asyncio
    async def test_patch_config_disables_memory_auto_approve(
        self, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH /api/control/config with memory_auto_approve=False should update config."""
        import json

        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        router = self._make_router(cfg, event_bus, state, tmp_path)
        patch_config = self._find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        assert cfg.memory_auto_approve is True
        response = await patch_config({"memory_auto_approve": False})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["updated"]["memory_auto_approve"] is False
        assert cfg.memory_auto_approve is False

    @pytest.mark.asyncio
    async def test_patch_config_memory_auto_approve_ignored_field(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Unknown fields in PATCH should be ignored without error."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        patch_config = self._find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        response = await patch_config({"unknown_field": True})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["updated"] == {}


class TestPatchConfigMaxTriagers:
    """Tests that PATCH /api/control/config accepts max_triagers."""

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
    async def test_patch_config_updates_max_triagers(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH /api/control/config with max_triagers should update config."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        patch_config = self._find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        assert config.max_triagers == 1
        response = await patch_config({"max_triagers": 3})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["updated"]["max_triagers"] == 3
        assert config.max_triagers == 3


class TestBgWorkerToggleEndpoint:
    """Tests for POST /api/control/bg-worker endpoint."""

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

    def _find_endpoint(self, router, path, method="POST"):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_bg_worker_toggle_returns_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        toggle = self._find_endpoint(router, "/api/control/bg-worker")
        assert toggle is not None

        response = await toggle({"name": "memory_sync", "enabled": False})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_bg_worker_toggle_requires_name_and_enabled(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = AsyncMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        toggle = self._find_endpoint(router, "/api/control/bg-worker")
        assert toggle is not None

        response = await toggle({"name": "memory_sync"})
        assert response.status_code == 400

        response = await toggle({"enabled": True})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_bg_worker_toggle_calls_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.set_bg_worker_enabled = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        toggle = self._find_endpoint(router, "/api/control/bg-worker")
        assert toggle is not None

        response = await toggle({"name": "memory_sync", "enabled": False})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["name"] == "memory_sync"
        assert data["enabled"] is False
        mock_orch.set_bg_worker_enabled.assert_called_once_with("memory_sync", False)

    def test_route_is_registered(self, config, event_bus, state, tmp_path) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker" in paths


# ---------------------------------------------------------------------------
# /api/control/bg-worker/interval endpoint
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# /api/control/bg-worker/interval endpoint
# ---------------------------------------------------------------------------


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

    def test_interval_route_is_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker/interval" in paths

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_pr_unsticker(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pr_unsticker", "interval_seconds": 7200})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "pr_unsticker"
        assert data["interval_seconds"] == 7200
        mock_orch.set_bg_worker_interval.assert_called_once_with("pr_unsticker", 7200)

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_memory_sync(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "memory_sync", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        mock_orch.set_bg_worker_interval.assert_called_once_with("memory_sync", 3600)

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_metrics(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "metrics", "interval_seconds": 1800})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        mock_orch.set_bg_worker_interval.assert_called_once_with("metrics", 1800)

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_pr_unsticker(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pr_unsticker", "interval_seconds": 30})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 60 and 86400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_pr_unsticker(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pr_unsticker", "interval_seconds": 100000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 60 and 86400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_pipeline_poller(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pipeline_poller", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "pipeline_poller"
        assert data["interval_seconds"] == 3600
        mock_orch.set_bg_worker_interval.assert_called_once_with(
            "pipeline_poller", 3600
        )

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_pipeline_poller(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pipeline_poller", "interval_seconds": 2})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 5 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_pipeline_poller(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint(
            {"name": "pipeline_poller", "interval_seconds": 20000}
        )
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 5 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_non_editable_worker(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "retrospective", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "not editable" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_missing_name(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "required" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_missing_interval(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pr_unsticker"})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "required" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_non_integer_interval(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "pr_unsticker", "interval_seconds": "abc"})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "integer" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "memory_sync", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_memory_sync(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "memory_sync", "interval_seconds": 5})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 10 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_memory_sync(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "memory_sync", "interval_seconds": 20000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 10 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_metrics(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "metrics", "interval_seconds": 10})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 30 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_metrics(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "metrics", "interval_seconds": 20000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 30 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_adr_reviewer(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "adr_reviewer", "interval_seconds": 86400})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "adr_reviewer"
        assert data["interval_seconds"] == 86400
        mock_orch.set_bg_worker_interval.assert_called_once_with("adr_reviewer", 86400)

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_adr_reviewer(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "adr_reviewer", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 28800 and 432000" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_adr_reviewer(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "adr_reviewer", "interval_seconds": 500000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 28800 and 432000" in data["error"]


# ---------------------------------------------------------------------------
# /api/pipeline endpoint
# ---------------------------------------------------------------------------
