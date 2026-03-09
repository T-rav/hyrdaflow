"""Shared dependency container for dashboard sub-routers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException

from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from state import StateTracker

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator
    from repo_runtime import RepoRuntime, RepoRuntimeRegistry
    from repo_store import RepoRecord, RepoStore


@dataclass
class RouterDeps:
    """Bundles all dependencies that dashboard sub-routers need.

    Replaces closure-captured variables so that extracted modules can
    access shared state without being defined inside ``create_router()``.
    """

    config: HydraFlowConfig
    event_bus: EventBus
    state: StateTracker
    pr_manager: PRManager
    get_orchestrator: Callable[[], HydraFlowOrchestrator | None]
    set_orchestrator: Callable[[HydraFlowOrchestrator], None]
    set_run_task: Callable[[asyncio.Task[None]], None]
    ui_dist_dir: Path
    template_dir: Path
    # Optional multi-repo support
    registry: RepoRuntimeRegistry | None = None
    repo_store: RepoStore | None = None
    register_repo_cb: (
        Callable[[Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]]
        | None
    ) = None
    remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None
    list_repos_cb: Callable[[], list[RepoRecord]] | None = None
    default_repo_slug: str | None = None
    # HITL summary concurrency state
    hitl_summary_inflight: set[int] = field(default_factory=set)
    hitl_summary_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(3)
    )
    hitl_summary_cooldown_seconds: int = 300

    # ------------------------------------------------------------------
    # Shared helpers used by multiple sub-routers
    # ------------------------------------------------------------------

    def resolve_runtime(
        self,
        slug: str | None,
    ) -> tuple[
        HydraFlowConfig,
        StateTracker,
        EventBus,
        Callable[[], HydraFlowOrchestrator | None],
    ]:
        """Resolve per-repo dependencies from the registry.

        When *slug* is ``None`` or no registry is configured, returns the
        single-repo closure defaults for backward compatibility.
        """
        if self.registry is not None and slug is not None:
            rt: RepoRuntime | None = self.registry.get(slug)
            if rt is None:
                raise HTTPException(status_code=404, detail=f"Unknown repo: {slug}")
            return rt.config, rt.state, rt.event_bus, lambda: rt.orchestrator
        return self.config, self.state, self.event_bus, self.get_orchestrator

    def pr_manager_for(self, cfg: HydraFlowConfig, bus: EventBus) -> PRManager:
        """Return the shared PRManager when config matches; otherwise create a new one."""
        if cfg is self.config and bus is self.event_bus:
            return self.pr_manager
        return PRManager(cfg, bus)
