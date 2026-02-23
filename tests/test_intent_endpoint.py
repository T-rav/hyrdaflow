"""Tests for the POST /api/intent endpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus


def _make_router(config, event_bus, state, tmp_path):
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


def _find_endpoint(router, path, method="POST"):
    for route in router.routes:
        if hasattr(route, "path") and route.path == path and hasattr(route, "endpoint"):
            # Check method matches if available
            if hasattr(route, "methods") and method not in route.methods:
                continue
            return route.endpoint
    return None


class TestIntentEndpoint:
    """Tests for POST /api/intent."""

    def test_intent_route_is_registered(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Verify /api/intent appears in router paths."""
        router, _ = _make_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/intent" in paths

    @pytest.mark.asyncio
    async def test_intent_creates_issue_with_planner_label(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Mock pr_manager.create_issue, verify it's called with planner_label."""
        from models import IntentRequest

        router, pr_mgr = _make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(return_value=42)

        endpoint = _find_endpoint(router, "/api/intent")
        assert endpoint is not None

        request = IntentRequest(text="add rate limiting to the API endpoints")
        response = await endpoint(request)
        data = json.loads(response.body)

        pr_mgr.create_issue.assert_called_once_with(
            title="add rate limiting to the API endpoints",
            body="add rate limiting to the API endpoints",
            labels=list(config.planner_label),
        )
        assert data["issue_number"] == 42
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_intent_returns_issue_number_and_url(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Happy path response validation."""
        from models import IntentRequest

        router, pr_mgr = _make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(return_value=99)

        endpoint = _find_endpoint(router, "/api/intent")
        assert endpoint is not None

        request = IntentRequest(text="build a login page")
        response = await endpoint(request)
        data = json.loads(response.body)

        assert data["issue_number"] == 99
        assert data["title"] == "build a login page"
        assert f"/issues/{99}" in data["url"]
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_intent_returns_500_on_create_failure(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """create_issue returns 0 → verify error response."""
        from models import IntentRequest

        router, pr_mgr = _make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(return_value=0)

        endpoint = _find_endpoint(router, "/api/intent")
        assert endpoint is not None

        request = IntentRequest(text="do something")
        response = await endpoint(request)
        assert response.status_code == 500

        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_intent_truncates_long_title(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Text > 120 chars: title is truncated, body is full text."""
        from models import IntentRequest

        router, pr_mgr = _make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_issue = AsyncMock(return_value=55)

        endpoint = _find_endpoint(router, "/api/intent")
        assert endpoint is not None

        long_text = "a" * 200
        request = IntentRequest(text=long_text)
        response = await endpoint(request)
        data = json.loads(response.body)

        call_args = pr_mgr.create_issue.call_args
        assert len(call_args.kwargs["title"]) == 120
        assert call_args.kwargs["body"] == long_text
        assert data["issue_number"] == 55

    def test_intent_rejects_empty_text(self) -> None:
        """IntentRequest with empty text should fail Pydantic validation."""
        from pydantic import ValidationError

        from models import IntentRequest

        with pytest.raises(ValidationError):
            IntentRequest(text="")
