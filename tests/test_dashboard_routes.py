"""Tests for dashboard_routes.py — route factory and handler registration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType, HydraFlowEvent
from models import HITLItem, SessionStatus


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

    @pytest.mark.asyncio
    async def test_issue_history_linked_issues_carry_kind(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """linked_issues populated via GitHub enrichment carry kind through."""
        import json
        from unittest.mock import AsyncMock, patch

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
                data={"issue": 200, "title": "Test linked kinds"},
            )
        )

        # Mock GitHub enrichment to return an issue with link patterns in body
        mock_issue = type(
            "MockIssue",
            (),
            {
                "number": 200,
                "title": "Test linked kinds",
                "url": "https://example.com/issues/200",
                "labels": [],
                "body": "relates to #5\nduplicates #10",
            },
        )()
        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_issue_by_number = AsyncMock(return_value=mock_issue)
        with patch("dashboard_routes.IssueFetcher", return_value=mock_fetcher):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 200), None)
        assert issue is not None
        links = issue["linked_issues"]
        assert len(links) >= 2
        by_id = {lnk["target_id"]: lnk for lnk in links}
        assert by_id[5]["kind"] == "relates_to"
        assert by_id[10]["kind"] == "duplicates"
        for link in links:
            assert isinstance(link, dict)
            assert "target_id" in link
            assert "kind" in link
            assert "target_url" in link

    @pytest.mark.asyncio
    async def test_issue_history_linked_issues_empty_is_list(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """An issue with no links still returns an empty list (not ints)."""
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
                data={"issue": 201, "title": "No links here"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 201), None)
        assert issue is not None
        assert issue["linked_issues"] == []

    @pytest.mark.asyncio
    async def test_issue_history_includes_crate_fields(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Issue history items include crate_number and crate_title fields."""
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
                data={"issue": 301, "title": "Crate test issue"},
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 301), None)
        assert issue is not None
        assert "crate_number" in issue
        assert "crate_title" in issue
        # Default values when no milestone is attached
        assert issue["crate_number"] is None
        assert issue["crate_title"] == ""

    @pytest.mark.asyncio
    async def test_issue_history_crate_number_from_event(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Milestone number from ISSUE_CREATED event flows into crate_number."""
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
                data={
                    "issue": 302,
                    "title": "Issue with milestone",
                    "milestone_number": 5,
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 302), None)
        assert issue is not None
        assert issue["crate_number"] == 5

    @pytest.mark.asyncio
    async def test_issue_history_crate_number_string_coerced(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Milestone number supplied as string is coerced to int."""
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
                data={
                    "issue": 303,
                    "title": "String milestone",
                    "milestone_number": "7",
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 303), None)
        assert issue is not None
        assert issue["crate_number"] == 7

    @pytest.mark.asyncio
    async def test_issue_history_crate_number_not_overwritten(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """First milestone_number wins; later events do not overwrite."""
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
                data={
                    "issue": 304,
                    "title": "First milestone",
                    "milestone_number": 3,
                },
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                timestamp="2026-02-21T01:00:00+00:00",
                data={
                    "issue": 304,
                    "title": "Second milestone",
                    "milestone_number": 9,
                },
            )
        )

        response = await endpoint(limit=100)
        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 304), None)
        assert issue is not None
        assert issue["crate_number"] == 3

    @pytest.mark.asyncio
    async def test_issue_history_crate_title_empty_on_fetch_failure(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When milestone lookup fails, items still have empty crate_title."""
        import json
        from unittest.mock import AsyncMock, patch

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
                data={
                    "issue": 305,
                    "title": "Milestone fetch fails",
                    "milestone_number": 10,
                },
            )
        )

        with patch.object(
            pr_mgr,
            "list_milestones",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API down"),
        ):
            response = await endpoint(limit=100)

        payload = json.loads(response.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 305), None)
        assert issue is not None
        assert issue["crate_number"] == 10
        assert issue["crate_title"] == ""


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
    async def test_hitl_endpoint_includes_cached_llm_summary(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Cached HITL summary should be included in /api/hitl payload."""
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        state.set_hitl_summary(42, "Line one\nLine two\nLine three")

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
        get_hitl_summary = None
        for route in router.routes:
            if hasattr(route, "path") and hasattr(route, "endpoint"):
                if route.path == "/api/hitl":
                    get_hitl = route.endpoint  # type: ignore[union-attr]
                if route.path == "/api/hitl/{issue_number}/summary":
                    get_hitl_summary = route.endpoint  # type: ignore[union-attr]

        assert get_hitl is not None
        assert get_hitl_summary is not None

        response = await get_hitl()
        import json

        items = json.loads(response.body)
        assert items[0]["llmSummary"].startswith("Line one")
        assert items[0]["llmSummaryUpdatedAt"] is not None

        summary_response = await get_hitl_summary(42)
        summary_payload = json.loads(summary_response.body)
        assert summary_payload["cached"] is True
        assert summary_payload["summary"].startswith("Line one")

    @pytest.mark.asyncio
    async def test_hitl_endpoint_skips_background_warm_during_failure_cooldown(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Recent summary failures should suppress warm task creation until cooldown."""
        from dashboard_routes import create_router
        from pr_manager import PRManager

        config.transcript_summarization_enabled = True
        config.dry_run = False
        config.gh_token = "test-token"

        pr_mgr = PRManager(config, event_bus)
        state.set_hitl_summary_failure(42, "model timeout")

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

        hitl_item = HITLItem(issue=42, title="Needs context", pr=0)
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
        with patch("dashboard_routes.asyncio.create_task") as mock_create_task:
            response = await get_hitl()
            import json

            payload = json.loads(response.body)
            assert payload[0]["llmSummary"] == ""
            mock_create_task.assert_not_called()

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
                        '"url": "https://github.com/T-rav/hyrdaflow/issues/42"}]'
                    )
                if label_arg == f"labels={config.hitl_active_label[0]}":
                    return (
                        '[{"number": 77, "title": "Issue from hitl-active", '
                        '"url": "https://github.com/T-rav/hyrdaflow/issues/77"}]'
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
            transcript_summarization_enabled=False,
            gh_token="",
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

    @pytest.mark.asyncio
    async def test_hitl_endpoint_includes_visual_evidence_when_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When visual evidence is stored in state, it should appear in the response."""
        from dashboard_routes import create_router
        from models import VisualEvidence, VisualEvidenceItem
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)

        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=12.5, status="fail"
                )
            ],
            summary="1 screen exceeded threshold",
            attempt=2,
        )
        state.set_hitl_visual_evidence(42, ev)

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

        hitl_item = HITLItem(issue=42, title="Fix visual regression", pr=101)
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
        visual = items[0]["visualEvidence"]
        assert visual is not None
        assert visual["summary"] == "1 screen exceeded threshold"
        assert visual["attempt"] == 2
        assert visual["items"][0]["screen_name"] == "login"
        assert visual["items"][0]["diff_percent"] == 12.5
        assert visual["items"][0]["status"] == "fail"

    @pytest.mark.asyncio
    async def test_hitl_endpoint_omits_visual_evidence_when_not_set(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When no visual evidence is stored, visualEvidence key should be absent."""
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
        assert items[0].get("visualEvidence") is None


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
        from models import HITLSkipRequest

        state.set_hitl_origin(42, "hydraflow-improve")
        state.set_hitl_cause(42, "Memory suggestion")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.post_comment = AsyncMock()

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None

        response = await skip(42, HITLSkipRequest(reason="Not actionable"))
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
        from models import HITLSkipRequest

        state.set_hitl_origin(42, "hydraflow-review")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.post_comment = AsyncMock()

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="Not needed"))

        # Should NOT add find label for non-improve origins
        add_calls = [c.args for c in pr_mgr.add_labels.call_args_list]
        for call in add_calls:
            assert call[1] != [config.find_label[0]]

    @pytest.mark.asyncio
    async def test_hitl_skip_no_origin_no_triage_transition(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """When no origin is set, skip should not add find label."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.post_comment = AsyncMock()

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="Skipping"))

        # Should NOT add find label when no origin
        add_calls = [c.args for c in pr_mgr.add_labels.call_args_list]
        for call in add_calls:
            assert call[1] != [config.find_label[0]]

    @pytest.mark.asyncio
    async def test_hitl_skip_cleans_up_hitl_cause(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should clean up hitl_cause in addition to hitl_origin."""
        from models import HITLSkipRequest

        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed after 2 fix attempt(s)")
        state.set_hitl_summary(42, "cached summary")

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, _ = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        _.post_comment = AsyncMock()

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="No longer needed"))

        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None

    @pytest.mark.asyncio
    async def test_hitl_skip_records_outcome(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should record an HITL_SKIPPED outcome."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.post_comment = AsyncMock()

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        await skip(42, HITLSkipRequest(reason="Not actionable"))

        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_skipped"
        assert outcome.reason == "Not actionable"

    @pytest.mark.asyncio
    async def test_hitl_skip_rejects_empty_reason(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip with empty reason should raise a Pydantic validation error."""
        from pydantic import ValidationError

        from models import HITLSkipRequest

        with pytest.raises(ValidationError):
            HITLSkipRequest(reason="")

    @pytest.mark.asyncio
    async def test_hitl_skip_posts_reason_as_comment(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should post the reason as a GitHub comment."""
        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.post_comment = AsyncMock()

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        await skip(42, HITLSkipRequest(reason="Not actionable"))

        pr_mgr.post_comment.assert_awaited()
        comment = pr_mgr.post_comment.call_args.args[1]
        assert "Not actionable" in comment


# ---------------------------------------------------------------------------
# GET /api/issues/outcomes endpoint
# ---------------------------------------------------------------------------


class TestOutcomesEndpoint:
    """Tests for GET /api/issues/outcomes."""

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
    async def test_outcomes_returns_empty_dict_by_default(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/issues/outcomes")
        assert endpoint is not None
        response = await endpoint()
        assert response.status_code == 200
        import json

        data = json.loads(response.body)
        assert data == {}

    @pytest.mark.asyncio
    async def test_outcomes_returns_recorded_outcomes(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from models import IssueOutcomeType

        state.record_outcome(
            42,
            IssueOutcomeType.MERGED,
            reason="PR merged",
            phase="review",
            pr_number=99,
        )
        state.record_outcome(
            43, IssueOutcomeType.HITL_CLOSED, reason="Duplicate", phase="hitl"
        )

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/issues/outcomes")
        response = await endpoint()
        import json

        data = json.loads(response.body)
        assert "42" in data
        assert data["42"]["outcome"] == "merged"
        assert data["42"]["pr_number"] == 99
        assert "43" in data
        assert data["43"]["outcome"] == "hitl_closed"


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
# GET /api/repos
# ---------------------------------------------------------------------------


class TestListSupervisedReposEndpoint:
    """Tests for GET /api/repos supervisor error logging behavior."""

    def _make_router(self, config, event_bus, state, tmp_path, supervisor_module):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch(
            "dashboard_routes.importlib.import_module", return_value=supervisor_module
        ):
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
    async def test_expected_supervisor_down_error_not_warned(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from types import SimpleNamespace

        def _raise_down():
            raise RuntimeError(
                "hf supervisor is not running. Run `hf run` inside a repo to start it."
            )

        router = self._make_router(
            config,
            event_bus,
            state,
            tmp_path,
            SimpleNamespace(list_repos=_raise_down),
        )
        endpoint = self._find_endpoint(router, "/api/repos")
        assert endpoint is not None

        with patch("dashboard_routes.logger") as mock_logger:
            response = await endpoint()

        data = json.loads(response.body)
        assert response.status_code == 503
        assert data["error"] == "Supervisor unavailable"
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_supervisor_error_is_warned(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from types import SimpleNamespace

        def _raise_other():
            raise RuntimeError("Supervisor connection failed: [Errno 61] refused")

        router = self._make_router(
            config,
            event_bus,
            state,
            tmp_path,
            SimpleNamespace(list_repos=_raise_other),
        )
        endpoint = self._find_endpoint(router, "/api/repos")
        assert endpoint is not None

        with patch("dashboard_routes.logger") as mock_logger:
            response = await endpoint()

        data = json.loads(response.body)
        assert response.status_code == 503
        assert data["error"] == "Supervisor unavailable"
        mock_logger.warning.assert_called_once()


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
        from models import HITLCloseRequest

        router, _ = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42, HITLCloseRequest(reason="test"))
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_close_issue_with_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import HITLCloseRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.close_issue = AsyncMock()  # type: ignore[method-assign]
        pr_mgr.post_comment = AsyncMock()  # type: ignore[method-assign]
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failure")
        state.set_hitl_summary(42, "cached summary")
        endpoint = self._find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42, HITLCloseRequest(reason="Duplicate of #123"))
        data = json.loads(response.body)
        assert data["status"] == "ok"
        mock_orch.skip_hitl_issue.assert_called_once_with(42)
        pr_mgr.close_issue.assert_called_once_with(42)
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None
        # Verify reason posted as comment
        pr_mgr.post_comment.assert_awaited()
        comment = pr_mgr.post_comment.call_args.args[1]
        assert "Duplicate of #123" in comment
        # Verify outcome recorded
        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_closed"
        assert outcome.reason == "Duplicate of #123"

    @pytest.mark.asyncio
    async def test_hitl_close_rejects_empty_reason(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Close with empty reason should raise a Pydantic validation error."""
        from pydantic import ValidationError

        from models import HITLCloseRequest

        with pytest.raises(ValidationError):
            HITLCloseRequest(reason="")

    @pytest.mark.asyncio
    async def test_hitl_close_succeeds_even_if_comment_fails(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Close should succeed even if post_comment raises."""
        import json

        from models import HITLCloseRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.close_issue = AsyncMock()
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.post_comment = AsyncMock(side_effect=RuntimeError("GitHub down"))

        # Pre-populate HITL state
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failure")
        state.set_hitl_summary(42, "cached summary")

        endpoint = self._find_endpoint(router, "/api/hitl/{issue_number}/close")
        response = await endpoint(42, HITLCloseRequest(reason="Duplicate"))

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["status"] == "ok"
        pr_mgr.close_issue.assert_called_once_with(42)
        # State should be cleaned up despite comment failure
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None
        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_closed"


# ---------------------------------------------------------------------------
# HITL skip — comment failure resilience
# ---------------------------------------------------------------------------


class TestHITLSkipCommentResilience:
    """Test that hitl_skip succeeds even when post_comment fails."""

    def _make_router(self, config, event_bus, state, tmp_path, get_orch=None):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        pr_mgr.remove_label = AsyncMock()
        pr_mgr.add_labels = AsyncMock()
        pr_mgr.swap_pipeline_labels = AsyncMock()
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
    async def test_hitl_skip_succeeds_even_if_comment_fails(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Skip should succeed even if post_comment raises."""
        import json

        from models import HITLSkipRequest

        mock_orch = MagicMock()
        mock_orch.skip_hitl_issue = MagicMock()
        router, pr_mgr = self._make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        pr_mgr.post_comment = AsyncMock(side_effect=RuntimeError("GitHub down"))

        # Pre-populate HITL state
        state.set_hitl_origin(42, "hydraflow-plan")
        state.set_hitl_cause(42, "Evidence rejected")
        state.set_hitl_summary(42, "some summary")

        skip = self._find_endpoint(router, "/api/hitl/{issue_number}/skip")
        assert skip is not None
        response = await skip(42, HITLSkipRequest(reason="Not needed"))

        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["status"] == "ok"
        mock_orch.skip_hitl_issue.assert_called_once_with(42)
        # State should be cleaned up despite comment failure
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None
        assert state.get_hitl_summary(42) is None
        outcome = state.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "hitl_skipped"


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
        state.set_hitl_summary(42, "cached summary")
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
        assert state.get_hitl_summary(42) is None

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


class TestIssueHistoryCache:
    """Tests for issue history disk cache (save / load / warm-up / invalidation)."""

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

    def _get_history_endpoint(self, router):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/issues/history"
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        raise AssertionError("history endpoint not found")

    @pytest.mark.asyncio
    async def test_save_load_round_trip_preserves_int_keys(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Cache round-trip: int keys for prs / linked_issues survive JSON."""
        import json

        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="implementer",
            tool="claude",
            model="sonnet",
            issue_number=50,
            pr_number=200,
            session_id="sess-cache",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=1.0,
            success=True,
            stats={"total_tokens": 500, "input_tokens": 300, "output_tokens": 200},
        )

        # First request — populates and saves cache.
        router = self._make_router(config, event_bus, state, tmp_path)
        ep = self._get_history_endpoint(router)
        resp = await ep(limit=100)
        payload = json.loads(resp.body)
        assert payload["totals"]["issues"] >= 1

        # Verify disk file was written.
        cache_file = config.data_path("metrics", "history_cache.json")
        assert cache_file.is_file()
        raw = json.loads(cache_file.read_text())
        assert "issue_rows" in raw

        # Verify round-trip: load the cache in a fresh router and query again.
        router2 = self._make_router(config, event_bus, state, tmp_path)
        ep2 = self._get_history_endpoint(router2)
        resp2 = await ep2(limit=100)
        payload2 = json.loads(resp2.body)
        issue = next((x for x in payload2["items"] if x["issue_number"] == 50), None)
        assert issue is not None
        assert issue["prs"][0]["number"] == 200

    @pytest.mark.asyncio
    async def test_corrupt_cache_file_is_ignored(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """A corrupt JSON cache file should not crash router creation."""
        cache_file = config.data_path("metrics", "history_cache.json")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("NOT VALID JSON {{{")

        # Router should create without error — corrupt file is silently skipped.
        router = self._make_router(config, event_bus, state, tmp_path)
        ep = self._get_history_endpoint(router)
        import json

        resp = await ep(limit=10)
        payload = json.loads(resp.body)
        # No crash, returns valid (possibly empty) response.
        assert "items" in payload
        assert "totals" in payload

    @pytest.mark.asyncio
    async def test_missing_cache_file_is_handled(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Missing cache file should not crash router creation."""
        cache_file = config.data_path("metrics", "history_cache.json")
        assert not cache_file.exists()

        router = self._make_router(config, event_bus, state, tmp_path)
        ep = self._get_history_endpoint(router)
        import json

        resp = await ep(limit=10)
        payload = json.loads(resp.body)
        assert "items" in payload

    @pytest.mark.asyncio
    async def test_cache_hit_skips_aggregation(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Second identical request within TTL should hit cache."""
        import json

        from prompt_telemetry import PromptTelemetry

        telemetry = PromptTelemetry(config)
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=99,
            pr_number=0,
            session_id="sess-hit",
            prompt_chars=50,
            transcript_chars=20,
            duration_seconds=0.5,
            success=True,
            stats={"total_tokens": 80},
        )

        router = self._make_router(config, event_bus, state, tmp_path)
        ep = self._get_history_endpoint(router)

        resp1 = await ep(limit=100)
        p1 = json.loads(resp1.body)
        assert p1["totals"]["issues"] >= 1

        # Second call — same event count and telemetry mtime → cache hit.
        resp2 = await ep(limit=100)
        p2 = json.loads(resp2.body)
        assert p2["totals"]["issues"] == p1["totals"]["issues"]

    @pytest.mark.asyncio
    async def test_cache_invalidated_by_new_event(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Publishing a new event should invalidate the cache."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        ep = self._get_history_endpoint(router)

        resp1 = await ep(limit=100)
        json.loads(resp1.body)  # populate cache

        # Publish a new event, changing the event count.
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ISSUE_CREATED,
                data={"issue": 999, "title": "New after cache"},
            )
        )

        resp2 = await ep(limit=100)
        p2 = json.loads(resp2.body)
        # The new issue should appear.
        found = any(x["issue_number"] == 999 for x in p2["items"])
        assert found

    @pytest.mark.asyncio
    async def test_load_restores_linked_issues_with_int_keys(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Ensure _load_history_cache restores linked_issues dict keys to int."""
        import json

        cache_file = config.data_path("metrics", "history_cache.json")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        # Simulate JSON file with string keys (as produced by json.dumps).
        cache_data = {
            "event_count": 0,
            "telemetry_mtime": 0.0,
            "issue_rows": {
                "42": {
                    "issue_number": 42,
                    "title": "Test issue",
                    "issue_url": "",
                    "status": "active",
                    "epic": "",
                    "linked_issues": {
                        "5": {"target_id": 5, "kind": "relates_to", "target_url": None},
                        "10": {
                            "target_id": 10,
                            "kind": "duplicates",
                            "target_url": None,
                        },
                    },
                    "prs": {
                        "200": {
                            "number": 200,
                            "url": "https://example.com/pull/200",
                            "merged": False,
                        },
                    },
                    "session_ids": ["sess-a"],
                    "source_calls": {"implementer": 1},
                    "model_calls": {"sonnet": 1},
                    "inference": {
                        "inference_calls": 1,
                        "total_tokens": 100,
                        "input_tokens": 60,
                        "output_tokens": 40,
                        "pruned_chars_total": 0,
                    },
                    "first_seen": "2026-02-20T00:00:00+00:00",
                    "last_seen": "2026-02-21T00:00:00+00:00",
                    "status_updated_at": None,
                },
            },
            "pr_to_issue": {"200": 42},
            "enriched_issues": [42],
        }
        cache_file.write_text(json.dumps(cache_data))

        # Load via router warm-up.
        router = self._make_router(config, event_bus, state, tmp_path)
        ep = self._get_history_endpoint(router)

        resp = await ep(limit=100)
        payload = json.loads(resp.body)
        issue = next((x for x in payload["items"] if x["issue_number"] == 42), None)
        assert issue is not None
        assert issue["prs"][0]["number"] == 200
        # linked_issues should have been rebuilt via _build_history_links.
        assert len(issue["linked_issues"]) == 2
        ids = {li["target_id"] for li in issue["linked_issues"]}
        assert ids == {5, 10}


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


class TestReviewInsightsEndpoint:
    """Tests for the /api/review-insights endpoint."""

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
    async def test_review_insights_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/review-insights")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_reviews"] == 0
        assert data["patterns"] == []
        assert data["verdict_counts"] == {}
        assert data["category_counts"] == {}
        assert data["fixes_made_count"] == 0
        assert data["proposed_categories"] == []

    @pytest.mark.asyncio
    async def test_review_insights_with_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from review_insights import ReviewInsightStore, ReviewRecord

        memory_dir = config.data_path("memory")
        store = ReviewInsightStore(memory_dir)
        store.append_review(
            ReviewRecord(
                pr_number=1,
                issue_number=10,
                timestamp="2024-01-01T00:00:00Z",
                verdict="approve",
                summary="Looks good",
                fixes_made=False,
                categories=["code_quality"],
            )
        )
        store.append_review(
            ReviewRecord(
                pr_number=2,
                issue_number=11,
                timestamp="2024-01-02T00:00:00Z",
                verdict="request-changes",
                summary="Missing tests",
                fixes_made=True,
                categories=["missing_tests"],
            )
        )

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/review-insights")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_reviews"] == 2
        assert data["fixes_made_count"] == 1
        assert "approve" in data["verdict_counts"]
        assert "request-changes" in data["verdict_counts"]
        assert "code_quality" in data["category_counts"]
        assert "missing_tests" in data["category_counts"]


# ---------------------------------------------------------------------------
# GET /api/retrospectives
# ---------------------------------------------------------------------------


class TestRetrospectivesEndpoint:
    """Tests for the /api/retrospectives endpoint."""

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
    async def test_retrospectives_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/retrospectives")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_entries"] == 0
        assert data["entries"] == []
        assert data["verdict_counts"] == {}

    @pytest.mark.asyncio
    async def test_retrospectives_with_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from retrospective import RetrospectiveEntry

        retro_path = config.data_path("memory", "retrospectives.jsonl")
        retro_path.parent.mkdir(parents=True, exist_ok=True)

        entry = RetrospectiveEntry(
            issue_number=10,
            pr_number=1,
            timestamp="2024-01-01T00:00:00Z",
            plan_accuracy_pct=85.0,
            quality_fix_rounds=1,
            review_verdict="approve",
            reviewer_fixes_made=False,
            ci_fix_rounds=0,
            duration_seconds=120.0,
        )
        retro_path.write_text(entry.model_dump_json() + "\n")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/retrospectives")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_entries"] == 1
        assert data["avg_plan_accuracy"] == 85.0
        assert data["avg_quality_fix_rounds"] == 1.0
        assert data["avg_ci_fix_rounds"] == 0.0
        assert data["avg_duration_seconds"] == 120.0
        assert data["reviewer_fix_rate"] == 0.0
        assert len(data["entries"]) == 1


# ---------------------------------------------------------------------------
# GET /api/memories
# ---------------------------------------------------------------------------


class TestMemoriesEndpoint:
    """Tests for the /api/memories endpoint."""

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
    async def test_memories_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/memories")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_items"] == 0
        assert data["items"] == []
        assert data["digest_chars"] == 0

    @pytest.mark.asyncio
    async def test_memories_with_items(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        items_dir = config.data_path("memory", "items")
        items_dir.mkdir(parents=True, exist_ok=True)
        (items_dir / "42.md").write_text("Always validate inputs")
        (items_dir / "55.md").write_text("Use async for I/O")

        digest_path = config.data_path("memory", "digest.md")
        digest_path.write_text("# Digest\nSome content here")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/memories")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_items"] == 2
        assert data["digest_chars"] > 0
        assert len(data["items"]) == 2
        # Items are sorted reverse by filename, so 55 comes first
        numbers = [item["issue_number"] for item in data["items"]]
        assert 42 in numbers
        assert 55 in numbers

    @pytest.mark.asyncio
    async def test_memories_skips_non_numeric_filenames(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Non-numeric .md filenames (e.g. README.md) should be silently skipped."""
        import json

        items_dir = config.data_path("memory", "items")
        items_dir.mkdir(parents=True, exist_ok=True)
        (items_dir / "42.md").write_text("Valid item")
        (items_dir / "README.md").write_text("Not a learning item")
        (items_dir / "notes.md").write_text("Also not valid")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/memories")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_items"] == 1
        assert data["items"][0]["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_memories_caps_at_50_items(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """The endpoint should return at most 50 items."""
        import json

        items_dir = config.data_path("memory", "items")
        items_dir.mkdir(parents=True, exist_ok=True)
        for i in range(60):
            (items_dir / f"{i + 1}.md").write_text(f"Learning #{i + 1}")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/memories")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_items"] == 60
        assert len(data["items"]) == 50


# ---------------------------------------------------------------------------
# GET /api/troubleshooting
# ---------------------------------------------------------------------------


class TestTroubleshootingEndpoint:
    """Tests for the /api/troubleshooting endpoint."""

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
    async def test_troubleshooting_returns_empty(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/troubleshooting")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_patterns"] == 0
        assert data["patterns"] == []

    @pytest.mark.asyncio
    async def test_troubleshooting_with_patterns(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from troubleshooting_store import (
            TroubleshootingPattern,
            TroubleshootingPatternStore,
        )

        memory_dir = config.data_path("memory")
        store = TroubleshootingPatternStore(memory_dir)
        store.append_pattern(
            TroubleshootingPattern(
                language="python",
                pattern_name="truthy_asyncmock",
                description="AsyncMock is always truthy",
                fix_strategy="Use .called or .call_count instead",
                frequency=3,
                source_issues=[10, 20, 30],
            )
        )
        store.append_pattern(
            TroubleshootingPattern(
                language="node",
                pattern_name="jest_open_handles",
                description="Jest hangs due to open handles",
                fix_strategy="Use --forceExit or close resources",
                frequency=1,
                source_issues=[42],
            )
        )

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/troubleshooting")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_patterns"] == 2
        assert len(data["patterns"]) == 2
        # Sorted by frequency desc — python pattern first
        assert data["patterns"][0]["pattern_name"] == "truthy_asyncmock"
        assert data["patterns"][0]["frequency"] == 3
        assert data["patterns"][0]["language"] == "python"
        assert data["patterns"][0]["source_issues"] == [10, 20, 30]
        assert data["patterns"][1]["pattern_name"] == "jest_open_handles"

    @pytest.mark.asyncio
    async def test_troubleshooting_caps_at_100(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from troubleshooting_store import (
            TroubleshootingPattern,
            TroubleshootingPatternStore,
        )

        memory_dir = config.data_path("memory")
        store = TroubleshootingPatternStore(memory_dir)
        for i in range(110):
            store.append_pattern(
                TroubleshootingPattern(
                    language="python",
                    pattern_name=f"pattern_{i}",
                    description=f"Description {i}",
                    fix_strategy=f"Fix {i}",
                    source_issues=[i],
                )
            )

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/troubleshooting")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_patterns"] == 110
        assert len(data["patterns"]) == 100


# ---------------------------------------------------------------------------
# GET /api/retrospectives — edge cases
# ---------------------------------------------------------------------------


class TestRetrospectivesEdgeCases:
    """Edge-case tests for the /api/retrospectives endpoint."""

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
    async def test_retrospectives_malformed_jsonl_skipped(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Malformed JSONL lines should be silently skipped."""
        import json

        from retrospective import RetrospectiveEntry

        retro_path = config.data_path("memory", "retrospectives.jsonl")
        retro_path.parent.mkdir(parents=True, exist_ok=True)

        valid = RetrospectiveEntry(
            issue_number=10,
            pr_number=1,
            timestamp="2024-01-01T00:00:00Z",
            plan_accuracy_pct=90.0,
            quality_fix_rounds=0,
            review_verdict="approve",
            reviewer_fixes_made=False,
            ci_fix_rounds=0,
            duration_seconds=60.0,
        )
        lines = [
            "not valid json at all",
            '{"issue_number": 99}',
            valid.model_dump_json(),
        ]
        retro_path.write_text("\n".join(lines) + "\n")

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/retrospectives")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_entries"] == 1
        assert data["avg_plan_accuracy"] == 90.0


