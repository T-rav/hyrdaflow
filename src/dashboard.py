"""Live web dashboard for HydraFlow — FastAPI + WebSocket."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from app_version import get_app_version
from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from state import StateTracker

if TYPE_CHECKING:
    from fastapi import FastAPI

    from orchestrator import HydraFlowOrchestrator
    from repo_runtime import RepoRuntimeRegistry

logger = logging.getLogger("hydraflow.dashboard")

# React build output or fallback HTML template
_REPO_ROOT = Path(__file__).resolve().parent.parent
_UI_DIST_DIR = _REPO_ROOT / "src" / "ui" / "dist"
_TEMPLATE_DIR = _REPO_ROOT / "templates"
_STATIC_DIR = _REPO_ROOT / "static"


def _auto_start_supervisor_enabled() -> bool:
    """Whether dashboard startup should auto-start the local supervisor."""
    raw = os.environ.get("HYDRAFLOW_AUTO_START_SUPERVISOR")
    if raw is None:
        legacy = os.environ.get("HF_AUTO_START_SUPERVISOR")
        if legacy is not None:
            logger.warning(
                "HF_AUTO_START_SUPERVISOR is deprecated; use HYDRAFLOW_AUTO_START_SUPERVISOR"
            )
            raw = legacy
    if raw is None:
        return True
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "Invalid HYDRAFLOW_AUTO_START_SUPERVISOR=%r; defaulting to enabled",
        raw,
    )
    return True


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
        *,
        registry: RepoRuntimeRegistry | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._state = state
        self._orchestrator = orchestrator
        self._registry = registry
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

        app = FastAPI(title="HydraFlow Dashboard", version=get_app_version())

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
            registry=self._registry,
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

        if _auto_start_supervisor_enabled():
            try:
                supervisor_manager = importlib.import_module(
                    "hf_cli.supervisor_manager"
                )
                await asyncio.to_thread(supervisor_manager.ensure_running)
            except ImportError:
                logger.debug(
                    "hf_cli.supervisor_manager not importable; skipping supervisor auto-start"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Supervisor auto-start failed: %s", exc)

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
