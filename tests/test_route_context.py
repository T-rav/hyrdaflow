"""Tests for RouteContext dataclass in dashboard_routes.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from config import HydraFlowConfig
from dashboard_routes import RouteContext
from events import EventBus
from state import StateTracker
from tests.helpers import make_dashboard_router


def _make_ctx(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    tmp_path: Path,
    *,
    registry: object | None = None,
    repo_store: object | None = None,
    register_repo_cb: object | None = None,
    remove_repo_cb: object | None = None,
    list_repos_cb: object | None = None,
    default_repo_slug: str | None = None,
    allowed_repo_roots_fn: object | None = None,
) -> RouteContext:
    """Build a RouteContext with test-friendly defaults."""
    from pr_manager import PRManager

    pr_mgr = PRManager(config, event_bus)
    return RouteContext(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_mgr,
        get_orchestrator=lambda: None,
        set_orchestrator=lambda o: None,
        set_run_task=lambda t: None,
        ui_dist_dir=tmp_path / "no-dist",
        template_dir=tmp_path / "no-templates",
        registry=registry,
        repo_store=repo_store,
        register_repo_cb=register_repo_cb,
        remove_repo_cb=remove_repo_cb,
        list_repos_cb=list_repos_cb,
        default_repo_slug=default_repo_slug,
        allowed_repo_roots_fn=allowed_repo_roots_fn,
    )


class TestRouteContextConstruction:
    """P1 — RouteContext dataclass can be constructed and exposes all fields."""

    def test_dataclass_has_all_expected_fields(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        assert ctx.config is config
        assert ctx.event_bus is event_bus
        assert ctx.state is state
        assert ctx.pr_manager is not None
        assert ctx.get_orchestrator() is None
        assert ctx.ui_dist_dir == tmp_path / "no-dist"
        assert ctx.template_dir == tmp_path / "no-templates"

    def test_optional_fields_default_to_none(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        assert ctx.registry is None
        assert ctx.repo_store is None
        assert ctx.register_repo_cb is None
        assert ctx.remove_repo_cb is None
        assert ctx.list_repos_cb is None
        assert ctx.default_repo_slug is None
        assert ctx.allowed_repo_roots_fn is None

    def test_post_init_creates_derived_state(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        assert ctx.issue_fetcher is not None
        assert ctx.hitl_summarizer is not None
        assert isinstance(ctx.hitl_summary_inflight, set)
        assert len(ctx.hitl_summary_inflight) == 0
        assert ctx.hitl_summary_slots is not None

    def test_hitl_summary_cooldown_default(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)
        assert ctx.hitl_summary_cooldown_seconds == 300


class TestRouteContextResolveRuntime:
    """P2 — resolve_runtime method delegates correctly."""

    def test_returns_defaults_when_no_registry(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        cfg, st, bus, get_orch = ctx.resolve_runtime(None)

        assert cfg is config
        assert st is state
        assert bus is event_bus

    def test_returns_defaults_when_slug_is_none(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        registry = MagicMock()
        ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

        cfg, st, bus, get_orch = ctx.resolve_runtime(None)

        assert cfg is config
        assert st is state

    def test_resolves_from_registry_when_slug_provided(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        rt = MagicMock()
        rt.config = MagicMock(spec=HydraFlowConfig)
        rt.state = MagicMock()
        rt.event_bus = MagicMock()
        rt.orchestrator = MagicMock()
        registry = MagicMock()
        registry.get.return_value = rt
        ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

        cfg, st, bus, get_orch = ctx.resolve_runtime("my-repo")

        registry.get.assert_called_once_with("my-repo")
        assert cfg is rt.config
        assert st is rt.state
        assert bus is rt.event_bus
        assert get_orch() is rt.orchestrator

    def test_raises_404_for_unknown_slug(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        registry = MagicMock()
        registry.get.return_value = None
        ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

        with pytest.raises(HTTPException) as exc_info:
            ctx.resolve_runtime("missing-repo")

        assert exc_info.value.status_code == 404


class TestRouteContextPrManagerFor:
    """P2 — pr_manager_for returns shared or new instance."""

    def test_returns_shared_when_same_config_and_bus(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        result = ctx.pr_manager_for(config, event_bus)

        assert result is ctx.pr_manager

    def test_returns_new_when_different_config(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        from tests.conftest import ConfigFactory

        other_config = ConfigFactory.create()
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        result = ctx.pr_manager_for(other_config, event_bus)

        assert result is not ctx.pr_manager


class TestRouteContextListRepoRecords:
    """P2 — list_repo_records delegates to callback or store."""

    def test_returns_empty_when_no_callback_or_store(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        result = ctx.list_repo_records()

        assert result == []

    def test_uses_callback_when_provided(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        records = [MagicMock()]
        ctx = _make_ctx(
            config,
            event_bus,
            state,
            tmp_path,
            list_repos_cb=lambda: records,
        )

        result = ctx.list_repo_records()

        assert result is records

    def test_falls_back_to_store_when_callback_fails(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        store_records = [MagicMock()]
        store = MagicMock()
        store.list.return_value = store_records
        ctx = _make_ctx(
            config,
            event_bus,
            state,
            tmp_path,
            list_repos_cb=MagicMock(side_effect=RuntimeError("fail")),
            repo_store=store,
        )

        result = ctx.list_repo_records()

        assert result is store_records

    def test_returns_empty_when_both_fail(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        store = MagicMock()
        store.list.side_effect = RuntimeError("boom")
        ctx = _make_ctx(
            config,
            event_bus,
            state,
            tmp_path,
            list_repos_cb=MagicMock(side_effect=RuntimeError("fail")),
            repo_store=store,
        )

        result = ctx.list_repo_records()

        assert result == []


class TestRouteContextServeSpaIndex:
    """P2 — serve_spa_index returns correct HTML response."""

    def test_serves_react_index_when_exists(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ui_dir = tmp_path / "dist"
        ui_dir.mkdir()
        (ui_dir / "index.html").write_text("<html>React</html>")

        from pr_manager import PRManager

        ctx = RouteContext(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=PRManager(config, event_bus),
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=ui_dir,
            template_dir=tmp_path / "no-templates",
        )

        response = ctx.serve_spa_index()

        assert "React" in response.body.decode()

    def test_falls_back_to_template(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "index.html").write_text("<html>Template</html>")

        from pr_manager import PRManager

        ctx = RouteContext(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=PRManager(config, event_bus),
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmpl_dir,
        )

        response = ctx.serve_spa_index()

        assert "Template" in response.body.decode()

    def test_returns_placeholder_when_nothing_exists(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        response = ctx.serve_spa_index()

        assert "make ui" in response.body.decode().lower()


class TestRouteContextRepoRootsFn:
    """P2 — repo_roots_fn delegates correctly."""

    def test_uses_override_when_provided(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        custom_roots = ("/custom/root",)
        ctx = _make_ctx(
            config,
            event_bus,
            state,
            tmp_path,
            allowed_repo_roots_fn=lambda: custom_roots,
        )

        result = ctx.repo_roots_fn()

        assert result == custom_roots

    def test_uses_default_when_no_override(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        result = ctx.repo_roots_fn()

        # Should return a tuple of at least one root (home dir)
        assert isinstance(result, tuple)
        assert len(result) >= 1


class TestRouteContextHitlSummaryRetryDue:
    """P2 — hitl_summary_retry_due checks cooldown."""

    def test_returns_true_when_no_prior_failure(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        assert ctx.hitl_summary_retry_due(123) is True

    def test_returns_false_when_recently_failed(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:

        ctx = _make_ctx(config, event_bus, state, tmp_path)
        # Record a recent failure
        state.set_hitl_summary_failure(123, "test failure")

        assert ctx.hitl_summary_retry_due(123) is False

    def test_custom_cooldown_respected(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        from pr_manager import PRManager

        # Use a very long cooldown — a recent failure should block retry.
        ctx = RouteContext(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=PRManager(config, event_bus),
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
            hitl_summary_cooldown_seconds=9999,
        )
        state.set_hitl_summary_failure(456, "some failure")

        assert ctx.hitl_summary_retry_due(456) is False


class TestRouteContextExecuteAdminTask:
    """P2 — execute_admin_task delegates correctly."""

    @pytest.mark.asyncio
    async def test_runs_task_successfully(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        from admin_tasks import TaskResult

        result = TaskResult(success=True, log=["done"])
        task_fn = AsyncMock(return_value=result)
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        response = await ctx.execute_admin_task("test-task", task_fn, None)

        assert response.status_code == 200
        task_fn.assert_awaited_once_with(config)

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_repo(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        registry = MagicMock()
        registry.get.return_value = None
        ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

        response = await ctx.execute_admin_task("test-task", AsyncMock(), "missing")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_500_on_task_failure(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        from admin_tasks import TaskResult

        result = TaskResult(success=False, log=["boom"])
        task_fn = AsyncMock(return_value=result)
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        response = await ctx.execute_admin_task("test-task", task_fn, None)

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_returns_500_when_task_raises(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        task_fn = AsyncMock(side_effect=RuntimeError("unexpected failure"))
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        response = await ctx.execute_admin_task("test-task", task_fn, None)

        assert response.status_code == 500


class TestCreateRouterUsesRouteContext:
    """P3 — create_router constructs a RouteContext internally."""

    def test_create_router_still_works(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        """create_router signature unchanged — existing callers still work."""
        from fastapi import APIRouter

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

        assert isinstance(router, APIRouter)

    def test_route_context_is_importable(self) -> None:
        """RouteContext can be imported from dashboard_routes."""
        assert RouteContext is not None