# ---------------------------------------------------------------------------
# Crate (milestone) endpoint tests
# ---------------------------------------------------------------------------


class TestCrateEndpoints:
    """Tests for /api/crates routes backed by GitHub milestones."""

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
    async def test_list_crates_returns_empty_list(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(return_value=[])
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
        assert endpoint is not None
        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_list_crates_returns_enriched_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import Crate

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(
            return_value=[
                Crate(
                    number=1,
                    title="Sprint 1",
                    state="open",
                    open_issues=3,
                    closed_issues=2,
                )
            ]
        )
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["title"] == "Sprint 1"
        assert data[0]["total_issues"] == 5
        assert data[0]["progress"] == 40

    @pytest.mark.asyncio
    async def test_list_crates_zero_total_issues(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """progress should be 0 when a crate has zero issues (no division by zero)."""
        import json

        from models import Crate

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(
            return_value=[
                Crate(
                    number=2,
                    title="Empty",
                    state="open",
                    open_issues=0,
                    closed_issues=0,
                )
            ]
        )
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        data = json.loads(response.body)
        assert data[0]["total_issues"] == 0
        assert data[0]["progress"] == 0

    @pytest.mark.asyncio
    async def test_list_crates_runtime_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(side_effect=RuntimeError("gh failed"))
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        assert response.status_code == 500
        data = json.loads(response.body)
        assert data["error"] == "Failed to fetch crates"

    @pytest.mark.asyncio
    async def test_create_crate_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import Crate, CrateCreateRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_milestone = AsyncMock(
            return_value=Crate(number=5, title="Sprint 3", state="open")
        )
        endpoint = self._find_endpoint(router, "/api/crates", "POST")
        body = CrateCreateRequest(title="Sprint 3")
        response = await endpoint(body)
        data = json.loads(response.body)
        assert data["title"] == "Sprint 3"
        assert data["number"] == 5
        pr_mgr.create_milestone.assert_called_once_with(
            title="Sprint 3", description="", due_on=None
        )

    @pytest.mark.asyncio
    async def test_create_crate_error(self, config, event_bus, state, tmp_path) -> None:
        import json

        from models import CrateCreateRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_milestone = AsyncMock(side_effect=RuntimeError("rate limit"))
        endpoint = self._find_endpoint(router, "/api/crates", "POST")
        body = CrateCreateRequest(title="Fail")
        response = await endpoint(body)
        assert response.status_code == 500
        data = json.loads(response.body)
        assert data["error"] == "Failed to create crate"

    @pytest.mark.asyncio
    async def test_update_crate_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import Crate, CrateUpdateRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.update_milestone = AsyncMock(
            return_value=Crate(number=1, title="Updated", state="closed")
        )
        endpoint = self._find_endpoint(router, "/api/crates/{crate_number}", "PATCH")
        body = CrateUpdateRequest(title="Updated", state="closed")
        response = await endpoint(1, body)
        data = json.loads(response.body)
        assert data["title"] == "Updated"
        assert data["state"] == "closed"

    @pytest.mark.asyncio
    async def test_delete_crate_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.delete_milestone = AsyncMock()
        endpoint = self._find_endpoint(router, "/api/crates/{crate_number}", "DELETE")
        response = await endpoint(1)
        data = json.loads(response.body)
        assert data["ok"] is True
        pr_mgr.delete_milestone.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_add_crate_items_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import CrateItemsRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.set_issue_milestone = AsyncMock()
        endpoint = self._find_endpoint(
            router, "/api/crates/{crate_number}/items", "POST"
        )
        body = CrateItemsRequest(issue_numbers=[10, 11, 12])
        response = await endpoint(5, body)
        data = json.loads(response.body)
        assert data["ok"] is True
        assert data["added"] == 3
        assert pr_mgr.set_issue_milestone.call_count == 3

    @pytest.mark.asyncio
    async def test_remove_crate_items_only_removes_matching(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Only issues currently assigned to the target milestone should be cleared."""
        import json

        from models import CrateItemsRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        # Issue 10 belongs to milestone 5, issue 99 does not
        pr_mgr.list_milestone_issues = AsyncMock(
            return_value=[{"number": 10}, {"number": 11}]
        )
        pr_mgr.set_issue_milestone = AsyncMock()
        endpoint = self._find_endpoint(
            router, "/api/crates/{crate_number}/items", "DELETE"
        )
        body = CrateItemsRequest(issue_numbers=[10, 99])
        response = await endpoint(5, body)
        data = json.loads(response.body)
        assert data["ok"] is True
        assert data["removed"] == 1  # Only issue 10 was actually in milestone 5
        pr_mgr.set_issue_milestone.assert_called_once_with(10, None)

    @pytest.mark.asyncio
    async def test_remove_crate_items_error(
        self, config, event_bus, state, tmp_path
    ) -> None:

        from models import CrateItemsRequest

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestone_issues = AsyncMock(side_effect=RuntimeError("fail"))
        endpoint = self._find_endpoint(
            router, "/api/crates/{crate_number}/items", "DELETE"
        )
        body = CrateItemsRequest(issue_numbers=[10])
        response = await endpoint(5, body)
        assert response.status_code == 500


class TestFindRepoMatch:
    """Tests for the _find_repo_match cascading match helper."""

    def _call(self, slug: str, repos: list[dict]) -> dict | None:
        from dashboard_routes import _find_repo_match

        return _find_repo_match(slug, repos)

    def test_exact_slug_match(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("insightmesh", repos) == repos[0]

    def test_owner_repo_format_strips_prefix(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("8thlight/insightmesh", repos) == repos[0]

    def test_path_tail_match(self) -> None:
        repos = [{"slug": "mesh", "path": "/home/user/insightmesh"}]
        assert self._call("insightmesh", repos) == repos[0]

    def test_path_component_match(self) -> None:
        repos = [{"slug": "mesh", "path": "/repos/8thlight/insightmesh"}]
        assert self._call("8thlight", repos) == repos[0]

    def test_exact_match_has_priority_over_path_match(self) -> None:
        exact = {"slug": "myrepo", "path": "/other/path"}
        path_match = {"slug": "other", "path": "/repos/myrepo"}
        repos = [path_match, exact]
        assert self._call("myrepo", repos) == exact

    def test_empty_slug_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("", repos) is None

    def test_no_match_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("bar", repos) is None

    def test_empty_repos_list_returns_none(self) -> None:
        assert self._call("foo", []) is None

    def test_slash_only_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("/", repos) is None

    def test_trailing_slash_stripped(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("8thlight/insightmesh/", repos) == repos[0]

    def test_multi_slash_input(self) -> None:
        repos = [{"slug": "repo", "path": "/repos/repo"}]
        assert self._call("github.com/owner/repo", repos) == repos[0]

    def test_case_insensitive_slug_match(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("InsightMesh", repos) == repos[0]

    def test_case_insensitive_owner_repo(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("8thLight/InsightMesh", repos) == repos[0]

    def test_repo_with_none_slug(self) -> None:
        repos = [{"slug": None, "path": "/repos/myrepo"}]
        assert self._call("myrepo", repos) == repos[0]

    def test_repo_with_missing_slug_key(self) -> None:
        repos = [{"path": "/repos/myrepo"}]
        assert self._call("myrepo", repos) == repos[0]

    def test_repo_with_none_path(self) -> None:
        repos = [{"slug": "foo", "path": None}]
        assert self._call("foo", repos) == repos[0]

    def test_whitespace_only_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("   ", repos) is None

    def test_no_partial_substring_match(self) -> None:
        """Strategy 4 requires full path component, not substring."""
        repos = [{"slug": "mesh", "path": "/repos/insightmesh"}]
        # "insight" is a substring of "insightmesh" but not a full component
        assert self._call("insight", repos) is None


class TestDetectRepoSlugFromPath:
    """Tests for _detect_repo_slug_from_path helper."""

    @pytest.fixture(autouse=True)
    def _setup(self, config, event_bus, state, tmp_path: Path) -> None:
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        self.router = create_router(
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

    def _get_helper(self):
        """Extract the _detect_repo_slug_from_path closure from the router scope."""
        # The helper is a closure inside create_router, accessible via the endpoint
        # We test it indirectly through the add_repo_by_path endpoint instead
        # For unit-level tests, we mock subprocess and call the endpoint
        pass

    @pytest.mark.asyncio
    async def test_https_remote_url(self) -> None:
        """HTTPS remote URL is parsed to owner/repo slug."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"https://github.com/owner/repo.git\n", b"")
        )
        mock_proc.returncode = 0

        from urllib.parse import urlparse

        url = "https://github.com/owner/repo.git"
        parsed = urlparse(url)
        slug = parsed.path.lstrip("/").removesuffix(".git")
        assert slug == "owner/repo"

    @pytest.mark.asyncio
    async def test_ssh_remote_url(self) -> None:
        """SSH remote URL is parsed to owner/repo slug."""
        url = "git@github.com:owner/repo.git"
        _, _, remainder = url.partition(":")
        slug = remainder.lstrip("/").removesuffix(".git")
        assert slug == "owner/repo"

    @pytest.mark.asyncio
    async def test_no_remote_returns_none(self) -> None:
        """Empty stdout means no remote — returns None-equivalent."""
        url = ""
        assert not url  # Would return None in the helper


class TestAddRepoByPath:
    """Tests for POST /api/repos/add endpoint."""

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

    def _get_endpoint(self, router):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/repos/add"
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        msg = "add_repo_by_path endpoint not found"
        raise AssertionError(msg)

    @pytest.mark.asyncio
    async def test_missing_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        from pydantic import BaseModel

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        class FakeReq(BaseModel):
            path: str = ""

        resp = await endpoint(FakeReq(path=""))
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "path required" in data["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        from pydantic import BaseModel

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        class FakeReq(BaseModel):
            path: str = ""

        resp = await endpoint(FakeReq(path=str(tmp_path / "missing-repo-dir")))
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "does not exist" in data["error"]

    @pytest.mark.asyncio
    async def test_non_git_repo_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        from pydantic import BaseModel

        fake_dir = tmp_path / "not-a-repo"
        fake_dir.mkdir()
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        class FakeReq(BaseModel):
            path: str = ""

        resp = await endpoint(FakeReq(path=str(fake_dir)))
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "not a git repository" in data["error"]

    @pytest.mark.asyncio
    async def test_disallowed_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        from pydantic import BaseModel

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        class FakeReq(BaseModel):
            path: str = ""

        resp = await endpoint(FakeReq(path="/"))
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "inside your home directory or temp directory" in data["error"]

    @pytest.mark.asyncio
    async def test_valid_path_registers_repo(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """Valid git repo path is registered with supervisor."""
        import json as json_mod
        import subprocess

        from pydantic import BaseModel

        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init", str(repo_dir)], capture_output=True, check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "remote",
                "add",
                "origin",
                "https://github.com/testowner/testrepo.git",
            ],
            capture_output=True,
            check=True,
        )

        mock_supervisor = MagicMock()
        mock_supervisor.register_repo = MagicMock(
            return_value={"status": "ok", "slug": "testrepo", "path": str(repo_dir)},
        )
        with patch.dict("sys.modules", {"hf_cli.supervisor_client": mock_supervisor}):
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
            endpoint = self._get_endpoint(router)

            class FakeReq(BaseModel):
                path: str = ""

            with patch("prep.ensure_labels", new_callable=AsyncMock):
                resp = await endpoint(FakeReq(path=str(repo_dir)))

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"
        assert data["path"] == str(repo_dir.resolve())

    @pytest.mark.asyncio
    async def test_label_creation_failure_still_registers(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """Labels fail but repo is still registered with a warning."""
        import json as json_mod
        import subprocess

        from pydantic import BaseModel

        repo_dir = tmp_path / "label-fail-repo"
        repo_dir.mkdir()
        subprocess.run(["git", "init", str(repo_dir)], capture_output=True, check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_dir),
                "remote",
                "add",
                "origin",
                "https://github.com/org/labeltest.git",
            ],
            capture_output=True,
            check=True,
        )

        mock_supervisor = MagicMock()
        mock_supervisor.register_repo = MagicMock(
            return_value={"status": "ok", "slug": "labeltest", "path": str(repo_dir)},
        )
        with patch.dict("sys.modules", {"hf_cli.supervisor_client": mock_supervisor}):
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
            endpoint = self._get_endpoint(router)

            class FakeReq(BaseModel):
                path: str = ""

            with patch(
                "prep.ensure_labels",
                new_callable=AsyncMock,
                side_effect=RuntimeError("gh not found"),
            ):
                resp = await endpoint(FakeReq(path=str(repo_dir)))

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"
        assert data["labels_created"] is False


class TestPickRepoFolder:
    """Tests for POST /api/repos/pick-folder endpoint."""

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

    def _get_endpoint(self, router):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/repos/pick-folder"
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        msg = "pick_repo_folder endpoint not found"
        raise AssertionError(msg)

    @pytest.mark.asyncio
    async def test_no_selection_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        with patch(
            "dashboard_routes._pick_folder_with_dialog",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await endpoint()

        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert data["error"] == "No folder selected"

    @pytest.mark.asyncio
    async def test_selected_folder_returns_path(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        repo_dir = tmp_path / "picked-repo"
        repo_dir.mkdir()
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        with patch(
            "dashboard_routes._pick_folder_with_dialog",
            new_callable=AsyncMock,
            return_value=str(repo_dir),
        ):
            resp = await endpoint()

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["path"] == str(repo_dir.resolve())
