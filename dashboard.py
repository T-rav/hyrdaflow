"""Live web dashboard for HydraFlow — FastAPI + WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from state import StateTracker

if TYPE_CHECKING:
    from fastapi import FastAPI

    from orchestrator import HydraFlowOrchestrator

logger = logging.getLogger("hydraflow.dashboard")

# React build output or fallback HTML template
_UI_DIST_DIR = Path(__file__).parent / "ui" / "dist"
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


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
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._state = state
        self._orchestrator = orchestrator
        self._server_task: asyncio.Task[None] | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._app: FastAPI | None = None

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

        app = FastAPI(title="HydraFlow Dashboard", version="1.0.0")

        # Serve React build if available
        if _UI_DIST_DIR.exists() and (_UI_DIST_DIR / "index.html").exists():
            assets_dir = _UI_DIST_DIR / "assets"
            if assets_dir.exists():
                app.mount(
                    "/assets",
                    StaticFiles(directory=str(assets_dir)),
                    name="assets",
                )

        # Serve static files (fallback dashboard JS, etc.)
        if _STATIC_DIR.exists():
            app.mount(
                "/static",
                StaticFiles(directory=str(_STATIC_DIR)),
                name="static",
            )

        pr_mgr = PRManager(self._config, self._bus)
        router = create_router(
            config=self._config,
            event_bus=self._bus,
            state=self._state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: self._orchestrator,
            set_orchestrator=self._set_orchestrator,
            set_run_task=self._set_run_task,
            ui_dist_dir=_UI_DIST_DIR,
            template_dir=_TEMPLATE_DIR,
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
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self._config.dashboard_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(server.serve())
        logger.info(
            "Dashboard running at http://localhost:%d",
            self._config.dashboard_port,
        )

    async def stop(self) -> None:
        """Stop the background server task."""
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._server_task
        logger.info("Dashboard stopped")
