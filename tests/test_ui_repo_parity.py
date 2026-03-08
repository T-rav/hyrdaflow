"""UI/API repo-parity tests.

Validates that dashboard API endpoints correctly scope responses
by repo parameter and that context switching between repos returns
independent data.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from models import SessionLog
from tests.helpers import ConfigFactory, find_endpoint, make_dashboard_router

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(repo: str, session_id: str) -> SessionLog:
    return SessionLog(
        id=session_id,
        repo=repo,
        started_at="2024-01-01T00:00:00Z",
        ended_at="2024-01-01T01:00:00Z",
        issues_processed=[1, 2],
        issues_succeeded=2,
        issues_failed=0,
        status="completed",
    )


# ---------------------------------------------------------------------------
# Session API repo filtering
# ---------------------------------------------------------------------------


class TestSessionAPIRepoFiltering:
    @pytest.mark.asyncio
    async def test_sessions_filtered_by_repo_param(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """GET /api/sessions?repo=X should return only sessions for that repo."""
        state.save_session(_make_session("owner/alpha", "alpha-1"))
        state.save_session(_make_session("owner/alpha", "alpha-2"))
        state.save_session(_make_session("owner/beta", "beta-1"))

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/sessions")

        resp_alpha = await endpoint(repo="owner/alpha")
        data_alpha = json.loads(resp_alpha.body)
        assert len(data_alpha) == 2
        assert all(s["repo"] == "owner/alpha" for s in data_alpha)

        resp_beta = await endpoint(repo="owner/beta")
        data_beta = json.loads(resp_beta.body)
        assert len(data_beta) == 1
        assert data_beta[0]["repo"] == "owner/beta"

    @pytest.mark.asyncio
    async def test_sessions_no_repo_returns_all(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """GET /api/sessions with no repo param returns all sessions."""
        state.save_session(_make_session("owner/alpha", "alpha-1"))
        state.save_session(_make_session("owner/beta", "beta-1"))

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/sessions")

        resp = await endpoint(repo=None)
        data = json.loads(resp.body)
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_sessions_unknown_repo_returns_empty(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """GET /api/sessions?repo=unknown should return an empty list."""
        state.save_session(_make_session("owner/alpha", "alpha-1"))

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/sessions")

        resp = await endpoint(repo="owner/nonexistent")
        data = json.loads(resp.body)
        assert data == []


# ---------------------------------------------------------------------------
# State endpoint repo scoping
# ---------------------------------------------------------------------------


class TestStateEndpointRepoScoping:
    def _mock_runtime(self, config, event_bus):
        """Create a mock runtime with a state that returns repo-specific data."""
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {"repo": config.repo, "custom": True}

        runtime = MagicMock()
        runtime.config = config
        runtime.state = mock_state
        runtime.event_bus = event_bus
        runtime.orchestrator = None
        return runtime

    @pytest.mark.asyncio
    async def test_state_returns_per_repo_data(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """GET /api/state?repo=slug should return data from the matching runtime."""
        alpha_cfg = ConfigFactory.create(
            repo="owner/alpha", repo_root=tmp_path / "alpha" / "repo"
        )
        alpha_runtime = self._mock_runtime(alpha_cfg, event_bus)

        mock_registry = MagicMock()
        mock_registry.get.return_value = alpha_runtime

        router, _pr = make_dashboard_router(
            config, event_bus, state, tmp_path, registry=mock_registry
        )
        ep = find_endpoint(router, "/api/state")

        resp = await ep(repo="owner-alpha")
        assert resp.status_code == 200
        mock_registry.get.assert_called_once_with("owner-alpha")

    @pytest.mark.asyncio
    async def test_state_no_repo_returns_default(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """GET /api/state with no repo param returns default state."""
        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        ep = find_endpoint(router, "/api/state")

        resp = await ep(repo=None)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Context switching independence
# ---------------------------------------------------------------------------


class TestContextSwitchingIndependence:
    @pytest.mark.asyncio
    async def test_switching_repos_returns_independent_sessions(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """Switching the repo param should return completely different sessions."""
        for i in range(5):
            state.save_session(_make_session("owner/alpha", f"alpha-{i}"))
        for i in range(3):
            state.save_session(_make_session("owner/beta", f"beta-{i}"))

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/sessions")

        # Simulate context switching
        resp_alpha = await endpoint(repo="owner/alpha")
        resp_beta = await endpoint(repo="owner/beta")
        resp_alpha2 = await endpoint(repo="owner/alpha")

        data_alpha = json.loads(resp_alpha.body)
        data_beta = json.loads(resp_beta.body)
        data_alpha2 = json.loads(resp_alpha2.body)

        assert len(data_alpha) == 5
        assert len(data_beta) == 3
        # Switching back should give same result
        assert len(data_alpha2) == 5
        assert {s["id"] for s in data_alpha} == {s["id"] for s in data_alpha2}

    @pytest.mark.asyncio
    async def test_no_cross_contamination_between_repos(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """Session IDs from one repo should never appear in another repo's response."""
        state.save_session(_make_session("owner/alpha", "unique-alpha"))
        state.save_session(_make_session("owner/beta", "unique-beta"))

        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/sessions")

        resp_alpha = await endpoint(repo="owner/alpha")
        resp_beta = await endpoint(repo="owner/beta")

        alpha_ids = {s["id"] for s in json.loads(resp_alpha.body)}
        beta_ids = {s["id"] for s in json.loads(resp_beta.body)}

        assert "unique-alpha" in alpha_ids
        assert "unique-beta" not in alpha_ids
        assert "unique-beta" in beta_ids
        assert "unique-alpha" not in beta_ids


# ---------------------------------------------------------------------------
# Runtime endpoint availability
# ---------------------------------------------------------------------------


class TestRuntimeEndpointAvailability:
    def test_runtime_routes_registered(
        self, config, event_bus, state, tmp_path: Path
    ) -> None:
        """Router should register all runtime lifecycle routes."""
        router, _pr = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {getattr(route, "path", "") for route in router.routes}

        expected = {
            "/api/runtimes",
            "/api/runtimes/{slug}",
            "/api/runtimes/{slug}/start",
            "/api/runtimes/{slug}/stop",
        }
        assert expected.issubset(paths)
