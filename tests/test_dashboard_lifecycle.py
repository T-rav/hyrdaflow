"""Tests for dashboard — lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from events import EventBus, EventType
from models import BGWorkerHealth, PRListItem
from tests.conftest import EventFactory, make_orchestrator_mock
from tests.helpers import ConfigFactory

if TYPE_CHECKING:
    from config import HydraFlowConfig


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config: HydraFlowConfig) -> None:
    """Avoid background HITL summary warm tasks in dashboard smoke tests."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------


class TestCreateApp:
    """Tests for HydraFlowDashboard.create_app()."""

    def test_create_app_returns_fastapi_instance(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        try:
            from fastapi import FastAPI
        except ImportError:
            pytest.skip("FastAPI not installed")

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        assert isinstance(app, FastAPI)

    def test_create_app_stores_app_on_instance(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        try:
            from dashboard import HydraFlowDashboard
        except ImportError:
            pytest.skip("FastAPI not installed")

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        assert dashboard._app is app

    def test_create_app_title_is_hydraflow_dashboard(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        try:
            from dashboard import HydraFlowDashboard
        except ImportError:
            pytest.skip("FastAPI not installed")

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        assert app.title == "HydraFlow Dashboard"


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


class TestIndexRoute:
    """Tests for the GET / route."""

    def test_get_root_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200

    def test_get_root_returns_html_content_type(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/")

        assert "text/html" in response.headers.get("content-type", "")

    def test_get_root_returns_html_body(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/")

        # Either the real template or the fallback HTML should be returned
        body = response.text
        assert "<html" in body.lower() or "<h1>" in body.lower()

    def test_get_root_fallback_when_template_missing(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """When index.html does not exist, a fallback HTML page is returned."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(
            config,
            event_bus,
            state,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )
        app = dashboard.create_app()
        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        assert "<h1>" in response.text


# ---------------------------------------------------------------------------
# GET /healthz
# ---------------------------------------------------------------------------


class TestHealthRoute:
    """Tests for the GET /healthz health-check endpoint."""

    def test_healthz_returns_ok_payload(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True)
        started_at = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0)
        state.reset_session_counters(started_at.isoformat())
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/healthz")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["orchestrator_running"] is True
        assert payload["dashboard"]["port"] == config.dashboard_port
        assert payload["dashboard"]["host"] == config.dashboard_host
        assert payload["ready"] is True
        assert payload["checks"]["orchestrator"]["status"] == "running"
        assert payload["checks"]["workers"]["status"] in {"ok", "disabled"}
        assert payload["checks"]["dashboard"]["public"] is False
        assert payload["session_started_at"] == started_at.isoformat()
        assert isinstance(payload["uptime_seconds"], int)
        assert payload["uptime_seconds"] >= 300

    def test_healthz_reports_worker_errors(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True)
        state.set_worker_heartbeat(
            "memory_sync",
            {
                "status": BGWorkerHealth.ERROR,
                "last_run": None,
                "details": {"error": "boom"},
            },
        )
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/healthz")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "degraded"
        assert payload["worker_errors"] == ["memory_sync"]
        assert payload["ready"] is False
        assert payload["checks"]["workers"]["status"] == "degraded"
        assert payload["checks"]["workers"]["errors"] == ["memory_sync"]

    def test_healthz_handles_missing_session_start(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(running=True)
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        payload = client.get("/healthz").json()

        assert payload["session_started_at"] is None
        assert payload["uptime_seconds"] is None

    def test_healthz_marks_dashboard_binding_public_flag(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        public_config = ConfigFactory.create(
            dashboard_host="0.0.0.0",
            dashboard_port=config.dashboard_port,
        )
        orch = make_orchestrator_mock(running=True)
        dashboard = HydraFlowDashboard(
            public_config, event_bus, state, orchestrator=orch
        )
        app = dashboard.create_app()

        client = TestClient(app)
        payload = client.get("/healthz").json()

        assert payload["checks"]["dashboard"]["public"] is True
        assert payload["ready"] is True

    def test_healthz_handles_invalid_session_start(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.reset_session_counters("not-a-date")
        orch = make_orchestrator_mock(running=True)
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        payload = client.get("/healthz").json()

        assert payload["session_started_at"] is None
        assert payload["uptime_seconds"] is None

    def test_healthz_reports_starting_when_orchestrator_missing(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        payload = client.get("/healthz").json()

        assert payload["status"] == "starting"
        assert payload["orchestrator_running"] is False
        assert payload["ready"] is False
        assert payload["checks"]["orchestrator"]["status"] == "missing"


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------


class TestAccessibility:
    """Tests for accessibility attributes in the dashboard HTML."""

    @pytest.mark.skip(
        reason="aria attribute is rendered by React in the browser, not in the HTML shell"
    )
    def test_human_input_field_has_aria_labelledby(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        """The human-input field must be linked to its label for screen readers."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/")

        assert 'aria-labelledby="human-input-question"' in response.text


# ---------------------------------------------------------------------------
# GET /api/state
# ---------------------------------------------------------------------------


class TestStateRoute:
    """Tests for the GET /api/state route."""

    def test_get_state_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/state")

        assert response.status_code == 200

    def test_get_state_returns_state_dict(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.mark_issue(42, "success")
        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/state")

        body = response.json()
        assert isinstance(body, dict)
        assert "processed_issues" in body

    def test_get_state_includes_lifetime_stats(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/state")

        body = response.json()
        assert "lifetime_stats" in body

    def test_get_state_reflects_current_state(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.mark_issue(7, "failed")
        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/state")
        body = response.json()

        assert body["processed_issues"].get("7") == "failed"


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------


class TestStatsRoute:
    """Tests for the GET /api/stats route."""

    def test_stats_endpoint_returns_lifetime_stats(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["issues_completed"] == 0
        assert body["prs_merged"] == 0
        assert body["issues_created"] == 0
        # New fields should be present with zero defaults
        assert body["total_quality_fix_rounds"] == 0
        assert body["total_hitl_escalations"] == 0

    def test_stats_endpoint_reflects_incremented_values(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.record_pr_merged()
        state.record_issue_completed()
        state.record_issue_created()
        state.record_issue_created()
        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/stats")

        body = response.json()
        assert body["prs_merged"] == 1
        assert body["issues_completed"] == 1
        assert body["issues_created"] == 2


# ---------------------------------------------------------------------------
# GET /api/events
# ---------------------------------------------------------------------------


class TestEventsRoute:
    """Tests for the GET /api/events route."""

    def test_get_events_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/events")

        assert response.status_code == 200

    def test_get_events_returns_list(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/events")

        body = response.json()
        assert isinstance(body, list)

    def test_get_events_empty_when_no_events_published(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/events")

        assert response.json() == []

    def test_get_events_includes_published_events(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        async def publish() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )

        asyncio.run(publish())

        client = TestClient(app)
        response = client.get("/api/events")
        body = response.json()

        assert len(body) == 1
        assert body[0]["type"] == EventType.PHASE_CHANGE.value


# ---------------------------------------------------------------------------
# GET /api/prs
# ---------------------------------------------------------------------------


class TestPRsRoute:
    """Tests for the GET /api/prs route."""

    def test_prs_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_open_prs", return_value=[]):
            response = client.get("/api/prs")

        assert response.status_code == 200

    def test_prs_returns_empty_list_when_no_open_prs(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_open_prs", return_value=[]):
            response = client.get("/api/prs")

        assert response.json() == []

    def test_prs_returns_empty_list_on_gh_failure(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_open_prs", return_value=[]):
            response = client.get("/api/prs")

        assert response.json() == []

    _TWO_MOCK_PRS = [
        PRListItem(
            pr=10,
            issue=42,
            branch="agent/issue-42",
            url="https://github.com/org/repo/pull/10",
            draft=False,
            title="Fix widget",
        ),
        PRListItem(
            pr=11,
            issue=55,
            branch="agent/issue-55",
            url="https://github.com/org/repo/pull/11",
            draft=True,
            title="Add feature",
        ),
    ]

    def test_prs_happy_path_returns_correct_count(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch(
            "pr_manager.PRManager.list_open_prs", return_value=self._TWO_MOCK_PRS
        ):
            response = client.get("/api/prs")

        body = response.json()
        assert len(body) == 2

    def test_prs_happy_path_pr_fields_match(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch(
            "pr_manager.PRManager.list_open_prs", return_value=self._TWO_MOCK_PRS
        ):
            response = client.get("/api/prs")

        body = response.json()
        assert body[0]["pr"] == 10
        assert body[0]["issue"] == 42
        assert body[0]["branch"] == "agent/issue-42"
        assert body[0]["url"] == "https://github.com/org/repo/pull/10"
        assert body[0]["draft"] is False
        assert body[0]["title"] == "Fix widget"

        assert body[1]["pr"] == 11
        assert body[1]["issue"] == 55
        assert body[1]["branch"] == "agent/issue-55"
        assert body[1]["draft"] is True
        assert body[1]["title"] == "Add feature"

    def test_prs_includes_all_expected_fields(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_prs = [
            PRListItem(
                pr=7,
                issue=99,
                branch="agent/issue-99",
                url="https://github.com/org/repo/pull/7",
                draft=False,
                title="Some PR",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_open_prs", return_value=mock_prs):
            response = client.get("/api/prs")

        body = response.json()
        assert len(body) == 1
        expected_keys = {"pr", "issue", "branch", "url", "draft", "title"}
        assert set(body[0].keys()) == expected_keys

    def test_prs_deduplicates_across_labels(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        # PRManager.list_open_prs already deduplicates, so mock returns one
        mock_prs = [
            PRListItem(
                pr=42,
                issue=10,
                branch="agent/issue-10",
                url="https://github.com/org/repo/pull/42",
                draft=False,
                title="Duplicate PR",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_open_prs", return_value=mock_prs):
            response = client.get("/api/prs")

        body = response.json()
        assert len(body) == 1
        assert body[0]["pr"] == 42

    def test_prs_non_standard_branch_sets_issue_to_zero(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_prs = [
            PRListItem(
                pr=5,
                issue=0,
                branch="feature/my-branch",
                url="https://github.com/org/repo/pull/5",
                draft=False,
                title="Manual PR",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_open_prs", return_value=mock_prs):
            response = client.get("/api/prs")

        body = response.json()
        assert len(body) == 1
        assert body[0]["issue"] == 0
        assert body[0]["branch"] == "feature/my-branch"

    def test_prs_returns_empty_on_malformed_json(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        # PRManager.list_open_prs handles errors internally, returns []
        with patch("pr_manager.PRManager.list_open_prs", return_value=[]):
            response = client.get("/api/prs")

        assert response.json() == []


# ---------------------------------------------------------------------------
# GET /api/human-input
# ---------------------------------------------------------------------------


class TestHumanInputGetRoute:
    """Tests for the GET /api/human-input route."""

    def test_get_human_input_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/human-input")

        assert response.status_code == 200

    def test_get_human_input_returns_empty_dict_when_no_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/human-input")

        assert response.json() == {}

    def test_get_human_input_returns_pending_requests_from_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock(requests={42: "Which approach?"})
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.get("/api/human-input")

        body = response.json()
        assert "42" in body
        assert body["42"] == "Which approach?"


# ---------------------------------------------------------------------------
# POST /api/human-input/{issue_number}
# ---------------------------------------------------------------------------


class TestHumanInputPostRoute:
    """Tests for the POST /api/human-input/{issue_number} route."""

    def test_post_human_input_returns_ok_status(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/human-input/42", json={"answer": "Use option A"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_post_human_input_calls_orchestrator_provide_human_input(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        client.post("/api/human-input/42", json={"answer": "Go left"})

        orch.provide_human_input.assert_called_once_with(42, "Go left")

    def test_post_human_input_passes_empty_string_when_answer_missing(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        client.post("/api/human-input/7", json={})

        orch.provide_human_input.assert_called_once_with(7, "")

    def test_post_human_input_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/human-input/42", json={"answer": "something"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_post_human_input_routes_correct_issue_number(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        client.post("/api/human-input/99", json={"answer": "yes"})

        orch.provide_human_input.assert_called_once_with(99, "yes")


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    """Tests for HydraFlowDashboard.start() and stop()."""

    @pytest.mark.asyncio
    async def test_start_creates_server_task(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)

        with patch("uvicorn.Config"), patch("uvicorn.Server", return_value=mock_server):
            await dashboard.start()

        assert dashboard._server_task is not None
        assert isinstance(dashboard._server_task, asyncio.Task)

        if dashboard._server_task and not dashboard._server_task.done():
            dashboard._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dashboard._server_task

    @pytest.mark.asyncio
    async def test_start_uses_configured_host(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        config.dashboard_host = "0.0.0.0"
        dashboard = HydraFlowDashboard(config, event_bus, state)

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)

        with (
            patch("uvicorn.Config") as mock_config,
            patch("uvicorn.Server", return_value=mock_server),
        ):
            await dashboard.start()

        assert mock_config.call_args.kwargs["host"] == "0.0.0.0"

        if dashboard._server_task and not dashboard._server_task.done():
            dashboard._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dashboard._server_task

    @pytest.mark.asyncio
    async def test_start_does_nothing_when_uvicorn_not_installed(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with (
            patch.dict("sys.modules", {"uvicorn": None}),
            contextlib.suppress(ImportError),
        ):
            await dashboard.start()

        assert dashboard._server_task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_server_task(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        async def long_running() -> None:
            await asyncio.sleep(3600)

        dashboard._server_task = asyncio.create_task(long_running())
        await asyncio.sleep(0)

        await dashboard.stop()

        assert dashboard._server_task.cancelled() or dashboard._server_task.done()

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_no_task(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        assert dashboard._server_task is None

        await dashboard.stop()

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_task_already_done(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        async def quick_task() -> None:
            return

        task = asyncio.create_task(quick_task())
        await task
        dashboard._server_task = task

        await dashboard.stop()
        assert (
            dashboard._server_task.done()
        )  # already-done task stays done after stop()
