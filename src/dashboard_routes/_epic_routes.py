"""Epic route handlers extracted from _routes.py."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext
from route_types import RepoSlugParam


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register epic-related routes on *router*."""

    @router.get("/api/epics")
    async def get_epics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return all tracked epics with enriched sub-issue progress."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse([])
        details = await orch._svc.epic_manager.get_all_detail()
        return JSONResponse([d.model_dump() for d in details])

    @router.get("/api/epics/{epic_number}")
    async def get_epic_detail(
        epic_number: int,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return full detail for a single epic including child issue info."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        detail = await orch._svc.epic_manager.get_detail(epic_number)
        if detail is None:
            return JSONResponse({"error": "epic not found"}, status_code=404)
        return JSONResponse(detail.model_dump())

    @router.post("/api/epics/{epic_number}/release")
    async def trigger_epic_release(
        epic_number: int,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Trigger async merge sequence and release creation for an epic.

        Returns a job_id. Completion is signalled via the EPIC_RELEASED WebSocket
        event — there is no REST polling endpoint for job status.
        """
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        result = await orch._svc.epic_manager.trigger_release(epic_number)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)
