"""Tests for dashboard_routes.py — state, stats, queue, events, PRs, sessions, timeline, pipeline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus
from models import SessionStatus


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


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


# ---------------------------------------------------------------------------
# GET /api/repos
# ---------------------------------------------------------------------------


class TestListSupervisedReposEndpoint:
    """Tests for GET /api/repos when supervisor is unavailable (issue #2205)."""

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
    async def test_returns_empty_repos_when_supervisor_unavailable(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """With supervisor_client=None and no repo_store, GET /api/repos returns []."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/repos")
        assert endpoint is not None

        response = await endpoint()

        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["repos"] == []

    @pytest.mark.asyncio
    async def test_no_warning_logged_when_supervisor_unavailable(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """No warning should be logged for the normal no-supervisor path."""
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_endpoint(router, "/api/repos")
        assert endpoint is not None

        with patch("dashboard_routes.logger") as mock_logger:
            await endpoint()

        mock_logger.warning.assert_not_called()


class TestEnsureRepoCompatibilityEndpoint:
    """Compatibility tests for POST /api/repos when supervisor is unavailable (issue #2205)."""

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

    def _find_post_endpoint(self, router, path):
        for route in router.routes:
            methods = getattr(route, "methods", set())
            if (
                hasattr(route, "path")
                and route.path == path
                and "POST" in methods
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_returns_503_when_supervisor_unavailable(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """With supervisor_client=None, POST /api/repos returns 503."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_post_endpoint(router, "/api/repos")
        assert endpoint is not None

        resp = await endpoint(
            req=None,
            req_query="8thlight/insightmesh",
            slug=None,
            repo=None,
        )
        data = json.loads(resp.body)
        assert resp.status_code == 503
        assert data["error"] == "supervisor unavailable"

    @pytest.mark.asyncio
    async def test_json_slug_also_returns_503(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """JSON-formatted slug also gets 503 when supervisor is unavailable."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._find_post_endpoint(router, "/api/repos")
        assert endpoint is not None

        resp = await endpoint(
            req=None,
            req_query='{"slug":"8thlight/insightmesh"}',
            slug=None,
            repo=None,
        )
        data = json.loads(resp.body)
        assert resp.status_code == 503
        assert data["error"] == "supervisor unavailable"


# ---------------------------------------------------------------------------
# GET /api/sessions and /api/sessions/{session_id}
# ---------------------------------------------------------------------------


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
# GET /api/timeline and /api/timeline/issue/{issue_number}
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/timeline and /api/timeline/issue/{issue_number}
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
    """Tests for GET /api/timeline/issue/{issue_number}."""

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
        endpoint = self._find_endpoint(router, "/api/timeline/issue/{issue_number}")
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
        endpoint = self._find_endpoint(router, "/api/timeline/issue/{issue_number}")
        response = await endpoint(42)
        data = json.loads(response.body)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# GET /api/harness-insights and /api/harness-insights/history
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET /api/memories
# ---------------------------------------------------------------------------


class TestMemoriesEndpoint:
    """Tests for the /api/memories endpoint."""

    def _make_router(self, config, event_bus, state, tmp_path, hindsight=None):
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
            hindsight=hindsight,
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
        from unittest.mock import AsyncMock, MagicMock

        mock_hindsight = AsyncMock()
        mem1 = MagicMock()
        mem1.content = "Always validate inputs"
        mem2 = MagicMock()
        mem2.content = "Use async for I/O"

        with patch("hindsight.recall_safe", AsyncMock(return_value=[mem1, mem2])):
            router = self._make_router(
                config, event_bus, state, tmp_path, hindsight=mock_hindsight
            )
            endpoint = self._find_endpoint(router, "/api/memories")
            response = await endpoint()

        data = json.loads(response.body)
        assert data["total_items"] == 2
        assert len(data["items"]) == 2
        learnings = [item["learning"] for item in data["items"]]
        assert "Always validate inputs" in learnings
        assert "Use async for I/O" in learnings

    @pytest.mark.asyncio
    async def test_memories_returns_empty_without_hindsight(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Without a Hindsight client, endpoint returns empty items."""
        import json

        router = self._make_router(config, event_bus, state, tmp_path, hindsight=None)
        endpoint = self._find_endpoint(router, "/api/memories")
        response = await endpoint()
        data = json.loads(response.body)
        assert data["total_items"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_memories_caps_at_50_items(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """The endpoint requests at most 50 items from Hindsight."""
        import json
        from unittest.mock import AsyncMock, MagicMock

        mock_hindsight = AsyncMock()
        memories = []
        for i in range(50):
            mem = MagicMock()
            mem.content = f"Learning #{i + 1}"
            memories.append(mem)

        with patch("hindsight.recall_safe", AsyncMock(return_value=memories)):
            router = self._make_router(
                config, event_bus, state, tmp_path, hindsight=mock_hindsight
            )
            endpoint = self._find_endpoint(router, "/api/memories")
            response = await endpoint()

        data = json.loads(response.body)
        assert data["total_items"] == 50
        assert len(data["items"]) == 50


# ---------------------------------------------------------------------------
# GET /api/troubleshooting
# ---------------------------------------------------------------------------


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
        from unittest.mock import patch

        from hindsight import HindsightMemory
        from troubleshooting_store import TroubleshootingPattern

        pattern1 = TroubleshootingPattern(
            language="python",
            pattern_name="truthy_asyncmock",
            description="AsyncMock is always truthy",
            fix_strategy="Use .called or .call_count instead",
            frequency=3,
            source_issues=[10, 20, 30],
        )
        pattern2 = TroubleshootingPattern(
            language="node",
            pattern_name="jest_open_handles",
            description="Jest hangs due to open handles",
            fix_strategy="Use --forceExit or close resources",
            frequency=1,
            source_issues=[42],
        )

        memories = [
            HindsightMemory(content=pattern1.model_dump_json()),
            HindsightMemory(content=pattern2.model_dump_json()),
        ]

        mock_hindsight = MagicMock()

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch(
            "hindsight.recall_safe", new_callable=AsyncMock, return_value=memories
        ):
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
                hindsight=mock_hindsight,
            )
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
        from unittest.mock import patch

        from hindsight import HindsightMemory
        from troubleshooting_store import TroubleshootingPattern

        # Build 110 patterns as HindsightMemory objects
        memories = []
        for i in range(110):
            p = TroubleshootingPattern(
                language="python",
                pattern_name=f"pattern_{i}",
                description=f"Description {i}",
                fix_strategy=f"Fix {i}",
                source_issues=[i],
            )
            memories.append(HindsightMemory(content=p.model_dump_json()))

        mock_hindsight = MagicMock()

        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch(
            "hindsight.recall_safe", new_callable=AsyncMock, return_value=memories
        ):
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
                hindsight=mock_hindsight,
            )
            endpoint = self._find_endpoint(router, "/api/troubleshooting")
            response = await endpoint()

        data = json.loads(response.body)
        assert data["total_patterns"] == 110
        assert len(data["patterns"]) == 100


# ---------------------------------------------------------------------------
# Repo-scoped endpoints
# ---------------------------------------------------------------------------


class TestRepoScopedEndpoints:
    """Tests for repo-scoped endpoints resolving runtime-specific state."""

    def _make_router(
        self,
        config,
        tmp_path: Path,
        registry,
        *,
        remove_repo_cb=None,
    ):
        from dashboard_routes import create_router

        event_bus = MagicMock()
        state = MagicMock()
        state.get_hitl_summary.return_value = ""
        state.get_hitl_summary_updated_at.return_value = None
        state.get_hitl_visual_evidence.return_value = None
        pr_mgr = MagicMock()
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
            remove_repo_cb=remove_repo_cb,
        )

    @pytest.mark.asyncio
    async def test_get_prs_uses_runtime_pr_manager(self, config, tmp_path) -> None:
        runtime_config = config.model_copy()
        runtime = SimpleNamespace(
            config=runtime_config,
            event_bus=MagicMock(),
            state=MagicMock(),
            orchestrator=None,
        )
        registry = MagicMock()
        registry.get.return_value = runtime
        router = self._make_router(config, tmp_path, registry)
        endpoint = next(
            r for r in router.routes if getattr(r, "path", "") == "/api/prs"
        )

        with patch("dashboard_routes.PRManager") as MockPRManager:
            mock_mgr = MockPRManager.return_value
            mock_mgr.list_open_prs = AsyncMock(return_value=[])
            resp = await endpoint.endpoint(repo="org-repo")

        assert resp.status_code == 200
        MockPRManager.assert_called_once_with(runtime_config, runtime.event_bus)
        mock_mgr.list_open_prs.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_hitl_uses_runtime_state(self, config, tmp_path) -> None:
        class _State:
            def __init__(self) -> None:
                self.cause_calls: list[int] = []
                self.origin_calls: list[int] = []

            def get_hitl_cause(self, issue: int) -> str:
                self.cause_calls.append(issue)
                return "Manual escalation"

            def get_hitl_origin(self, issue: int) -> str:
                self.origin_calls.append(issue)
                return config.review_label[0]

        runtime = SimpleNamespace(
            config=config.model_copy(),
            event_bus=MagicMock(),
            state=_State(),
            orchestrator=None,
        )
        registry = MagicMock()
        registry.get.return_value = runtime
        router = self._make_router(config, tmp_path, registry)
        endpoint = next(
            r for r in router.routes if getattr(r, "path", "") == "/api/hitl"
        )

        class _Item:
            def __init__(self, issue: int) -> None:
                self.issue = issue

            def model_dump(self) -> dict:
                return {"issue": self.issue}

        with patch("dashboard_routes.PRManager") as MockPRManager:
            mock_mgr = MockPRManager.return_value
            mock_mgr.list_hitl_items = AsyncMock(return_value=[_Item(42)])
            resp = await endpoint.endpoint(repo="org-repo")

        import json

        assert resp.status_code == 200
        payload = json.loads(resp.body)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["cause"] == "Manual escalation"
        assert runtime.state.cause_calls == [42]
        assert runtime.state.origin_calls == [42]

    @pytest.mark.asyncio
    async def test_get_system_workers_reads_repo_state_when_idle(
        self, config, tmp_path
    ) -> None:
        runtime = SimpleNamespace(
            config=config.model_copy(),
            event_bus=MagicMock(),
            state=MagicMock(),
            orchestrator=None,
        )
        runtime.state.get_bg_worker_states.return_value = {
            "pipeline_poller": {"last_run": "2026-01-01T00:00:00Z", "details": {}}
        }
        registry = MagicMock()
        registry.get.return_value = runtime
        router = self._make_router(config, tmp_path, registry)
        endpoint = next(
            r for r in router.routes if getattr(r, "path", "") == "/api/system/workers"
        )

        resp = await endpoint.endpoint(repo="org-repo")

        assert resp.status_code == 200
        runtime.state.get_bg_worker_states.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_sessions_uses_runtime_state(self, config, tmp_path) -> None:
        runtime = SimpleNamespace(
            config=config.model_copy(),
            event_bus=MagicMock(),
            state=MagicMock(),
            orchestrator=None,
        )
        runtime.state.load_sessions.return_value = []
        registry = MagicMock()
        registry.get.return_value = runtime
        router = self._make_router(config, tmp_path, registry)
        endpoint = next(
            r for r in router.routes if getattr(r, "path", "") == "/api/sessions"
        )

        resp = await endpoint.endpoint(repo="org-repo")

        assert resp.status_code == 200
        runtime.state.load_sessions.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_runtime_uses_callback(self, config, tmp_path) -> None:
        runtime = SimpleNamespace(
            config=config.model_copy(),
            event_bus=MagicMock(),
            state=MagicMock(),
            orchestrator=None,
            running=False,
        )
        registry = MagicMock()
        registry.get.return_value = runtime
        remove_cb = AsyncMock(return_value=True)
        router = self._make_router(
            config,
            tmp_path,
            registry,
            remove_repo_cb=remove_cb,
        )
        endpoint = next(
            r
            for r in router.routes
            if getattr(r, "path", "") == "/api/runtimes/{slug}"
            and "DELETE" in getattr(r, "methods", set())
        )

        resp = await endpoint.endpoint(slug="org-repo")

        assert resp.status_code == 200
        remove_cb.assert_awaited_once_with("org-repo")


# ---------------------------------------------------------------------------
# Runtime endpoints with registry
# ---------------------------------------------------------------------------


class TestRuntimeEndpointsWithRegistry:
    """Tests for /api/runtimes/* endpoints when a registry is provided."""

    def _make_router(self, config, event_bus, state, tmp_path, *, registry=None):
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

    def _find_endpoint(self, router, path, method=None):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
                and (
                    method is None
                    or (hasattr(route, "methods") and method in route.methods)
                )
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_list_runtimes_empty_registry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_registry = MagicMock()
        mock_registry.all = []
        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes")
        assert endpoint is not None

        resp = await endpoint()
        import json as json_mod

        data = json_mod.loads(resp.body)
        assert data == {"runtimes": []}

    @pytest.mark.asyncio
    async def test_list_runtimes_with_registered_runtime(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.slug = "owner-repo"
        mock_rt.config.repo = "owner/repo"
        mock_rt.running = False

        mock_registry = MagicMock()
        mock_registry.all = [mock_rt]

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes")

        resp = await endpoint()
        import json as json_mod

        data = json_mod.loads(resp.body)
        assert len(data["runtimes"]) == 1
        assert data["runtimes"][0]["slug"] == "owner-repo"
        assert data["runtimes"][0]["running"] is False

    @pytest.mark.asyncio
    async def test_get_runtime_status_found(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.slug = "owner-repo"
        mock_rt.config.repo = "owner/repo"
        mock_rt.running = False

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_rt

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}", "GET")

        resp = await endpoint("owner-repo")
        import json as json_mod

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["slug"] == "owner-repo"

    @pytest.mark.asyncio
    async def test_get_runtime_status_not_found(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}", "GET")

        resp = await endpoint("nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_runtime_status_no_registry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path, registry=None)
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}", "GET")
        assert endpoint is not None

        resp = await endpoint("any-slug")
        assert resp.status_code == 501

    @pytest.mark.asyncio
    async def test_start_runtime_success(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.running = False
        mock_rt.start = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_rt

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/start")

        resp = await endpoint("my-repo")
        import json as json_mod

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "started"
        mock_rt.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_runtime_already_running(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.running = True

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_rt

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/start")

        resp = await endpoint("my-repo")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_stop_runtime_success(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.running = True
        mock_rt.stop = AsyncMock()

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_rt

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/stop")

        resp = await endpoint("my-repo")
        import json as json_mod

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "stopped"
        mock_rt.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_runtime_success(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.running = False

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_rt

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}", "DELETE")
        assert endpoint is not None

        resp = await endpoint("my-repo")
        import json as json_mod

        data = json_mod.loads(resp.body)
        assert data["status"] == "removed"
        mock_registry.remove.assert_called_once_with("my-repo")

    @pytest.mark.asyncio
    async def test_start_runtime_no_registry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path, registry=None)
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/start")
        assert endpoint is not None

        resp = await endpoint("my-repo")
        assert resp.status_code == 501

    @pytest.mark.asyncio
    async def test_stop_runtime_no_registry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path, registry=None)
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/stop")
        assert endpoint is not None

        resp = await endpoint("my-repo")
        assert resp.status_code == 501

    @pytest.mark.asyncio
    async def test_stop_runtime_not_running(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_rt = MagicMock()
        mock_rt.running = False

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_rt

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/stop")

        resp = await endpoint("my-repo")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_runtime_no_registry(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router = self._make_router(config, event_bus, state, tmp_path, registry=None)
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}", "DELETE")
        assert endpoint is not None

        resp = await endpoint("my-repo")
        assert resp.status_code == 501

    @pytest.mark.asyncio
    async def test_start_runtime_not_found(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/start")
        assert endpoint is not None

        resp = await endpoint("nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_runtime_not_found(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}/stop")
        assert endpoint is not None

        resp = await endpoint("nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_runtime_not_found(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        router = self._make_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        endpoint = self._find_endpoint(router, "/api/runtimes/{slug}", "DELETE")
        assert endpoint is not None

        resp = await endpoint("nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/retrospectives — edge cases
# ---------------------------------------------------------------------------
