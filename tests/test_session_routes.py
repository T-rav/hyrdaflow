"""Tests for session-related API endpoints in dashboard_routes.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import SessionLog


def _make_session(
    *,
    id: str = "test-repo-20240315T142530",
    repo: str = "test-org/test-repo",
    started_at: str = "2024-03-15T14:25:30+00:00",
    ended_at: str | None = None,
    status: str = "active",
) -> SessionLog:
    return SessionLog(
        id=id,
        repo=repo,
        started_at=started_at,
        ended_at=ended_at,
        status=status,
    )


def _make_router(config, event_bus, state, tmp_path, get_orch=None):
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


def _find_endpoint(router, path):
    for route in router.routes:
        if hasattr(route, "path") and route.path == path and hasattr(route, "endpoint"):
            return route.endpoint
    return None


class TestGetSessions:
    """Tests for GET /api/sessions endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_sessions(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/sessions")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_returns_sessions_list(
        self, config, event_bus, state, tmp_path
    ) -> None:
        s1 = _make_session(id="s1", started_at="2024-01-01T00:00:00")
        s2 = _make_session(id="s2", started_at="2024-01-02T00:00:00")
        state.save_session(s1)
        state.save_session(s2)

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/sessions")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 2
        assert data[0]["id"] == "s2"  # newest first
        assert data[1]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_filters_by_repo(self, config, event_bus, state, tmp_path) -> None:
        s1 = _make_session(id="s1", repo="org/repo-a", started_at="2024-01-01T00:00:00")
        s2 = _make_session(id="s2", repo="org/repo-b", started_at="2024-01-02T00:00:00")
        state.save_session(s1)
        state.save_session(s2)

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/sessions")
        assert endpoint is not None

        response = await endpoint(repo="org/repo-a")
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["repo"] == "org/repo-a"


class TestGetSessionDetail:
    """Tests for GET /api/sessions/{session_id} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_session_detail(
        self, config, event_bus, state, tmp_path
    ) -> None:
        session = _make_session(id="target-id")
        state.save_session(session)

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/sessions/{session_id}")
        assert endpoint is not None

        response = await endpoint(session_id="target-id")
        data = json.loads(response.body)
        assert data["id"] == "target-id"
        assert data["repo"] == "test-org/test-repo"
        assert "events" in data

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_session(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/sessions/{session_id}")
        assert endpoint is not None

        response = await endpoint(session_id="nonexistent")
        assert response.status_code == 404
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_returns_events_for_session(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from events import EventType, HydraFlowEvent

        session = _make_session(id="sess-1")
        state.save_session(session)

        # Publish events: one tagged with the session, one without
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                session_id="sess-1",
                data={"issue": 1},
            )
        )
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.WORKER_UPDATE,
                session_id="other-session",
                data={"issue": 2},
            )
        )

        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/sessions/{session_id}")
        response = await endpoint(session_id="sess-1")
        data = json.loads(response.body)
        assert len(data["events"]) == 1
        assert data["events"][0]["data"]["issue"] == 1


class TestControlStatusIncludesSessionId:
    """Tests that /api/control/status includes current_session_id."""

    @pytest.mark.asyncio
    async def test_control_status_includes_session_id_when_running(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.run_status = "running"
        mock_orch.current_session_id = "test-session-123"

        router = _make_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = _find_endpoint(router, "/api/control/status")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data["current_session_id"] == "test-session-123"

    @pytest.mark.asyncio
    async def test_control_status_session_id_null_when_idle(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/status")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert data["current_session_id"] is None
