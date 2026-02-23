"""Tests for PATCH /api/control/config endpoint with persist flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from events import EventBus
from tests.helpers import ConfigFactory


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
    )


def _find_endpoint(router, path, method="PATCH"):
    for route in router.routes:
        if (
            hasattr(route, "path")
            and route.path == path
            and hasattr(route, "endpoint")
            and hasattr(route, "methods")
            and method in route.methods
        ):
            return route.endpoint  # type: ignore[union-attr]
    return None


class TestPatchConfigEndpoint:
    """Tests for the PATCH /api/control/config endpoint."""

    @pytest.mark.asyncio
    async def test_patch_config_route_exists(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Router should include PATCH /api/control/config."""
        router = _make_router(config, event_bus, state, tmp_path)

        paths = set()
        for route in router.routes:
            if hasattr(route, "path"):
                paths.add(route.path)

        assert "/api/control/config" in paths

    @pytest.mark.asyncio
    async def test_patch_config_updates_runtime_config(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH should update config fields in memory."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        response = await endpoint({"max_workers": 5, "model": "opus"})
        data = json.loads(response.body)

        assert data["status"] == "ok"
        assert config.max_workers == 5
        assert config.model == "opus"

    @pytest.mark.asyncio
    async def test_patch_config_with_persist_writes_file(
        self, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH with persist=true should write changes to config file."""
        config_path = tmp_path / ".hydraflow" / "config.json"
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        # Set config_file path on config
        object.__setattr__(cfg, "config_file", config_path)
        router = _make_router(cfg, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        response = await endpoint({"max_workers": 8, "persist": True})
        data = json.loads(response.body)

        assert data["status"] == "ok"
        assert cfg.max_workers == 8

        # Verify file was written
        assert config_path.exists()
        file_data = json.loads(config_path.read_text())
        assert file_data["max_workers"] == 8

    @pytest.mark.asyncio
    async def test_patch_config_without_persist_does_not_write(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH without persist should not write to disk."""
        config_path = tmp_path / ".hydraflow" / "config.json"
        object.__setattr__(config, "config_file", config_path)
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        await endpoint({"max_workers": 8})

        assert not config_path.exists()

    @pytest.mark.asyncio
    async def test_patch_config_ignores_unknown_fields(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Unknown fields in PATCH body should be silently ignored."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        original_workers = config.max_workers
        response = await endpoint({"not_a_field": "value"})
        data = json.loads(response.body)

        assert data["status"] == "ok"
        assert config.max_workers == original_workers

    @pytest.mark.asyncio
    async def test_patch_config_returns_updated_values(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH response should include the updated config values."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        response = await endpoint({"max_workers": 6})
        data = json.loads(response.body)

        assert data["status"] == "ok"
        assert data["updated"]["max_workers"] == 6

    @pytest.mark.asyncio
    async def test_patch_config_persist_flag_not_saved_to_file(
        self, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """The 'persist' flag itself should not be saved to the config file."""
        config_path = tmp_path / ".hydraflow" / "config.json"
        cfg = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        object.__setattr__(cfg, "config_file", config_path)
        router = _make_router(cfg, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        await endpoint({"max_workers": 4, "persist": True})

        file_data = json.loads(config_path.read_text())
        assert "persist" not in file_data

    @pytest.mark.asyncio
    async def test_patch_config_rejects_invalid_int_below_min(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH should reject values that violate Pydantic field constraints (ge)."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        original = config.max_workers
        response = await endpoint({"max_workers": 0})
        data = json.loads(response.body)

        assert response.status_code == 422
        assert data["status"] == "error"
        assert config.max_workers == original  # Unchanged

    @pytest.mark.asyncio
    async def test_patch_config_rejects_invalid_int_above_max(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH should reject values that violate Pydantic field constraints (le)."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        original = config.max_workers
        response = await endpoint({"max_workers": 999})
        data = json.loads(response.body)

        assert response.status_code == 422
        assert data["status"] == "error"
        assert config.max_workers == original  # Unchanged

    @pytest.mark.asyncio
    async def test_patch_config_rejects_negative_budget(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH should reject negative budget values (ge=0 constraint)."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        response = await endpoint({"max_budget_usd": -5.0})
        data = json.loads(response.body)

        assert response.status_code == 422
        assert data["status"] == "error"

    @pytest.mark.asyncio
    async def test_patch_config_accepts_valid_boundary_values(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH should accept values at the boundary of valid ranges."""
        router = _make_router(config, event_bus, state, tmp_path)
        endpoint = _find_endpoint(router, "/api/control/config")
        assert endpoint is not None

        response = await endpoint({"max_workers": 10})
        data = json.loads(response.body)

        assert data["status"] == "ok"
        assert config.max_workers == 10
