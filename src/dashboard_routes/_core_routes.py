"""Core and SPA route handlers for the HydraFlow dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from fastapi import APIRouter, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import dashboard_routes as _pkg
from app_version import get_app_version
from dashboard_routes._helpers import _is_likely_disconnect
from models import BGWorkerHealth

if TYPE_CHECKING:
    from dashboard_routes._context import RouterContext
    from events import HydraFlowEvent


def register_core_routes(router: APIRouter, ctx: RouterContext) -> None:
    """Register health-check, SPA index, and WebSocket routes on *router*."""

    @router.get("/healthz")
    def get_health() -> JSONResponse:
        """Lightweight readiness response for load balancers and monitors."""
        orchestrator = ctx.get_orchestrator()
        orchestrator_running = bool(getattr(orchestrator, "running", False))
        worker_states = ctx.state.get_bg_worker_states()
        session_counters = ctx.state.get_session_counters()
        session_started_at: str | None = session_counters.session_start or None
        uptime_seconds: int | None = None
        if session_started_at:
            try:
                started_dt = datetime.fromisoformat(session_started_at)
            except (ValueError, TypeError):
                session_started_at = None
            else:
                uptime_seconds = max(
                    int((datetime.now(UTC) - started_dt).total_seconds()),
                    0,
                )

        def _normalise_worker_health(
            raw_status: str | BGWorkerHealth | None,
        ) -> BGWorkerHealth:
            """Coerce a raw status value to a BGWorkerHealth enum member."""
            if isinstance(raw_status, BGWorkerHealth):
                return raw_status
            try:
                return BGWorkerHealth(str(raw_status or "").lower())
            except ValueError:
                return BGWorkerHealth.DISABLED

        worker_count = len(worker_states)
        worker_errors = sorted(
            name
            for name, heartbeat in worker_states.items()
            if _normalise_worker_health(heartbeat.get("status")) == BGWorkerHealth.ERROR
        )
        if orchestrator is None:
            orchestrator_running = False
        orchestrator_status = "missing"
        if orchestrator is not None and orchestrator_running:
            orchestrator_status = "running"
        elif orchestrator is not None:
            orchestrator_status = "idle"

        worker_status = "disabled"
        if worker_count > 0:
            worker_status = "degraded" if worker_errors else "ok"

        status = "ok"
        if orchestrator_status == "missing":
            status = "starting"
        elif orchestrator_status == "idle":
            status = "idle"
        if worker_status == "degraded":
            status = "degraded"

        def _is_loopback_host(host: str) -> bool:
            host_lower = (host or "").lower()
            return host_lower == "localhost" or host_lower.startswith("127.")

        dashboard_binding = {
            "host": ctx.config.dashboard_host,
            "port": ctx.config.dashboard_port,
        }
        dashboard_public = not _is_loopback_host(ctx.config.dashboard_host)

        checks = {
            "orchestrator": {
                "status": orchestrator_status,
                "running": orchestrator_running,
                "session_started_at": session_started_at,
            },
            "workers": {
                "status": worker_status,
                "count": worker_count,
                "errors": worker_errors,
            },
            "dashboard": {
                "status": "ok" if ctx.config.dashboard_enabled else "disabled",
                "host": ctx.config.dashboard_host,
                "port": ctx.config.dashboard_port,
                "public": dashboard_public,
            },
        }
        ready = checks["orchestrator"]["status"] == "running" and checks["workers"][
            "status"
        ] in {"ok", "disabled"}
        payload = {
            "status": status,
            "version": get_app_version(),
            "timestamp": datetime.now(UTC).isoformat(),
            "orchestrator_running": orchestrator_running,
            "active_issue_count": len(ctx.state.get_active_issue_numbers()),
            "active_worktrees": len(ctx.state.get_active_worktrees()),
            "worker_count": worker_count,
            "worker_errors": worker_errors,
            "dashboard": dashboard_binding,
            "session_started_at": session_started_at,
            "uptime_seconds": uptime_seconds,
            "ready": ready,
            "checks": checks,
        }
        return JSONResponse(payload)

    @router.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Serve the single-page application root."""
        return ctx.serve_spa_index()

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Stream event history then live events over a WebSocket connection."""
        from fastapi import HTTPException

        repo_slug: str | None = ws.query_params.get("repo")
        try:
            _cfg, _state, bus, _get_orch = ctx.resolve_runtime(repo_slug)
        except (ValueError, HTTPException):
            await ws.accept()
            await ws.close(code=1008, reason=f"Unknown repo: {repo_slug}")
            return
        await ws.accept()
        history = bus.get_history()
        async with bus.subscription() as queue:
            for event in history:
                try:
                    await ws.send_text(event.model_dump_json())
                except Exception as exc:
                    if _is_likely_disconnect(exc):
                        _pkg.logger.warning(
                            "WebSocket disconnect during history replay: %s",
                            exc.__class__.__name__,
                        )
                    else:
                        _pkg.logger.error(
                            "WebSocket error during history replay: %s",
                            exc.__class__.__name__,
                            exc_info=True,
                        )
                    return
            try:
                while True:
                    event: HydraFlowEvent = await queue.get()
                    await ws.send_text(event.model_dump_json())
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                if _is_likely_disconnect(exc):
                    _pkg.logger.warning(
                        "WebSocket disconnect during live streaming: %s",
                        exc.__class__.__name__,
                    )
                else:
                    _pkg.logger.error(
                        "WebSocket error during live streaming: %s",
                        exc.__class__.__name__,
                        exc_info=True,
                    )


def register_spa_catchall(router: APIRouter, ctx: RouterContext) -> None:
    """Register the SPA catch-all route on *router*.

    This **must** be called last, after all other routes have been registered,
    because the ``{path:path}`` pattern matches everything.
    """

    @router.get("/{path:path}", response_model=None)
    async def spa_catchall(path: str) -> Response:
        """Catch-all route: serve static assets or fall back to the SPA index."""
        if path.startswith(("api/", "ws/", "assets/", "static/")) or path == "ws":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        path_parts = PurePosixPath(path).parts
        if len(path_parts) == 1 and path_parts[0] not in {"", ".", ".."}:
            static_file = (ctx.ui_dist_dir / path_parts[0]).resolve()
            if (
                static_file.is_relative_to(ctx.ui_dist_dir.resolve())
                and static_file.is_file()
            ):
                return FileResponse(static_file)
        return ctx.serve_spa_index()
