"""Tests for RouteContext dataclass in dashboard_routes.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Credentials, HydraFlowConfig
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
    credentials: Credentials | None = None,
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
        credentials=credentials or Credentials(),
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

    def test_falls_back_to_defaults_for_unknown_slug(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        registry = MagicMock()
        registry.get.return_value = None
        registry.all = []
        ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

        cfg, st, bus, get_orch = ctx.resolve_runtime("missing-repo")

        # Falls back to defaults instead of 404
        assert cfg is config
        assert st is state
        assert bus is event_bus


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
            credentials=Credentials(),
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
            credentials=Credentials(),
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
            credentials=Credentials(),
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
    async def test_falls_back_to_defaults_for_unknown_repo(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        registry = MagicMock()
        registry.get.return_value = None
        registry.all = []
        task_fn = AsyncMock(return_value=MagicMock(success=True, as_dict=lambda: {}))
        ctx = _make_ctx(config, event_bus, state, tmp_path, registry=registry)

        response = await ctx.execute_admin_task("test-task", task_fn, "missing")

        # Falls back to default config instead of 404
        assert response.status_code == 200

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


class TestRouteContextComputeHitlSummary:
    """P2 — compute_hitl_summary generates and persists a HITL summary."""

    @pytest.mark.asyncio
    async def test_returns_none_when_summarization_disabled(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        config.transcript_summarization_enabled = False
        ctx = _make_ctx(config, event_bus, state, tmp_path)

        result = await ctx.compute_hitl_summary(1, cause="x", origin=None)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_issue_fetch_fails(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        config.transcript_summarization_enabled = True
        config.dry_run = False
        creds = Credentials(gh_token="tok")
        ctx = _make_ctx(config, event_bus, state, tmp_path, credentials=creds)
        ctx.issue_fetcher = MagicMock()
        ctx.issue_fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        result = await ctx.compute_hitl_summary(1, cause="x", origin=None)

        assert result is None
        failed_at, _ = state.get_hitl_summary_failure(1)
        assert failed_at is not None

    @pytest.mark.asyncio
    async def test_returns_summary_on_success(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        config.transcript_summarization_enabled = True
        config.dry_run = False
        creds = Credentials(gh_token="tok")
        ctx = _make_ctx(config, event_bus, state, tmp_path, credentials=creds)
        issue = MagicMock()
        issue.number = 42
        issue.title = "Test issue"
        issue.body = "body text"
        issue.comments = []
        ctx.issue_fetcher = MagicMock()
        ctx.issue_fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        ctx.hitl_summarizer = MagicMock()
        ctx.hitl_summarizer.summarize_hitl_context = AsyncMock(
            return_value="line one\nline two"
        )

        result = await ctx.compute_hitl_summary(42, cause="ci failure", origin="review")

        assert result == "line one\nline two"
        assert state.get_hitl_summary(42) == "line one\nline two"

    @pytest.mark.asyncio
    async def test_returns_none_when_summarizer_returns_empty(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        config.transcript_summarization_enabled = True
        config.dry_run = False
        creds = Credentials(gh_token="tok")
        ctx = _make_ctx(config, event_bus, state, tmp_path, credentials=creds)
        issue = MagicMock()
        issue.number = 10
        issue.title = "Test"
        issue.body = ""
        issue.comments = []
        ctx.issue_fetcher = MagicMock()
        ctx.issue_fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        ctx.hitl_summarizer = MagicMock()
        ctx.hitl_summarizer.summarize_hitl_context = AsyncMock(return_value="")

        result = await ctx.compute_hitl_summary(10, cause="x", origin=None)

        assert result is None
        failed_at, _ = state.get_hitl_summary_failure(10)
        assert failed_at is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_normalization_produces_empty(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        config.transcript_summarization_enabled = True
        config.dry_run = False
        creds = Credentials(gh_token="tok")
        ctx = _make_ctx(config, event_bus, state, tmp_path, credentials=creds)
        issue = MagicMock()
        issue.number = 11
        issue.title = "Test"
        issue.body = ""
        issue.comments = []
        ctx.issue_fetcher = MagicMock()
        ctx.issue_fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        ctx.hitl_summarizer = MagicMock()
        # Return a string of only whitespace/dashes — normalisation strips these to ""
        ctx.hitl_summarizer.summarize_hitl_context = AsyncMock(return_value="  -  \n  ")

        result = await ctx.compute_hitl_summary(11, cause="x", origin=None)

        assert result is None
        failed_at, _ = state.get_hitl_summary_failure(11)
        assert failed_at is not None


class TestRouteContextWarmHitlSummary:
    """P2 — warm_hitl_summary guards against duplicate inflight requests."""

    @pytest.mark.asyncio
    async def test_skips_when_already_inflight(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)
        ctx.hitl_summary_inflight.add(7)
        ctx.compute_hitl_summary = AsyncMock()

        await ctx.warm_hitl_summary(7, cause="x", origin=None)

        ctx.compute_hitl_summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_removes_from_inflight_after_completion(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)
        ctx.compute_hitl_summary = AsyncMock(return_value="summary text")

        await ctx.warm_hitl_summary(8, cause="x", origin=None)

        assert 8 not in ctx.hitl_summary_inflight

    @pytest.mark.asyncio
    async def test_removes_from_inflight_on_exception(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        tmp_path: Path,
    ) -> None:
        ctx = _make_ctx(config, event_bus, state, tmp_path)
        ctx.compute_hitl_summary = AsyncMock(side_effect=RuntimeError("boom"))

        await ctx.warm_hitl_summary(9, cause="x", origin=None)

        assert 9 not in ctx.hitl_summary_inflight
        failed_at, _ = state.get_hitl_summary_failure(9)
        assert failed_at is not None


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
