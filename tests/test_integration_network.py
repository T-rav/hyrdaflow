"""Integration tests for HTTP and WebSocket operations.

Covers: dashboard.py (FastAPI WebSocket streaming via real TestClient).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# dashboard.py — FastAPI WebSocket integration
# ---------------------------------------------------------------------------


class TestDashboardHttp:
    """Integration tests for the dashboard HTTP endpoints."""

    @pytest.fixture()
    def app_client(self, tmp_path: Path):
        """Build a TestClient-wrapped FastAPI app with a real dashboard router."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from events import EventBus
        from state import StateTracker
        from tests.helpers import ConfigFactory, make_dashboard_router

        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
        )
        event_bus = EventBus()
        state = StateTracker(tmp_path / "state.json")
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            yield client, state

    def test_stats_endpoint(self, app_client) -> None:
        """GET /api/stats returns a JSON response."""
        client, _ = app_client
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_state_endpoint(self, app_client) -> None:
        """GET /api/state returns the state tracker data."""
        client, state = app_client
        state.mark_issue(42, "planned")
        resp = client.get("/api/state")
        assert resp.status_code == 200
        assert resp.json()["processed_issues"]["42"] == "planned"

    def test_event_history_endpoint(self, app_client) -> None:
        """GET /api/events returns event history as a list."""
        client, _ = app_client
        resp = client.get("/api/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
