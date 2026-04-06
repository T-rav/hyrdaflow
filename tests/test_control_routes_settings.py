"""Tests for settings endpoints in _control_routes.py.

Verifies that settings GET/POST endpoints use ctx.state directly
and work without an orchestrator running.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from models import (
    CIMonitorSettings,
    CodeGroomingSettings,
    DependabotMergeSettings,
    SecurityPatchSettings,
    StaleIssueSettings,
)
from tests.helpers import find_endpoint, make_dashboard_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _router_no_orch(config, event_bus: EventBus, state, tmp_path: Path):
    """Build a dashboard router with get_orch returning None (no orchestrator)."""
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, get_orch=lambda: None
    )
    return router, state


# ---------------------------------------------------------------------------
# Dependabot Merge Settings
# ---------------------------------------------------------------------------


class TestDependabotMergeSettingsEndpoints:
    """GET/POST /api/dependabot-merge/settings use ctx.state, not orch.state."""

    @pytest.mark.asyncio
    async def test_get_dependabot_merge_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, state = _router_no_orch
        handler = find_endpoint(router, "/api/dependabot-merge/settings", method="GET")
        assert handler is not None
        response = await handler()
        data = json.loads(response.body)
        assert data == DependabotMergeSettings().model_dump()

    @pytest.mark.asyncio
    async def test_post_dependabot_merge_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, state = _router_no_orch
        handler = find_endpoint(router, "/api/dependabot-merge/settings", method="POST")
        assert handler is not None
        response = await handler(body={"failure_strategy": "hitl"})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["failure_strategy"] == "hitl"
        # Verify state was updated
        assert state.get_dependabot_merge_settings().failure_strategy == "hitl"


# ---------------------------------------------------------------------------
# Stale Issue Settings
# ---------------------------------------------------------------------------


class TestStaleIssueSettingsEndpoints:
    """GET/POST /api/stale-issue/settings use ctx.state, not orch.state."""

    @pytest.mark.asyncio
    async def test_get_stale_issue_settings_without_orchestrator(self, _router_no_orch):
        router, _state = _router_no_orch
        handler = find_endpoint(router, "/api/stale-issue/settings", method="GET")
        assert handler is not None
        response = await handler()
        data = json.loads(response.body)
        assert data == StaleIssueSettings().model_dump()

    @pytest.mark.asyncio
    async def test_post_stale_issue_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, state = _router_no_orch
        handler = find_endpoint(router, "/api/stale-issue/settings", method="POST")
        assert handler is not None
        response = await handler(body={"staleness_days": 60})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["staleness_days"] == 60
        assert state.get_stale_issue_settings().staleness_days == 60


# ---------------------------------------------------------------------------
# Security Patch Settings
# ---------------------------------------------------------------------------


class TestSecurityPatchSettingsEndpoints:
    """GET/POST /api/security-patch/settings use ctx.state, not orch.state."""

    @pytest.mark.asyncio
    async def test_get_security_patch_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, _state = _router_no_orch
        handler = find_endpoint(router, "/api/security-patch/settings", method="GET")
        assert handler is not None
        response = await handler()
        data = json.loads(response.body)
        assert data == SecurityPatchSettings().model_dump()

    @pytest.mark.asyncio
    async def test_post_security_patch_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, state = _router_no_orch
        handler = find_endpoint(router, "/api/security-patch/settings", method="POST")
        assert handler is not None
        response = await handler(body={"severity_levels": ["critical"]})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["severity_levels"] == ["critical"]
        assert state.get_security_patch_settings().severity_levels == ["critical"]


# ---------------------------------------------------------------------------
# CI Monitor Settings
# ---------------------------------------------------------------------------


class TestCIMonitorSettingsEndpoints:
    """GET/POST /api/ci-monitor/settings use ctx.state, not orch.state."""

    @pytest.mark.asyncio
    async def test_get_ci_monitor_settings_without_orchestrator(self, _router_no_orch):
        router, _state = _router_no_orch
        handler = find_endpoint(router, "/api/ci-monitor/settings", method="GET")
        assert handler is not None
        response = await handler()
        data = json.loads(response.body)
        assert data == CIMonitorSettings().model_dump()

    @pytest.mark.asyncio
    async def test_post_ci_monitor_settings_without_orchestrator(self, _router_no_orch):
        router, state = _router_no_orch
        handler = find_endpoint(router, "/api/ci-monitor/settings", method="POST")
        assert handler is not None
        response = await handler(body={"branch": "develop", "create_issue": False})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["branch"] == "develop"
        assert data["create_issue"] is False
        settings = state.get_ci_monitor_settings()
        assert settings.branch == "develop"
        assert settings.create_issue is False


# ---------------------------------------------------------------------------
# Code Grooming Settings
# ---------------------------------------------------------------------------


class TestCodeGroomingSettingsEndpoints:
    """GET/POST /api/code-grooming/settings use ctx.state, not orch.state."""

    @pytest.mark.asyncio
    async def test_get_code_grooming_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, _state = _router_no_orch
        handler = find_endpoint(router, "/api/code-grooming/settings", method="GET")
        assert handler is not None
        response = await handler()
        data = json.loads(response.body)
        assert data == CodeGroomingSettings().model_dump()

    @pytest.mark.asyncio
    async def test_post_code_grooming_settings_without_orchestrator(
        self, _router_no_orch
    ):
        router, state = _router_no_orch
        handler = find_endpoint(router, "/api/code-grooming/settings", method="POST")
        assert handler is not None
        response = await handler(body={"max_issues_per_cycle": 10, "dry_run": True})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["max_issues_per_cycle"] == 10
        assert data["dry_run"] is True
        settings = state.get_code_grooming_settings()
        assert settings.max_issues_per_cycle == 10
        assert settings.dry_run is True


# ---------------------------------------------------------------------------
# Source-level guard: no orch.state in settings endpoints
# ---------------------------------------------------------------------------


class TestNoOrchStateInSettings:
    """Ensure _control_routes.py settings section uses ctx.state, not orch.state."""

    def test_no_orch_state_in_settings_endpoints(self):
        """Grep the source to confirm orch.state.get_*_settings is gone."""
        import inspect

        from dashboard_routes import _control_routes

        source = inspect.getsource(_control_routes)
        for name in (
            "dependabot_merge",
            "stale_issue",
            "security_patch",
            "ci_monitor",
            "code_grooming",
        ):
            assert f"orch.state.get_{name}_settings" not in source
            assert f"orch.state.set_{name}_settings" not in source
