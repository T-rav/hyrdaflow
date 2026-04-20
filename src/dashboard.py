"""Live web dashboard for HydraFlow — FastAPI + WebSocket.

Provides the ``HydraFlowDashboard`` class for embedding into the
HydraFlow server process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app_version import get_app_version
from config import Credentials, HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from state import StateTracker

if TYPE_CHECKING:
    from fastapi import FastAPI

    from hindsight import HindsightClient  # noqa: F811
    from orchestrator import HydraFlowOrchestrator
    from repo_runtime import RepoRuntimeRegistry
    from repo_store import RepoRecord, RepoStore

logger = logging.getLogger("hydraflow.dashboard")

# React build output or fallback HTML template
_REPO_ROOT = Path(__file__).resolve().parent.parent
_UI_DIST_DIR = _REPO_ROOT / "src" / "ui" / "dist"
_TEMPLATE_DIR = _REPO_ROOT / "templates"
_STATIC_DIR = _REPO_ROOT / "static"


class HydraFlowDashboard:
    """Serves the live dashboard and streams events via WebSocket.

    Runs a uvicorn server in a background asyncio task so it
    doesn't block the orchestrator.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        state: StateTracker,
        orchestrator: HydraFlowOrchestrator | None = None,
        registry: RepoRuntimeRegistry | None = None,
        repo_store: RepoStore | None = None,
        register_repo_cb: Callable[
            [Path, str | None], Awaitable[tuple[RepoRecord, HydraFlowConfig]]
        ]
        | None = None,
        remove_repo_cb: Callable[[str], Awaitable[bool]] | None = None,
        list_repos_cb: Callable[[], list[RepoRecord]] | None = None,
        default_repo_slug: str | None = None,
        ui_dist_dir: Path | None = None,
        template_dir: Path | None = None,
        static_dir: Path | None = None,
        credentials: Credentials | None = None,
        hindsight_client: HindsightClient | None = None,
    ) -> None:
        self._config = config
        self._credentials = credentials
        self._bus = event_bus
        self._state = state
        self._orchestrator = orchestrator
        self._registry = registry
        self._repo_store = repo_store
        self._register_repo_cb = register_repo_cb
        self._remove_repo_cb = remove_repo_cb
        self._list_repos_cb = list_repos_cb
        self._default_repo_slug = default_repo_slug
        self._hindsight_client = hindsight_client
        self._ui_dist_dir = ui_dist_dir if ui_dist_dir is not None else _UI_DIST_DIR
        self._template_dir = template_dir if template_dir is not None else _TEMPLATE_DIR
        self._static_dir = static_dir if static_dir is not None else _STATIC_DIR
        self._server_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._app: FastAPI | None = None
        self._uvicorn_server: Any = None

    def create_app(self) -> FastAPI:
        """Build and return the FastAPI application."""
        try:
            from fastapi import FastAPI
        except ImportError:
            logger.error(
                "FastAPI not installed. Run: uv pip install fastapi uvicorn websockets"
            )
            raise

        from fastapi.staticfiles import StaticFiles

        from dashboard_routes import create_router

        app = FastAPI(title="HydraFlow Dashboard", version=get_app_version())

        # Serve React build if available
        ui_dist_dir = self._ui_dist_dir
        if ui_dist_dir.exists() and (ui_dist_dir / "index.html").exists():
            assets_dir = ui_dist_dir / "assets"
            if assets_dir.exists():
                app.mount(
                    "/assets",
                    StaticFiles(directory=str(assets_dir)),
                    name="assets",
                )

        # Serve static files (fallback dashboard JS, etc.)
        if self._static_dir.exists():
            app.mount(
                "/static",
                StaticFiles(directory=str(self._static_dir)),
                name="static",
            )

        pr_mgr = PRManager(self._config, self._bus, credentials=self._credentials)
        router = create_router(
            config=self._config,
            event_bus=self._bus,
            state=self._state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: self._orchestrator,
            set_orchestrator=self._set_orchestrator,
            set_run_task=self._set_run_task,
            ui_dist_dir=ui_dist_dir,
            template_dir=self._template_dir,
            credentials=self._credentials,
            registry=self._registry,
            repo_store=self._repo_store,
            register_repo_cb=self._register_repo_cb,
            remove_repo_cb=self._remove_repo_cb,
            list_repos_cb=self._list_repos_cb,
            default_repo_slug=self._default_repo_slug,
            hindsight_client=self._hindsight_client,
        )
        app.include_router(router)

        self._app = app
        return app

    def _set_orchestrator(self, orch: HydraFlowOrchestrator) -> None:
        self._orchestrator = orch

    def _set_run_task(self, task: asyncio.Task[None]) -> None:
        self._run_task = task

    async def start(self) -> None:
        """Start the dashboard server in a background task."""
        try:
            import uvicorn
        except ImportError:
            logger.warning("uvicorn not installed — dashboard disabled")
            return

        app = self.create_app()
        bind_host = self._config.dashboard_host
        config = uvicorn.Config(
            app,
            host=bind_host,
            port=self._config.dashboard_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server

        async def _serve_safe() -> None:
            try:
                await server.serve()
            except (SystemExit, OSError) as exc:
                logger.error(
                    "Dashboard failed to bind %s:%d — %s",
                    bind_host,
                    self._config.dashboard_port,
                    exc,
                )

        self._server_task = asyncio.create_task(_serve_safe())
        logger.info(
            "Dashboard running at http://%s:%d",
            bind_host,
            self._config.dashboard_port,
        )

    async def stop(self) -> None:
        """Stop the background server task."""
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._server_task
        logger.info("Dashboard stopped")
