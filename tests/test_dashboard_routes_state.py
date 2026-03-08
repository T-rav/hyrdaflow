"""Tests for dashboard_routes.py — state, stats, queue, events, PRs, sessions, timeline, pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


class TestEnsureRepoCompatibilityEndpoint:
    """Compatibility tests for POST /api/repos request shapes."""

    def _make_router(self, config, event_bus, state, tmp_path, supervisor_module):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        with patch.dict(
            "sys.modules",
            {
                "hf_cli.supervisor_client": supervisor_module,
                "hf_cli.supervisor_manager": MagicMock(),
            },
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
    async def test_accepts_req_query_plain_slug(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from types import SimpleNamespace

        supervisor = SimpleNamespace(
            list_repos=lambda: [
                {
                    "slug": "8thlight/insightmesh",
                    "path": str(tmp_path / "insightmesh"),
                }
            ],
            add_repo=lambda _path, _slug: {"status": "ok", "slug": _slug},
        )
        router = self._make_router(config, event_bus, state, tmp_path, supervisor)
        endpoint = self._find_post_endpoint(router, "/api/repos")
        assert endpoint is not None

        resp = await endpoint(
            req=None,
            req_query="8thlight/insightmesh",
            slug=None,
            repo=None,
        )
        data = json.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_accepts_req_query_json_slug(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from types import SimpleNamespace

        supervisor = SimpleNamespace(
            list_repos=lambda: [
                {
                    "slug": "8thlight/insightmesh",
                    "path": str(tmp_path / "insightmesh"),
                }
            ],
            add_repo=lambda _path, _slug: {"status": "ok", "slug": _slug},
        )
        router = self._make_router(config, event_bus, state, tmp_path, supervisor)
        endpoint = self._find_post_endpoint(router, "/api/repos")
        assert endpoint is not None

        resp = await endpoint(
            req=None,
            req_query='{"slug":"8thlight/insightmesh"}',
            slug=None,
            repo=None,
        )
        data = json.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"


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
# GET /api/timeline and /api/timeline/issue/{issue_num}
# ---------------------------------------------------------------------------


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
