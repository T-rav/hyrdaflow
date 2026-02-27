"""Tests for dashboard_routes.py — route factory and handler registration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType, HydraFlowEvent
from models import HITLItem, SessionStatus


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
            "/api/timeline",
            "/api/timeline/issue/{issue_num}",
            "/api/intent",
            "/api/sessions",
            "/api/sessions/{session_id}",
            "/api/request-changes",
            "/api/runs",
            "/api/runs/{issue_number}",
            "/api/runs/{issue_number}/{timestamp}/{filename}",
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


class TestIssueHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_issue_history_aggregates_inference_and_events(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        import json

        from dashboard_routes import create_router
        from pr_manager import PRManager
        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=77,
            pr_number=501,
            session_id="sess-x",
            prompt_chars=400,
            transcript_chars=200,
            duration_seconds=1.5,
            success=True,
            stats={"total_tokens": 123, "input_tokens": 80, "output_tokens": 43},
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={
                    "issue": 77,
                    "title": "Improve planner quality",
                    "labels": ["epic:quality"],
                },
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                data={"issue": 77, "pr": 501, "url": "https://example.com/pull/501"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                data={"pr": 501, "status": "merged"},
            )
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

        endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/issues/history"
                and hasattr(route, "endpoint")
            ):
                endpoint = route.endpoint
                break
        assert endpoint is not None

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        assert payload["totals"]["issues"] >= 1
        assert payload["totals"]["total_tokens"] >= 123

        issue = next((x for x in payload["items"] if x["issue_number"] == 77), None)
        assert issue is not None
        assert issue["status"] == "merged"
        assert issue["epic"] == "epic:quality"
        assert issue["inference"]["total_tokens"] == 123
        assert issue["session_ids"] == ["sess-x"]
        assert issue["prs"][0]["number"] == 501
        assert issue["prs"][0]["merged"] is True

    @pytest.mark.asyncio
    async def test_issue_history_uses_latest_status_not_highest_rank(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
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

        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/issues/history"
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-02-25T00:00:00+00:00",
                data={"issue": 88, "status": "failed", "worker": 1},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-02-25T00:05:00+00:00",
                data={"issue": 88, "status": "running", "worker": 1},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 88), None)
        assert issue is not None
        assert issue["status"] == "active"

    @pytest.mark.asyncio
    async def test_issue_history_merges_with_pr_created_outside_range(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
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
        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/issues/history"
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                timestamp="2026-02-01T00:00:00+00:00",
                data={"issue": 99, "pr": 9001},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                timestamp="2026-02-20T00:00:00+00:00",
                data={"pr": 9001, "status": "merged"},
            )
        )

        response = await endpoint(
            since="2026-02-10T00:00:00+00:00", until="2026-02-28T00:00:00+00:00"
        )
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 99), None)
        assert issue is not None
        assert issue["status"] == "merged"
        assert issue["prs"][0]["number"] == 9001
        assert issue["prs"][0]["merged"] is True

    @pytest.mark.asyncio
    async def test_issue_history_filters_by_status_and_query(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
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
        endpoint = next(
            r.endpoint
            for r in router.routes
            if getattr(r, "path", "") == "/api/issues/history"
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 101, "title": "Fix auth cache"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                timestamp="2026-02-21T00:01:00+00:00",
                data={"issue": 101, "status": "running", "worker": 1},
            )
        )

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T00:00:00+00:00",
                data={"issue": 102, "title": "Merge docs"},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PR_CREATED,
                timestamp="2026-02-21T00:02:00+00:00",
                data={"issue": 102, "pr": 3002},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.MERGE_UPDATE,
                timestamp="2026-02-21T00:03:00+00:00",
                data={"pr": 3002, "status": "merged"},
            )
        )

        response = await endpoint(status="merged", query="docs")
        payload = json.loads(response.body)
        assert len(payload["items"]) == 1
        assert payload["items"][0]["issue_number"] == 102


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


class TestHITLEndpointCause:
    """Tests that /api/hitl includes the cause from state."""

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_cause_from_state(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When a HITL cause is set in state, it should appear in the response."""
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

        # Set a cause in state for issue 42
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")

        # Mock list_hitl_items to return a single item
        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        # Find and call the get_hitl handler
        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        data = response.body  # JSONResponse stores body as bytes
        import json

        items = json.loads(data)
        assert len(items) == 1
        assert items[0]["cause"] == "CI failed after 2 fix attempt(s)"
        called_labels = pr_mgr.list_hitl_items.await_args.args[0]  # type: ignore[union-attr]
        assert set(called_labels) == {
            *config.hitl_label,
            *config.hitl_active_label,
        }

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_items_from_hitl_active_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """`/api/hitl` should return items tagged with either HITL label."""
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)

        async def fake_run_gh(*args: str, **_kwargs: object) -> str:
            # list_hitl_items -> _fetch_hitl_raw_issues
            if args[0] == "gh" and args[1] == "api" and "issues" in args[2]:
                label_arg = next(
                    (
                        arg
                        for arg in args
                        if isinstance(arg, str) and arg.startswith("labels=")
                    ),
                    "",
                )
                if label_arg == f"labels={config.hitl_label[0]}":
                    return (
                        '[{"number": 42, "title": "Issue from hitl", '
                        '"url": "https://github.com/T-rav/hyrda/issues/42"}]'
                    )
                if label_arg == f"labels={config.hitl_active_label[0]}":
                    return (
                        '[{"number": 77, "title": "Issue from hitl-active", '
                        '"url": "https://github.com/T-rav/hyrda/issues/77"}]'
                    )
                return "[]"
            # list_hitl_items -> _build_hitl_item PR lookup
            if args[0] == "gh" and args[1] == "api" and "/pulls" in args[2]:
                return "[]"
            raise AssertionError(f"Unexpected gh invocation: {args}")

        pr_mgr._run_gh = fake_run_gh  # type: ignore[method-assign]

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

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        issue_numbers = {item["issue"] for item in items}
        assert {42, 77}.issubset(issue_numbers)

    @pytest.mark.asyncio
    async def test_hitl_endpoint_omits_cause_when_not_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no cause is set, the default empty string from model should be present."""
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

        # No cause set in state
        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        # No cause or origin — should remain empty
        assert items[0]["cause"] == ""

    @pytest.mark.asyncio
    async def test_hitl_includes_is_memory_suggestion_when_origin_is_improve(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When HITL origin matches improve_label, isMemorySuggestion should be True."""
        from dashboard_routes import create_router
        from pr_manager import PRManager

        state.set_hitl_origin(42, "hydraflow-improve")
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

        hitl_item = HITLItem(issue=42, title="Memory suggestion", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["isMemorySuggestion"] is True

    @pytest.mark.asyncio
    async def test_hitl_is_memory_suggestion_false_when_origin_is_other(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When HITL origin is not improve_label, isMemorySuggestion should be False."""
        from dashboard_routes import create_router
        from pr_manager import PRManager

        state.set_hitl_origin(42, "hydraflow-review")
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

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["isMemorySuggestion"] is False

    @pytest.mark.asyncio
    async def test_hitl_is_memory_suggestion_false_when_no_origin(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no HITL origin is set at all, isMemorySuggestion should be False."""
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

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["isMemorySuggestion"] is False

    @pytest.mark.asyncio
    async def test_hitl_endpoint_falls_back_to_origin_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no cause is set but origin is, should fall back to origin description."""
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

        # Set origin but not cause
        state.set_hitl_origin(42, "hydraflow-review")

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["cause"] == "Review escalation"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_origin_fallback_unknown_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Unknown origin label should produce generic fallback message."""
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

        state.set_hitl_origin(42, "some-unknown-label")

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["cause"] == "Escalation (reason not recorded)"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_cause_takes_precedence_over_origin(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When both cause and origin are set, cause should take precedence."""
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

        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")
        state.set_hitl_origin(42, "hydraflow-review")

        hitl_item = HITLItem(issue=42, title="Fix bug", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["cause"] == "CI failed after 2 fix attempt(s)"

    @pytest.mark.asyncio
    async def test_hitl_filters_memory_suggestions_when_auto_approve_enabled(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """With memory_auto_approve=True, memory items excluded from response."""
        from dashboard_routes import create_router
        from pr_manager import PRManager
        from state import StateTracker
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            memory_auto_approve=True,
        )
        st = StateTracker(cfg.state_file)
        pr_mgr = PRManager(cfg, event_bus)

        router = create_router(
            config=cfg,
            event_bus=event_bus,
            state=st,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

        # Mark issue 42 as a memory suggestion (origin = improve label)
        st.set_hitl_origin(42, "hydraflow-improve")
        st.set_hitl_cause(42, "Actionable memory suggestion (config)")

        # Also add a non-memory HITL item
        st.set_hitl_origin(43, "hydraflow-review")
        st.set_hitl_cause(43, "CI failed after 2 fix attempt(s)")

        hitl_items = [
            HITLItem(issue=42, title="Memory suggestion", pr=101),
            HITLItem(issue=43, title="CI failure", pr=102),
        ]
        pr_mgr.list_hitl_items = AsyncMock(return_value=hitl_items)  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        # Only the non-memory item should remain
        assert len(items) == 1
        assert items[0]["issue"] == 43

    @pytest.mark.asyncio
    async def test_hitl_keeps_memory_suggestions_when_auto_approve_disabled(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """With memory_auto_approve=False (default), memory items included."""
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

        state.set_hitl_origin(42, "hydraflow-improve")
        state.set_hitl_cause(42, "Actionable memory suggestion (config)")

        hitl_item = HITLItem(issue=42, title="Memory suggestion", pr=101)
        pr_mgr.list_hitl_items = AsyncMock(return_value=[hitl_item])  # type: ignore[method-assign]

        get_hitl = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/hitl"
                and hasattr(route, "endpoint")
            ):
                get_hitl = route.endpoint  # type: ignore[union-attr]
                break

        assert get_hitl is not None
        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert len(items) == 1
        assert items[0]["isMemorySuggestion"] is True


# ---------------------------------------------------------------------------
# /api/metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """Tests for the GET /api/metrics endpoint."""

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
                return route.endpoint  # type: ignore[union-attr]
        return None

    @pytest.mark.asyncio
    async def test_metrics_returns_zero_rates_when_no_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        get_metrics = self._find_endpoint(router, "/api/metrics")
        assert get_metrics is not None

        response = await get_metrics()
        data = json.loads(response.body)

        assert data["rates"].get("quality_fix_rate", 0.0) == pytest.approx(0.0)
        assert data["rates"].get("first_pass_approval_rate", 0.0) == pytest.approx(0.0)
        assert data["rates"].get("hitl_escalation_rate", 0.0) == pytest.approx(0.0)
        assert data["lifetime"]["issues_completed"] == 0
        assert data["lifetime"]["prs_merged"] == 0

    @pytest.mark.asyncio
    async def test_metrics_returns_computed_rates(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        # Set up some stats
        for _ in range(10):
            state.record_issue_completed()
        for _ in range(5):
            state.record_pr_merged()
        state.record_quality_fix_rounds(4)
        state.record_review_verdict("approve", fixes_made=False)
        state.record_review_verdict("approve", fixes_made=False)
        state.record_review_verdict("request-changes", fixes_made=True)
        state.record_hitl_escalation()
        state.record_hitl_escalation()
        state.record_implementation_duration(100.0)

        router = self._make_router(config, event_bus, state, tmp_path)
        get_metrics = self._find_endpoint(router, "/api/metrics")
        response = await get_metrics()
        data = json.loads(response.body)

        assert data["rates"]["quality_fix_rate"] == pytest.approx(0.4)  # 4/10
        assert data["rates"]["first_pass_approval_rate"] == pytest.approx(
            2.0 / 3.0
        )  # 2/3
        assert data["rates"]["hitl_escalation_rate"] == pytest.approx(0.2)  # 2/10
        assert data["rates"]["avg_implementation_seconds"] == pytest.approx(
            10.0
        )  # 100/10
        assert data["rates"]["reviewer_fix_rate"] == pytest.approx(1.0 / 3.0)  # 1/3
        assert data["lifetime"]["issues_completed"] == 10
        assert data["lifetime"]["prs_merged"] == 5

    @pytest.mark.asyncio
    async def test_metrics_no_division_by_zero_on_reviews(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When no reviews exist, approval rate should be 0 not crash."""
        import json

        for _ in range(5):
            state.record_issue_completed()

        router = self._make_router(config, event_bus, state, tmp_path)
        get_metrics = self._find_endpoint(router, "/api/metrics")
        response = await get_metrics()
        data = json.loads(response.body)

        assert data["rates"].get("first_pass_approval_rate", 0.0) == pytest.approx(0.0)
        assert data["rates"].get("reviewer_fix_rate", 0.0) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_metrics_includes_inference_lifetime_and_session_totals(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=1,
            pr_number=0,
            session_id="session-1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 60},
        )

        class Orch:
            current_session_id = "session-1"

        def _get_orch():
            return Orch()

        # Build router with orchestrator getter override
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=_get_orch,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )
        get_metrics = self._find_endpoint(router, "/api/metrics")
        response = await get_metrics()
        data = json.loads(response.body)
        assert data["inference_lifetime"]["total_tokens"] == 60
        assert data["inference_session"]["total_tokens"] == 60


class TestGitHubMetricsEndpoint:
    """Tests for the GET /api/metrics/github endpoint."""

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
    async def test_github_metrics_returns_label_counts(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)

        mock_counts = {
            "open_by_label": {
                "hydraflow-plan": 3,
                "hydraflow-ready": 1,
                "hydraflow-review": 2,
                "hydraflow-hitl": 0,
                "hydraflow-fixed": 0,
            },
            "total_closed": 10,
            "total_merged": 8,
        }
        pr_mgr.get_label_counts = AsyncMock(return_value=mock_counts)

        get_github_metrics = self._find_endpoint(router, "/api/metrics/github")
        assert get_github_metrics is not None

        response = await get_github_metrics()
        data = json.loads(response.body)

        assert data["open_by_label"]["hydraflow-plan"] == 3
        assert data["total_closed"] == 10
        assert data["total_merged"] == 8


class TestMetricsHistoryEndpoint:
    """Tests for GET /api/metrics/history endpoint — local-cache fallback path."""

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
    async def test_returns_empty_when_no_cache(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns empty snapshots list when orchestrator is None and no local cache."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/metrics/history")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data["snapshots"] == []

    @pytest.mark.asyncio
    async def test_returns_local_cache_when_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Serves metrics snapshots from local disk cache when orchestrator is None."""
        import json

        from metrics_manager import get_metrics_cache_dir
        from models import MetricsSnapshot

        # Write a snapshot directly to the local cache
        snap = MetricsSnapshot(timestamp="2025-06-01T00:00:00", issues_completed=7)
        cache_dir = get_metrics_cache_dir(config)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "snapshots.jsonl"
        cache_file.write_text(snap.model_dump_json() + "\n")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/metrics/history")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["issues_completed"] == 7


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


# ---------------------------------------------------------------------------
# /api/pipeline endpoint
# ---------------------------------------------------------------------------


class TestPipelineEndpoint:
    """Tests for the GET /api/pipeline endpoint."""

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

    def test_pipeline_route_is_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/pipeline" in paths

    @pytest.mark.asyncio
    async def test_pipeline_returns_empty_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        get_pipeline = self._find_endpoint(router, "/api/pipeline")
        assert get_pipeline is not None

        response = await get_pipeline()
        data = json.loads(response.body)
        assert "stages" in data
        assert data["stages"] == {}

    @pytest.mark.asyncio
    async def test_pipeline_maps_backend_stage_names_to_frontend(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.issue_store = MagicMock()
        mock_orch.issue_store.get_pipeline_snapshot = MagicMock(
            return_value={
                "find": [
                    {
                        "issue_number": 1,
                        "title": "Triage me",
                        "url": "",
                        "status": "queued",
                    }
                ],
                "ready": [
                    {
                        "issue_number": 2,
                        "title": "Implement me",
                        "url": "",
                        "status": "active",
                    }
                ],
                "hitl": [],
            }
        )
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        get_pipeline = self._find_endpoint(router, "/api/pipeline")
        assert get_pipeline is not None

        response = await get_pipeline()
        data = json.loads(response.body)

        # "find" → "triage", "ready" → "implement"
        assert "triage" in data["stages"]
        assert "implement" in data["stages"]
        assert len(data["stages"]["triage"]) == 1
        assert data["stages"]["triage"][0]["issue_number"] == 1
        assert len(data["stages"]["implement"]) == 1
        assert data["stages"]["implement"][0]["status"] == "active"


# ---------------------------------------------------------------------------
# HITL skip with improve origin → triage transition
# ---------------------------------------------------------------------------


class TestHITLSkipImproveTransition:
    """Tests that /api/hitl/{issue}/skip transitions improve issues to triage."""

    def _make_router(self, config, event_bus, state, tmp_path, get_orch=None):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        return (
            create_router(
                config=config,
                event_bus=event_bus,
                state=state,
                pr_manager=pr_mgr,
                get_orchestrator=get_orch or (lambda: None),
                set_orchestrator=lambda o: None,
                set_run_task=lambda t: None,
                ui_dist_dir=tmp_path / "no-dist",
                template_dir=tmp_path / "no-templates",
            ),
            pr_mgr,
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
    async def test_hitl_skip_improve_origin_transitions_to_triage(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skipping an improve-origin HITL item should remove improve and add find label."""
        state.set_hitl_origin(42, "hydraflow-improve")
        state.set_hitl_cause(42, "Memory suggestion")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None

        response = await skip(42)
        assert response.status_code == 200

        # Verify find/triage label was set via swap
        pr_mgr.swap_pipeline_labels.assert_any_call(42, config.find_label[0])

        # Verify state cleanup
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None

    @pytest.mark.asyncio
    async def test_hitl_skip_non_improve_origin_no_triage_transition(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Non-improve HITL items should not get triage label on skip."""
        state.set_hitl_origin(42, "hydraflow-review")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42)

        # Should NOT add find label for non-improve origins
        add_calls = [c.args for c in pr_mgr.add_labels.call_args_list]
        for call in add_calls:
            assert call[1] != [config.find_label[0]]

    @pytest.mark.asyncio
    async def test_hitl_skip_no_origin_no_triage_transition(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When no origin is set, skip should not add find label."""

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42)

        # Should NOT add find label when no origin
        add_calls = [c.args for c in pr_mgr.add_labels.call_args_list]
        for call in add_calls:
            assert call[1] != [config.find_label[0]]

    @pytest.mark.asyncio
    async def test_hitl_skip_cleans_up_hitl_cause(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should clean up hitl_cause in addition to hitl_origin."""
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, _ = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42)

        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None


# ---------------------------------------------------------------------------
# POST /api/request-changes endpoint
# ---------------------------------------------------------------------------


class TestRequestChangesEndpoint:
    """Tests for POST /api/request-changes endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
        return (
            create_router(
                config=config,
                event_bus=event_bus,
                state=state,
                pr_manager=pr_mgr,
                get_orchestrator=lambda: None,
                set_orchestrator=lambda o: None,
                set_run_task=lambda t: None,
                ui_dist_dir=tmp_path / "no-dist",
                template_dir=tmp_path / "no-templates",
            ),
            pr_mgr,
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
    async def test_request_changes_stores_cause_and_origin(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Submit with valid data stores HITL cause and origin."""
        import json

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint(
            {"issue_number": 42, "feedback": "Fix the tests", "stage": "review"}
        )
        data = json.loads(response.body)
        assert data["status"] == "ok"

        assert state.get_hitl_cause(42) == "Fix the tests"
        assert state.get_hitl_origin(42) == config.review_label[0]

    @pytest.mark.asyncio
    async def test_request_changes_swaps_labels(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Request changes transitions issue into HITL via pipeline label swap."""
        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        await endpoint(
            {"issue_number": 42, "feedback": "Fix the tests", "stage": "review"}
        )

        pr_mgr.swap_pipeline_labels.assert_awaited_once_with(42, config.hitl_label[0])

    @pytest.mark.asyncio
    async def test_request_changes_emits_escalation_event(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """HITL_ESCALATION event is emitted with correct data."""
        queue = event_bus.subscribe()

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        await endpoint(
            {"issue_number": 42, "feedback": "Fix the tests", "stage": "implement"}
        )

        event = queue.get_nowait()
        assert event.type == "hitl_escalation"
        assert event.data["issue"] == 42
        assert event.data["cause"] == "Fix the tests"
        assert event.data["origin"] == config.ready_label[0]

    @pytest.mark.asyncio
    async def test_request_changes_rejects_empty_feedback(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns 400 when feedback is empty."""
        import json

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint(
            {"issue_number": 42, "feedback": "  ", "stage": "review"}
        )
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "required" in data["detail"]

    @pytest.mark.asyncio
    async def test_request_changes_rejects_unknown_stage(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns 400 when stage is not recognized."""
        import json

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint(
            {"issue_number": 42, "feedback": "Fix it", "stage": "unknown"}
        )
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "Unknown stage" in data["detail"]

    @pytest.mark.asyncio
    async def test_request_changes_rejects_missing_issue_number(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns 400 when issue_number is missing."""
        import json

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint({"feedback": "Fix it", "stage": "review"})
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "required" in data["detail"]

    @pytest.mark.asyncio
    async def test_request_changes_rejects_zero_issue_number(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns 400 when issue_number is 0 or negative."""
        import json

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        for bad_num in [0, -1, -99]:
            response = await endpoint(
                {"issue_number": bad_num, "feedback": "Fix it", "stage": "review"}
            )
            assert response.status_code == 400, (
                f"Expected 400 for issue_number={bad_num}"
            )
            data = json.loads(response.body)
            assert "required" in data["detail"]

    @pytest.mark.asyncio
    async def test_request_changes_rejects_non_integer_issue_number(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Returns 400 when issue_number is a string instead of an int."""
        import json

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint(
            {"issue_number": "42", "feedback": "Fix it", "stage": "review"}
        )
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "required" in data["detail"]

    def test_route_is_registered(self, config, event_bus, state, tmp_path) -> None:
        router, _ = self._make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/request-changes" in paths

    @pytest.mark.asyncio
    async def test_request_changes_triage_stage(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Triage stage records origin from find_label and routes to HITL."""
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint(
            {"issue_number": 10, "feedback": "Not the right issue", "stage": "triage"}
        )
        data = json.loads(response.body)
        assert data["status"] == "ok"

        assert state.get_hitl_cause(10) == "Not the right issue"
        assert state.get_hitl_origin(10) == config.find_label[0]

        pr_mgr.swap_pipeline_labels.assert_awaited_once_with(10, config.hitl_label[0])

    @pytest.mark.asyncio
    async def test_request_changes_plan_stage(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Plan stage records origin from planner_label and routes to HITL."""
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/request-changes")
        assert endpoint is not None

        response = await endpoint(
            {"issue_number": 7, "feedback": "Plan is incomplete", "stage": "plan"}
        )
        data = json.loads(response.body)
        assert data["status"] == "ok"

        assert state.get_hitl_cause(7) == "Plan is incomplete"
        assert state.get_hitl_origin(7) == config.planner_label[0]

        pr_mgr.swap_pipeline_labels.assert_awaited_once_with(7, config.hitl_label[0])


class TestDeleteSessionEndpoint:
    """Tests for DELETE /api/sessions/{session_id}."""

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

    def _find_endpoint(self, router, path, method=None):
        for route in router.routes:
            if not (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                continue
            if method is None or (
                hasattr(route, "methods") and method in route.methods
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_delete_session_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import SessionLog

        state.save_session(
            SessionLog(
                id="s1",
                repo="org/repo",
                started_at="2024-01-01T00:00:00",
                status=SessionStatus.COMPLETED,
            )
        )
        router = self._make_router(config, event_bus, state, tmp_path)
        delete_endpoint = self._find_endpoint(
            router, "/api/sessions/{session_id}", method="DELETE"
        )
        assert delete_endpoint is not None
        response = await delete_endpoint("s1")
        data = json.loads(response.body)
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_session_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        delete_endpoint = self._find_endpoint(
            router, "/api/sessions/{session_id}", method="DELETE"
        )
        assert delete_endpoint is not None
        response = await delete_endpoint("nonexistent")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_active_session_returns_400(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import SessionLog

        state.save_session(
            SessionLog(
                id="active-s",
                repo="org/repo",
                started_at="2024-01-01T00:00:00",
                status=SessionStatus.ACTIVE,
            )
        )
        router = self._make_router(config, event_bus, state, tmp_path)
        delete_endpoint = self._find_endpoint(
            router, "/api/sessions/{session_id}", method="DELETE"
        )
        assert delete_endpoint is not None
        response = await delete_endpoint("active-s")
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "active" in data["error"].lower()


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


class TestLoadLocalMetricsCacheExceptionHandling:
    """Verify _load_local_metrics_cache skips corrupt lines with debug logging."""

    def test_skips_corrupt_lines_with_logging(
        self, config, event_bus: EventBus, state, tmp_path: Path, caplog
    ) -> None:
        """Corrupt lines in metrics cache should be skipped with debug logging."""
        import logging

        from dashboard_routes import create_router
        from metrics_manager import get_metrics_cache_dir
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

        # Write corrupt lines to the metrics cache file
        cache_dir = get_metrics_cache_dir(config)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "snapshots.jsonl"
        cache_file.write_text("corrupt line\nalso bad\n")

        # Find the _load_local_metrics_cache function through the metrics/history endpoint
        history_endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/metrics/history"
                and hasattr(route, "endpoint")
            ):
                history_endpoint = route.endpoint
                break

        assert history_endpoint is not None

        import asyncio

        with caplog.at_level(logging.DEBUG, logger="hydraflow.dashboard"):
            asyncio.run(history_endpoint())

        assert "Skipping corrupt metrics snapshot line" in caplog.text

    def test_load_local_metrics_cache_returns_empty_on_oserror(
        self, config, event_bus: EventBus, state, tmp_path: Path, caplog
    ) -> None:
        """When the cache file can't be read due to OSError, return empty snapshots."""
        import asyncio
        import logging
        from unittest.mock import patch

        from dashboard_routes import create_router
        from metrics_manager import get_metrics_cache_dir
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

        # Create a valid cache file first so exists() returns True
        cache_dir = get_metrics_cache_dir(config)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "snapshots.jsonl"
        cache_file.write_text('{"timestamp": "2025-01-01T00:00:00"}\n')

        # Find the metrics/history endpoint
        history_endpoint = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/metrics/history"
                and hasattr(route, "endpoint")
            ):
                history_endpoint = route.endpoint
                break

        assert history_endpoint is not None

        with (
            patch("builtins.open", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.dashboard"),
        ):
            response = asyncio.run(history_endpoint())

        assert "Could not read metrics cache" in caplog.text
        # Should return response with empty snapshots
        import json

        data = json.loads(response.body)
        assert data["snapshots"] == []


# ---------------------------------------------------------------------------
# /api/runs endpoints
# ---------------------------------------------------------------------------


class TestRunsEndpoints:
    """Tests for the /api/runs route family."""

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

    # --- GET /api/runs (list_run_issues) ---

    @pytest.mark.asyncio
    async def test_list_run_issues_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Without orchestrator, returns empty list."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/runs")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_list_run_issues_with_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """With orchestrator, returns run_recorder.list_issues() result."""
        import json

        mock_orch = MagicMock()
        mock_orch.run_recorder = MagicMock()
        mock_orch.run_recorder.list_issues = MagicMock(return_value=[42, 99])

        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/runs")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == [42, 99]

    # --- GET /api/runs/{issue_number} (get_runs) ---

    @pytest.mark.asyncio
    async def test_get_runs_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Without orchestrator, returns empty list."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/runs/{issue_number}")
        assert endpoint is not None

        response = await endpoint(42)
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_get_runs_with_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """With orchestrator, returns serialized RunManifest list."""
        import json

        from run_recorder import RunManifest

        manifest = RunManifest(
            issue_number=42,
            timestamp="2025-01-01T00:00:00",
            outcome="success",
            duration_seconds=12.5,
            files=["plan.md", "transcript.txt"],
        )

        mock_orch = MagicMock()
        mock_orch.run_recorder = MagicMock()
        mock_orch.run_recorder.list_runs = MagicMock(return_value=[manifest])

        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/runs/{issue_number}")
        assert endpoint is not None

        response = await endpoint(42)
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["issue_number"] == 42
        assert data[0]["outcome"] == "success"
        assert data[0]["timestamp"] == "2025-01-01T00:00:00"

    # --- GET /api/runs/{issue_number}/{timestamp}/{filename} (get_run_artifact) ---

    @pytest.mark.asyncio
    async def test_get_run_artifact_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Without orchestrator, returns 400."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(
            router, "/api/runs/{issue_number}/{timestamp}/{filename}"
        )
        assert endpoint is not None

        response = await endpoint(42, "2025-01-01T00:00:00", "plan.md")
        assert response.status_code == 400
        data = json.loads(response.body)
        assert data["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_get_run_artifact_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When artifact exists, returns 200 with plain text content."""
        mock_orch = MagicMock()
        mock_orch.run_recorder = MagicMock()
        mock_orch.run_recorder.get_run_artifact = MagicMock(
            return_value="# Plan\nDo the thing."
        )

        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(
            router, "/api/runs/{issue_number}/{timestamp}/{filename}"
        )
        assert endpoint is not None

        response = await endpoint(42, "2025-01-01T00:00:00", "plan.md")
        assert response.status_code == 200
        assert response.body == b"# Plan\nDo the thing."
        assert response.media_type == "text/plain"

    @pytest.mark.asyncio
    async def test_get_run_artifact_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When artifact does not exist, returns 404."""
        import json

        mock_orch = MagicMock()
        mock_orch.run_recorder = MagicMock()
        mock_orch.run_recorder.get_run_artifact = MagicMock(return_value=None)

        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(
            router, "/api/runs/{issue_number}/{timestamp}/{filename}"
        )
        assert endpoint is not None

        response = await endpoint(42, "2025-01-01T00:00:00", "missing.txt")
        assert response.status_code == 404
        data = json.loads(response.body)
        assert data["error"] == "artifact not found"


# ---------------------------------------------------------------------------
# GET /api/state
# ---------------------------------------------------------------------------


class TestGetStateEndpoint:
    """Tests for GET /api/state."""

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
    async def test_returns_state_dict(self, config, event_bus, state, tmp_path) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/state")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert isinstance(data, dict)
        assert "processed_issues" in data

    @pytest.mark.asyncio
    async def test_reflects_state_changes(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        state.mark_issue(42, "in_progress")
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/state")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["processed_issues"]["42"] == "in_progress"


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------


class TestGetStatsEndpoint:
    """Tests for GET /api/stats."""

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
    async def test_returns_lifetime_stats(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/stats")
        response = await endpoint()
        data = json.loads(response.body)
        assert "issues_completed" in data

    @pytest.mark.asyncio
    async def test_includes_queue_when_orchestrator_present(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.issue_store = MagicMock()
        mock_orch.issue_store.get_queue_stats = MagicMock(
            return_value=MagicMock(model_dump=lambda: {"triage": 0, "plan": 0})
        )
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/stats")
        response = await endpoint()
        data = json.loads(response.body)
        assert "queue" in data

    @pytest.mark.asyncio
    async def test_no_queue_when_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/stats")
        response = await endpoint()
        data = json.loads(response.body)
        assert "queue" not in data


# ---------------------------------------------------------------------------
# GET /api/queue
# ---------------------------------------------------------------------------


class TestGetQueueEndpoint:
    """Tests for GET /api/queue."""

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
    async def test_returns_default_when_no_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/queue")
        response = await endpoint()
        data = json.loads(response.body)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_returns_queue_from_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.issue_store = MagicMock()
        mock_orch.issue_store.get_queue_stats = MagicMock(
            return_value=MagicMock(model_dump=lambda: {"triage": 3, "plan": 1})
        )
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/queue")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["triage"] == 3


# ---------------------------------------------------------------------------
# GET /api/events
# ---------------------------------------------------------------------------


class TestGetEventsEndpoint:
    """Tests for GET /api/events."""

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
    async def test_returns_empty_history_initially(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/events")
        response = await endpoint(since=None)
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_returns_events_after_publish(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from tests.conftest import EventFactory

        await event_bus.publish(EventFactory.create(data={"msg": "hello"}))
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/events")
        response = await endpoint(since=None)
        data = json.loads(response.body)
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_invalid_since_falls_through_to_history(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/events")
        response = await endpoint(since="not-a-date")
        data = json.loads(response.body)
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# GET /api/prs
# ---------------------------------------------------------------------------


class TestGetPRsEndpoint:
    """Tests for GET /api/prs."""

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
    async def test_returns_pr_list(self, config, event_bus, state, tmp_path) -> None:
        import json

        from models import PRListItem

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_open_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                PRListItem(pr=101, title="Fix bug", url="https://example.com/pr/101")
            ]
        )
        endpoint = self._find_endpoint(router, "/api/prs")
        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["pr"] == 101

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_prs(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_open_prs = AsyncMock(return_value=[])  # type: ignore[method-assign]
        endpoint = self._find_endpoint(router, "/api/prs")
        response = await endpoint()
        data = json.loads(response.body)
        assert data == []


# ---------------------------------------------------------------------------
# GET /api/sessions and /api/sessions/{session_id}
# ---------------------------------------------------------------------------


class TestGetSessionsEndpoint:
    """Tests for GET /api/sessions."""

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
    async def test_returns_empty_sessions(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/sessions")
        response = await endpoint(repo=None)
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_returns_saved_sessions(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import SessionLog

        state.save_session(
            SessionLog(
                id="s1", repo="test-org/test-repo", started_at="2024-01-01T00:00:00Z"
            )
        )
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/sessions")
        response = await endpoint(repo=None)
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["id"] == "s1"


class TestGetSessionDetailEndpoint:
    """Tests for GET /api/sessions/{session_id}."""

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
    async def test_returns_404_for_missing_session(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/sessions/{session_id}")
        response = await endpoint("nonexistent")
        assert response.status_code == 404
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_session_with_events(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import SessionLog

        state.save_session(
            SessionLog(
                id="s1", repo="test-org/test-repo", started_at="2024-01-01T00:00:00Z"
            )
        )
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/sessions/{session_id}")
        response = await endpoint("s1")
        data = json.loads(response.body)
        assert data["id"] == "s1"
        assert "events" in data


# ---------------------------------------------------------------------------
# GET /api/system/workers
# ---------------------------------------------------------------------------


class TestGetSystemWorkersEndpoint:
    """Tests for GET /api/system/workers."""

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
    async def test_returns_workers_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)
        assert "workers" in data
        assert len(data["workers"]) > 0

    @pytest.mark.asyncio
    async def test_returns_workers_with_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.get_bg_worker_states = MagicMock(return_value={})
        mock_orch.is_bg_worker_enabled = MagicMock(return_value=True)
        mock_orch.get_bg_worker_interval = MagicMock(return_value=120)
        router = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)
        assert "workers" in data

    @pytest.mark.asyncio
    async def test_system_workers_include_inference_rollups(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="sonnet",
            issue_number=42,
            pr_number=None,
            session_id="s-1",
            prompt_chars=200,
            transcript_chars=50,
            duration_seconds=1.2,
            success=True,
            stats={"total_tokens": 120, "pruned_chars_total": 800},
        )
        telemetry.record(
            source="agent",
            tool="codex",
            model="gpt-5",
            issue_number=43,
            pr_number=None,
            session_id="s-1",
            prompt_chars=150,
            transcript_chars=40,
            duration_seconds=0.8,
            success=True,
            stats={"total_tokens": 60, "pruned_chars_total": 200},
        )
        telemetry.record(
            source="merge_conflict",
            tool="claude",
            model="sonnet",
            issue_number=44,
            pr_number=222,
            session_id="s-1",
            prompt_chars=180,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 70, "pruned_chars_total": 400},
        )

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/system/workers")
        response = await endpoint()
        data = json.loads(response.body)
        plan_worker = next(w for w in data["workers"] if w["name"] == "plan")
        details = plan_worker["details"]
        assert details["inference_calls"] == 1
        assert details["total_tokens"] == 120
        assert details["pruned_chars_total"] == 800
        assert details["saved_tokens_est"] == 200
        assert details["unpruned_tokens_est"] == 320

        implement_worker = next(w for w in data["workers"] if w["name"] == "implement")
        assert implement_worker["details"]["inference_calls"] == 1
        assert implement_worker["details"]["total_tokens"] == 60

        review_worker = next(w for w in data["workers"] if w["name"] == "review")
        assert review_worker["details"]["inference_calls"] == 1
        assert review_worker["details"]["total_tokens"] == 70


# ---------------------------------------------------------------------------
# GET /api/timeline and /api/timeline/issue/{issue_num}
# ---------------------------------------------------------------------------


class TestGetTimelineEndpoint:
    """Tests for GET /api/timeline."""

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
    async def test_returns_empty_timeline(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/timeline")
        response = await endpoint()
        data = json.loads(response.body)
        assert isinstance(data, list)


class TestGetTimelineIssueEndpoint:
    """Tests for GET /api/timeline/issue/{issue_num}."""

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
    async def test_returns_404_for_unknown_issue(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/timeline/issue/{issue_num}")
        response = await endpoint(9999)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_timeline_for_issue(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from events import EventType, HydraFlowEvent

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.PHASE_CHANGE, data={"issue": 42, "phase": "plan"}
            )
        )
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/timeline/issue/{issue_num}")
        response = await endpoint(42)
        data = json.loads(response.body)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# GET /api/harness-insights and /api/harness-insights/history
# ---------------------------------------------------------------------------


class TestHarnessInsightsEndpoints:
    """Tests for harness-insights endpoints."""

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
    async def test_harness_insights_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/harness-insights")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_failures"] == 0
        assert data["suggestions"] == []

    @pytest.mark.asyncio
    async def test_harness_insights_history_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/harness-insights/history")
        response = await endpoint()
        data = json.loads(response.body)
        assert data == []


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue_number}/close
# ---------------------------------------------------------------------------


class TestHITLCloseEndpoint:
    """Tests for POST /api/hitl/{issue_number}/close."""

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
    async def test_returns_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_close_issue_with_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.close_issue = AsyncMock()  # type: ignore[method-assign]
        state.set_hitl_origin(42, "hydraflow-review")
        endpoint = self._find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42)
        data = json.loads(response.body)
        assert data["status"] == "ok"
        mock_orch.skip_hitl_issue.assert_called_once_with(42)
        pr_mgr.close_issue.assert_called_once_with(42)
        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue_number}/approve-memory
# ---------------------------------------------------------------------------


class TestHITLApproveMemoryEndpoint:
    """Tests for POST /api/hitl/{issue_number}/approve-memory."""

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
    async def test_approve_memory_removes_pipeline_labels(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.remove_label = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.add_labels = AsyncMock()  # type: ignore[method-assign]
        endpoint = self._find_endpoint(
            router, "/api/hitl/{issue_number}/approve-memory"
        )
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "some cause")
        response = await endpoint(42)
        data = json.loads(response.body)
        assert data["status"] == "ok"
        # Should remove all pipeline labels
        removed = {call.args[1] for call in pr_mgr.remove_label.call_args_list}
        assert removed == set(config.all_pipeline_labels)
        # Should add memory label
        pr_mgr.add_labels.assert_called_once_with(42, config.memory_label)
        # State should be cleaned up
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None

    @pytest.mark.asyncio
    async def test_approve_memory_works_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.remove_label = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.add_labels = AsyncMock()  # type: ignore[method-assign]
        endpoint = self._find_endpoint(
            router, "/api/hitl/{issue_number}/approve-memory"
        )
        response = await endpoint(42)
        data = json.loads(response.body)
        assert data["status"] == "ok"


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
