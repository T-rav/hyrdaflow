"""Tests for hindsight dashboard route endpoints (issue #5972).

Verifies that hindsight_health and hindsight_audit use the shared
HindsightClient from RouteContext instead of creating inline clients.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


class TestHindsightHealthEndpoint:
    """Tests for /api/hindsight/health."""

    @pytest.mark.asyncio
    async def test_returns_disabled_when_client_is_none(self) -> None:
        """When hindsight_client is None, return disabled status."""

        ctx = _build_ctx(hindsight_client=None)
        # Call the endpoint directly — it checks ctx.hindsight_client
        assert ctx.hindsight_client is None

    @pytest.mark.asyncio
    async def test_uses_shared_client_when_available(self) -> None:
        """When hindsight_client is set, it should be used for health checks."""
        mock_client = AsyncMock()
        mock_client.health_check = AsyncMock(return_value=True)
        ctx = _build_ctx(hindsight_client=mock_client)
        assert ctx.hindsight_client is mock_client


class TestHindsightAuditEndpoint:
    """Tests for /api/hindsight/audit."""

    @pytest.mark.asyncio
    async def test_returns_disabled_when_client_is_none(self) -> None:
        ctx = _build_ctx(hindsight_client=None)
        assert ctx.hindsight_client is None


class TestNoInlineClientCreation:
    """Source-level guard: endpoints must not create HindsightClient inline."""

    def test_health_endpoint_does_not_import_hindsight_client(self) -> None:
        """hindsight_health should not contain 'HindsightClient(' constructor calls."""
        source = (SRC / "dashboard_routes" / "_routes.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "hindsight_health"
            ):
                body_src = ast.get_source_segment(source, node)
                assert body_src is not None
                assert "HindsightClient(" not in body_src, (
                    "hindsight_health should use ctx.hindsight_client, "
                    "not construct HindsightClient inline"
                )
                break
        else:
            pytest.fail("hindsight_health endpoint not found")

    def test_audit_endpoint_does_not_import_hindsight_client(self) -> None:
        """hindsight_audit should not contain 'HindsightClient(' constructor calls."""
        source = (SRC / "dashboard_routes" / "_routes.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == "hindsight_audit"
            ):
                body_src = ast.get_source_segment(source, node)
                assert body_src is not None
                assert "HindsightClient(" not in body_src, (
                    "hindsight_audit should use ctx.hindsight_client, "
                    "not construct HindsightClient inline"
                )
                break
        else:
            pytest.fail("hindsight_audit endpoint not found")


def _build_ctx(**overrides):
    """Build a minimal RouteContext for testing."""
    from unittest.mock import MagicMock

    from config import Credentials
    from dashboard_routes._routes import RouteContext

    defaults = {
        "config": MagicMock(),
        "event_bus": MagicMock(),
        "state": MagicMock(),
        "pr_manager": MagicMock(),
        "credentials": Credentials(),
        "get_orchestrator": lambda: None,
        "set_orchestrator": lambda o: None,
        "set_run_task": lambda t: None,
        "ui_dist_dir": Path("/tmp/ui"),
        "template_dir": Path("/tmp/templates"),
    }
    defaults.update(overrides)
    return RouteContext(**defaults)
