"""Dashboard route handlers for the HydraFlow dashboard API.

This package was refactored from a single 4,000-line module into a package
with a shared ``RouterContext`` and grouped route sub-modules.  The public
API (``create_router`` and module-level helpers) is preserved for backward
compatibility.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter

from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from state import StateTracker

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator
# Re-export module-level helpers that tests import directly.
from dashboard_routes._helpers import (  # noqa: F401
    _extract_field_from_sources,
    _extract_repo_path,
    _extract_repo_slug,
    _find_repo_match,
    _is_likely_disconnect,
    _parse_compat_json_object,
    logger,
)
from repo_runtime import RepoRuntimeRegistry
from repo_store import RepoRecord, RepoStore


def create_router(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    pr_manager: PRManager,
    get_orchestrator: Callable[[], HydraFlowOrchestrator | None],
    set_orchestrator: Callable[[HydraFlowOrchestrator], None],
    set_run_task: Callable[[asyncio.Task[None]], None],
    ui_dist_dir: Path,
    template_dir: Path,
    *,
    registry: RepoRuntimeRegistry | None = None,
    repo_store: RepoStore | None = None,
    register_repo_cb: Callable[
        [Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]
    ]
    | None = None,
    remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None,
    list_repos_cb: Callable[[], list[RepoRecord]] | None = None,
    default_repo_slug: str | None = None,
    allowed_repo_roots_fn: Callable[[], tuple[str, ...]] | None = None,
) -> APIRouter:
    """Create an APIRouter with all dashboard route handlers.

    When *registry* is provided, operational endpoints accept an optional
    ``repo`` query parameter to target a specific repo runtime.  When the
    parameter is omitted, the single-repo defaults (*config*, *state*,
    *event_bus*, and *get_orchestrator*) are used for backward compatibility.
    """
    from dashboard_routes._context import RouterContext
    from dashboard_routes._control_routes import register_control_routes
    from dashboard_routes._core_routes import (
        register_core_routes,
        register_spa_catchall,
    )
    from dashboard_routes._hitl_routes import register_hitl_routes
    from dashboard_routes._issue_routes import register_issue_routes
    from dashboard_routes._metrics_routes import register_metrics_routes
    from dashboard_routes._misc_routes import register_misc_routes
    from dashboard_routes._repo_routes import register_repo_routes
    from dashboard_routes._state_routes import register_state_routes

    router = APIRouter()

    ctx = RouterContext(
        config=config,
        event_bus=event_bus,
        state=state,
        pr_manager=pr_manager,
        get_orchestrator=get_orchestrator,
        set_orchestrator=set_orchestrator,
        set_run_task=set_run_task,
        ui_dist_dir=ui_dist_dir,
        template_dir=template_dir,
        registry=registry,
        repo_store=repo_store,
        register_repo_cb=register_repo_cb,
        remove_repo_cb=remove_repo_cb,
        list_repos_cb=list_repos_cb,
        default_repo_slug=default_repo_slug,
        allowed_repo_roots_fn=allowed_repo_roots_fn,
    )

    # Register route groups (order matters for some path patterns).
    register_core_routes(router, ctx)
    register_state_routes(router, ctx)
    register_hitl_routes(router, ctx)
    register_control_routes(router, ctx)
    register_issue_routes(router, ctx)
    register_metrics_routes(router, ctx)
    register_repo_routes(router, ctx)
    register_misc_routes(router, ctx)

    # SPA catch-all MUST be registered last so it doesn't shadow API routes.
    register_spa_catchall(router, ctx)

    return router
