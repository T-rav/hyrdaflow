"""Tests for dx/hydraflow/dashboard.py - HydraFlowDashboard class."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import contextlib
from typing import TYPE_CHECKING

from events import EventBus, EventType, HydraFlowEvent
from models import HITLItem, PRListItem
from tests.conftest import EventFactory, make_orchestrator_mock, make_state

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

        dashboard = HydraFlowDashboard(config, event_bus, state)

        # Patch both _UI_DIST_DIR and _TEMPLATE_DIR to non-existent paths
        with (
            patch("dashboard._UI_DIST_DIR", tmp_path / "no-dist"),
            patch("dashboard._TEMPLATE_DIR", tmp_path / "no-templates"),
        ):
            app = dashboard.create_app()
            client = TestClient(app)
            response = client.get("/")

        assert response.status_code == 200
        assert "<h1>" in response.text


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


# ---------------------------------------------------------------------------
# WebSocket /ws
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    """Tests for the WebSocket /ws endpoint."""

    def test_websocket_connects_successfully(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws"):
            pass  # Connection opens and closes without error

    def test_websocket_receives_history_on_connect(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish_events() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )
            await event_bus.publish(
                EventFactory.create(
                    type=EventType.PHASE_CHANGE, data={"phase": "implement"}
                )
            )

        asyncio.run(publish_events())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            msg1 = json.loads(ws.receive_text())
            msg2 = json.loads(ws.receive_text())

        assert msg1["type"] == "phase_change"
        assert msg1["data"]["phase"] == "plan"
        assert msg2["type"] == "phase_change"
        assert msg2["data"]["phase"] == "implement"

    def test_websocket_history_events_are_valid_json(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish() -> None:
            await event_bus.publish(
                EventFactory.create(
                    type=EventType.WORKER_UPDATE,
                    data={"issue": 42, "status": "running"},
                )
            )

        asyncio.run(publish())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            raw = ws.receive_text()

        parsed = json.loads(raw)
        assert "type" in parsed
        assert "timestamp" in parsed
        assert "data" in parsed
        assert parsed["type"] == "worker_update"
        assert parsed["data"]["issue"] == 42

    def test_websocket_receives_live_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        event = EventFactory.create(type=EventType.PR_CREATED, data={"pr": 99})

        original_subscribe = event_bus.subscribe

        def subscribe_with_preload(
            *_args: object, **_kwargs: object
        ) -> asyncio.Queue[HydraFlowEvent]:
            queue = original_subscribe()
            queue.put_nowait(event)
            return queue

        event_bus.subscribe = subscribe_with_preload  # type: ignore[assignment]

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())

        assert msg["type"] == "pr_created"
        assert msg["data"]["pr"] == 99

    def test_websocket_subscribes_to_event_bus_on_connect(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})

        original_subscribe = event_bus.subscribe

        def subscribe_with_preload(
            *_args: object, **_kwargs: object
        ) -> asyncio.Queue[HydraFlowEvent]:
            queue = original_subscribe()
            queue.put_nowait(event)
            return queue

        event_bus.subscribe = subscribe_with_preload  # type: ignore[assignment]

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            assert len(event_bus._subscribers) >= 1

    def test_websocket_unsubscribes_on_disconnect(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
        unsubscribe_called = threading.Event()

        original_subscribe = event_bus.subscribe
        original_unsubscribe = event_bus.unsubscribe

        def subscribe_with_preload(
            *_args: object, **_kwargs: object
        ) -> asyncio.Queue[HydraFlowEvent]:
            queue = original_subscribe()
            # Preload one event so receive_text() returns immediately, ensuring
            # the handler has entered its live-streaming loop before disconnect.
            queue.put_nowait(event)
            return queue

        event_bus.subscribe = subscribe_with_preload  # type: ignore[assignment]

        def unsubscribe_and_signal(
            queue: asyncio.Queue[HydraFlowEvent],
        ) -> None:
            original_unsubscribe(queue)
            unsubscribe_called.set()

        event_bus.unsubscribe = unsubscribe_and_signal  # type: ignore[assignment]

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()

        # Wait for the background ASGI thread to unsubscribe its queue deterministically
        assert unsubscribe_called.wait(timeout=5), (
            "unsubscribe was not called within 5s"
        )
        # Also verify the unsubscribe actually mutated _subscribers (not just that it was called)
        assert len(event_bus._subscribers) == 0, (
            f"Expected 0 subscribers after disconnect, got {len(event_bus._subscribers)}"
        )

    def test_multiple_websocket_clients_receive_same_history(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish_events() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
            )

        asyncio.run(publish_events())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)

        with client.websocket_connect("/ws") as ws1:
            msgs1 = [json.loads(ws1.receive_text()) for _ in range(2)]

        with client.websocket_connect("/ws") as ws2:
            msgs2 = [json.loads(ws2.receive_text()) for _ in range(2)]

        assert msgs1[0]["type"] == msgs2[0]["type"]
        assert msgs1[0]["data"] == msgs2[0]["data"]
        assert msgs1[1]["type"] == msgs2[1]["type"]
        assert msgs1[1]["data"] == msgs2[1]["data"]

    def test_websocket_sends_multiple_history_events_in_order(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        import json

        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        async def publish_events() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"step": 1})
            )
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"step": 2})
            )
            await event_bus.publish(
                EventFactory.create(type=EventType.WORKER_UPDATE, data={"step": 3})
            )

        asyncio.run(publish_events())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            msgs = [json.loads(ws.receive_text()) for _ in range(3)]

        assert msgs[0]["type"] == "phase_change"
        assert msgs[1]["type"] == "phase_change"
        assert msgs[2]["type"] == "worker_update"
        assert msgs[0]["data"]["step"] == 1
        assert msgs[1]["data"]["step"] == 2
        assert msgs[2]["data"]["step"] == 3


# ---------------------------------------------------------------------------
# GET /api/hitl
# ---------------------------------------------------------------------------


class TestHITLRoute:
    """Tests for the GET /api/hitl route."""

    def test_hitl_returns_200(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.status_code == 200

    def test_hitl_returns_empty_list_when_no_issues(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.json() == []

    def test_hitl_returns_issues_with_pr_info(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=42,
                title="Fix widget",
                issueUrl="https://github.com/org/repo/issues/42",
                pr=99,
                prUrl="https://github.com/org/repo/pull/99",
                branch="agent/issue-42",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["issue"] == 42
        assert body[0]["title"] == "Fix widget"
        assert body[0]["pr"] == 99
        assert body[0]["branch"] == "agent/issue-42"

    def test_hitl_returns_empty_on_gh_failure(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        client = TestClient(app)
        # PRManager.list_hitl_items handles errors internally, returns []
        with patch("pr_manager.PRManager.list_hitl_items", return_value=[]):
            response = client.get("/api/hitl")

        assert response.json() == []

    def test_hitl_shows_zero_pr_when_no_pr_found(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=10,
                title="Broken thing",
                issueUrl="",
                pr=0,
                prUrl="",
                branch="agent/issue-10",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["pr"] == 0
        assert body[0]["prUrl"] == ""


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/correct
# ---------------------------------------------------------------------------


class TestHITLCorrectEndpoint:
    """Tests for the POST /api/hitl/{issue}/correct route."""

    def test_correct_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            response = client.post(
                "/api/hitl/42/correct",
                json={"correction": "Mock the DB connection"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_correct_calls_orchestrator_submit(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            client.post(
                "/api/hitl/42/correct",
                json={"correction": "Fix the test"},
            )

        orch.submit_hitl_correction.assert_called_once_with(42, "Fix the test")

    def test_correct_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": "Something"},
        )

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_correct_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.submit_hitl_correction = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with patch("pr_manager.PRManager.swap_pipeline_labels", new_callable=AsyncMock):
            client.post(
                "/api/hitl/42/correct",
                json={"correction": "Fix it"},
            )

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "processing"
        assert hitl_events[0].data["action"] == "correct"

    def test_correct_rejects_empty_correction(
        self, config: HydraFlowConfig, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": ""},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    def test_correct_rejects_whitespace_only_correction(
        self, config: HydraFlowConfig, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": "   "},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    def test_correct_rejects_null_correction(
        self, config: HydraFlowConfig, event_bus: EventBus, tmp_path: Path
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state = make_state(tmp_path)
        orch = make_orchestrator_mock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post(
            "/api/hitl/42/correct",
            json={"correction": None},
        )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/skip
# ---------------------------------------------------------------------------


class TestHITLSkipEndpoint:
    """Tests for the POST /api/hitl/{issue}/skip route."""

    def test_skip_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_skip_calls_orchestrator_skip(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_skip_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_skip_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "skip"

    def test_skip_removes_hitl_origin_from_state(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-review")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/skip", json={"reason": "not needed"})

        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/close
# ---------------------------------------------------------------------------


class TestHITLCloseEndpoint:
    """Tests for the POST /api/hitl/{issue}/close route."""

    def test_close_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_close_calls_orchestrator_skip(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_close_returns_400_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        response = client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert response.status_code == 400
        assert response.json() == {"status": "no orchestrator"}

    def test_close_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "close"

    def test_close_removes_hitl_origin_from_state(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-review")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.close_issue", new_callable=AsyncMock),
            patch("pr_manager.PRManager.post_comment", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/close", json={"reason": "duplicate"})

        assert state.get_hitl_origin(42) is None


# ---------------------------------------------------------------------------
# POST /api/hitl/{issue}/approve-memory
# ---------------------------------------------------------------------------


class TestHITLApproveMemoryEndpoint:
    """Tests for the POST /api/hitl/{issue}/approve-memory route."""

    def test_approve_memory_returns_ok_with_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-memory")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_approve_memory_calls_orchestrator_skip(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        orch.skip_hitl_issue.assert_called_once_with(42)

    def test_approve_memory_works_without_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            response = client.post("/api/hitl/42/approve-memory")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_approve_memory_publishes_hitl_update_event(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        history = event_bus.get_history()
        hitl_events = [e for e in history if e.type.value == "hitl_update"]
        assert len(hitl_events) == 1
        assert hitl_events[0].data["issue"] == 42
        assert hitl_events[0].data["status"] == "resolved"
        assert hitl_events[0].data["action"] == "approved_as_memory"

    def test_approve_memory_removes_hitl_origin(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_origin(42, "hydraflow-improve")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        assert state.get_hitl_origin(42) is None

    def test_approve_memory_removes_hitl_cause(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        state.set_hitl_cause(42, "Memory suggestion")
        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        assert state.get_hitl_cause(42) is None

    def test_approve_memory_adds_memory_label(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch("pr_manager.PRManager.remove_label", new_callable=AsyncMock),
            patch(
                "pr_manager.PRManager.add_labels", new_callable=AsyncMock
            ) as mock_add,
        ):
            client.post("/api/hitl/42/approve-memory")

        mock_add.assert_called_once_with(42, ["hydraflow-memory"])

    def test_approve_memory_removes_improve_and_hitl_labels(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.skip_hitl_issue = MagicMock()
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        client = TestClient(app)
        with (
            patch(
                "pr_manager.PRManager.remove_label", new_callable=AsyncMock
            ) as mock_remove,
            patch("pr_manager.PRManager.add_labels", new_callable=AsyncMock),
        ):
            client.post("/api/hitl/42/approve-memory")

        # Should remove both improve and hitl labels
        removed_labels = [call.args[1] for call in mock_remove.call_args_list]
        assert "hydraflow-improve" in removed_labels
        assert "hydraflow-hitl" in removed_labels


# ---------------------------------------------------------------------------
# GET /api/hitl enriched with status
# ---------------------------------------------------------------------------


class TestHITLEnrichedRoute:
    """Tests for the enriched GET /api/hitl response with status."""

    def test_hitl_includes_status_from_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        orch = make_orchestrator_mock()
        orch.get_hitl_status = MagicMock(return_value="processing")
        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=orch)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(issue=42, title="Fix widget", branch="agent/issue-42"),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == "processing"
        orch.get_hitl_status.assert_called_once_with(42)

    def test_hitl_defaults_status_when_no_orchestrator(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state, orchestrator=None)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(issue=42, title="Fix widget", branch="agent/issue-42"),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == "pending"

    def test_hitl_includes_cause_and_status_fields(
        self, config: HydraFlowConfig, event_bus: EventBus, state
    ) -> None:
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()

        mock_items = [
            HITLItem(
                issue=42,
                title="Fix widget",
                branch="agent/issue-42",
                cause="CI failure",
                status="pending",
            ),
        ]

        client = TestClient(app)
        with patch("pr_manager.PRManager.list_hitl_items", return_value=mock_items):
            response = client.get("/api/hitl")

        body = response.json()
        assert "cause" in body[0]
        assert "status" in body[0]
        assert body[0]["cause"] == "CI failure"


# ---------------------------------------------------------------------------
# WebSocket error logging
# ---------------------------------------------------------------------------


class TestWebSocketErrorLogging:
    """Tests that unexpected WebSocket errors are logged, not silently swallowed."""

    def test_websocket_logs_warning_on_history_replay_error(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        """When send_text raises during history replay, a warning is logged."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        # Publish an event so history is non-empty
        async def publish() -> None:
            await event_bus.publish(
                EventFactory.create(type=EventType.PHASE_CHANGE, data={"batch": 1})
            )

        asyncio.run(publish())

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)

        with patch("dashboard_routes.logger") as mock_logger:
            with (
                patch(
                    "starlette.websockets.WebSocket.send_text",
                    side_effect=RuntimeError("serialization failed"),
                ),
                client.websocket_connect("/ws"),
            ):
                pass

            mock_logger.warning.assert_any_call(
                "WebSocket error during history replay", exc_info=True
            )

    def test_websocket_logs_warning_on_live_stream_error(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        """When send_text raises during live streaming, a warning is logged."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)

        # Pre-populate a queue with one event so queue.get() returns immediately
        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
        pre_populated_queue: asyncio.Queue[HydraFlowEvent] = asyncio.Queue()
        pre_populated_queue.put_nowait(event)

        with patch("dashboard_routes.logger") as mock_logger:
            # subscribe() returns the pre-populated queue (no history, so
            # send_text is only called during the live streaming phase)
            with (
                patch.object(event_bus, "subscribe", return_value=pre_populated_queue),
                patch.object(event_bus, "get_history", return_value=[]),
                patch(
                    "starlette.websockets.WebSocket.send_text",
                    side_effect=RuntimeError("live stream send failed"),
                ),
                client.websocket_connect("/ws"),
            ):
                pass

            mock_logger.warning.assert_any_call(
                "WebSocket error during live streaming", exc_info=True
            )

    def test_websocket_disconnect_not_logged(
        self, config: HydraFlowConfig, event_bus, state
    ) -> None:
        """WebSocketDisconnect should be handled silently (no warning logged)."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)
        app = dashboard.create_app()
        client = TestClient(app)

        with patch("dashboard_routes.logger") as mock_logger:
            with client.websocket_connect("/ws"):
                # Just connect and disconnect normally
                pass

            # logger.warning should NOT have been called with WebSocket error messages
            for call in mock_logger.warning.call_args_list:
                assert "WebSocket error" not in str(call)


# ---------------------------------------------------------------------------
# Static file serving and template cleanup (issue #24)
# ---------------------------------------------------------------------------


class TestStaticDashboardJS:
    """Tests for serving /static/dashboard.js."""

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

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with patch("dashboard._STATIC_DIR", static_dir):
            app = dashboard.create_app()
            client = TestClient(app)
            response = client.get("/static/dashboard.js")

        assert response.status_code == 200
        assert "// dashboard JS" in response.text


class TestFallbackTemplateExternalJS:
    """Tests that the fallback template references external JS and has no inline onclick."""

    def test_fallback_template_references_external_js(
        self, config: HydraFlowConfig, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The fallback HTML includes a script tag pointing to /static/dashboard.js."""
        from fastapi.testclient import TestClient

        from dashboard import HydraFlowDashboard

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with (
            patch("dashboard._UI_DIST_DIR", tmp_path / "no-dist"),
            patch("dashboard._STATIC_DIR", tmp_path / "no-static"),
        ):
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

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with (
            patch("dashboard._UI_DIST_DIR", tmp_path / "no-dist"),
            patch("dashboard._STATIC_DIR", tmp_path / "no-static"),
        ):
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

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with (
            patch("dashboard._UI_DIST_DIR", tmp_path / "no-dist"),
            patch("dashboard._STATIC_DIR", tmp_path / "no-static"),
        ):
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
    """Tests for the SPA catch-all route that serves index.html for non-API paths."""

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

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with patch("dashboard._UI_DIST_DIR", dist_dir):
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

        dashboard = HydraFlowDashboard(config, event_bus, state)

        with patch("dashboard._UI_DIST_DIR", dist_dir):
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
    """Tests for the GET /api/pipeline/stats endpoint."""

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
        orch = make_orchestrator_mock()
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
        orch = make_orchestrator_mock()
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
    """Tests that PIPELINE_STATS events are forwarded via WebSocket."""

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
