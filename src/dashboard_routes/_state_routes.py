"""State, pipeline, events, queue, stats, PRs, epics, crates, and request-changes route handlers."""

from __future__ import annotations

import logging
from datetime import UTC
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._context import RepoSlugParam
from dashboard_routes._helpers import _FRONTEND_STAGE_TO_LABEL_FIELD, _STAGE_NAME_MAP
from events import EventType, HydraFlowEvent
from models import (
    CrateCreateRequest,
    CrateItemsRequest,
    CrateUpdateRequest,
    HITLEscalationPayload,
    PipelineIssue,
    PipelineSnapshot,
    PipelineSnapshotEntry,
    QueueStats,
)

if TYPE_CHECKING:
    from dashboard_routes._context import RouterContext

logger = logging.getLogger("hydraflow.dashboard")


def register_state_routes(router: APIRouter, ctx: RouterContext) -> None:
    """Register state, pipeline, events, queue, stats, PRs, epics, and crate routes on *router*."""

    @router.get("/api/state")
    async def get_state(repo: RepoSlugParam = None) -> JSONResponse:
        """Return the full state tracker snapshot as JSON."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        return JSONResponse(_state.to_dict())

    @router.get("/api/stats")
    async def get_stats(repo: RepoSlugParam = None) -> JSONResponse:
        """Return lifetime stats and optional queue depths."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        data: dict[str, Any] = _state.get_lifetime_stats().model_dump()
        orch = _get_orch()
        if orch:
            data["queue"] = orch.issue_store.get_queue_stats().model_dump()
        return JSONResponse(data)

    @router.get("/api/queue")
    async def get_queue(repo: RepoSlugParam = None) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            return JSONResponse(orch.issue_store.get_queue_stats().model_dump())
        return JSONResponse(QueueStats().model_dump())

    @router.post("/api/request-changes")
    async def request_changes(body: dict[str, Any]) -> JSONResponse:
        issue_number: int | None = body.get("issue_number")
        feedback = (body.get("feedback") or "").strip()
        stage: str = body.get("stage") or ""
        if not isinstance(issue_number, int) or issue_number < 1 or not feedback:
            return JSONResponse(
                {"status": "error", "detail": "issue_number and feedback are required"},
                status_code=400,
            )
        label_field = _FRONTEND_STAGE_TO_LABEL_FIELD.get(stage)
        if not label_field:
            return JSONResponse(
                {"status": "error", "detail": f"Unknown stage: {stage}"},
                status_code=400,
            )
        stage_labels: list[str] = getattr(ctx.config, label_field, [])
        origin_label: str = stage_labels[0]
        await ctx.pr_manager.swap_pipeline_labels(
            issue_number, ctx.config.hitl_label[0]
        )
        ctx.state.set_hitl_cause(issue_number, feedback)
        ctx.state.set_hitl_origin(issue_number, origin_label)
        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_ESCALATION,
                data=HITLEscalationPayload(
                    issue=issue_number, cause=feedback, origin=origin_label
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    @router.get("/api/pipeline")
    async def get_pipeline(repo: RepoSlugParam = None) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            raw = orch.issue_store.get_pipeline_snapshot()
            mapped: dict[str, list[PipelineSnapshotEntry]] = {}
            for backend_stage, issues in raw.items():
                frontend_stage = _STAGE_NAME_MAP.get(backend_stage, backend_stage)
                mapped[frontend_stage] = issues
            snapshot = PipelineSnapshot(
                stages={
                    k: [PipelineIssue.model_validate(i) for i in v]
                    for k, v in mapped.items()
                }
            )
            return JSONResponse(snapshot.model_dump())
        return JSONResponse(PipelineSnapshot().model_dump())

    @router.get("/api/pipeline/stats")
    async def get_pipeline_stats(repo: RepoSlugParam = None) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            stats = orch.build_pipeline_stats()
            return JSONResponse(stats.model_dump())
        return JSONResponse({})

    @router.get("/api/events")
    async def get_events(since: str | None = None) -> JSONResponse:
        """Return event history, optionally filtered by a since timestamp."""
        if since is not None:
            from datetime import datetime

            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=UTC)
                events = await ctx.event_bus.load_events_since(since_dt)
                if events is not None:
                    return JSONResponse([e.model_dump() for e in events])
            except (ValueError, TypeError):
                pass
        history = ctx.event_bus.get_history()
        return JSONResponse([e.model_dump() for e in history])

    @router.get("/api/prs")
    async def get_prs(repo: RepoSlugParam = None) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        manager = ctx.pr_manager_for(_cfg, _bus)
        all_labels = list(
            {
                *_cfg.ready_label,
                *_cfg.review_label,
                *_cfg.fixed_label,
                *_cfg.hitl_label,
                *_cfg.hitl_active_label,
                *_cfg.planner_label,
                *_cfg.improve_label,
            }
        )
        items = await manager.list_open_prs(all_labels)
        return JSONResponse([item.model_dump() for item in items])

    @router.get("/api/epics")
    async def get_epics(repo: RepoSlugParam = None) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse([])
        details = await orch._svc.epic_manager.get_all_detail()
        return JSONResponse([d.model_dump() for d in details])

    @router.get("/api/epics/{epic_number}")
    async def get_epic_detail(
        epic_number: int, repo: RepoSlugParam = None
    ) -> JSONResponse:
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
        epic_number: int, repo: RepoSlugParam = None
    ) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            return JSONResponse({"error": "orchestrator not running"}, status_code=503)
        result = await orch._svc.epic_manager.trigger_release(epic_number)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return JSONResponse(result)

    # ------------------------------------------------------------------
    # Crate routes
    # ------------------------------------------------------------------

    @router.get("/api/crates")
    async def get_crates() -> JSONResponse:
        try:
            crates = await ctx.pr_manager.list_milestones()
            result = []
            for crate in crates:
                data = crate.model_dump()
                data["total_issues"] = crate.open_issues + crate.closed_issues
                data["progress"] = (
                    round(
                        crate.closed_issues
                        / (crate.open_issues + crate.closed_issues)
                        * 100
                    )
                    if (crate.open_issues + crate.closed_issues) > 0
                    else 0
                )
                result.append(data)
            return JSONResponse(result)
        except RuntimeError as exc:
            logger.error("Failed to fetch crates: %s", exc)
            return JSONResponse({"error": "Failed to fetch crates"}, status_code=500)

    @router.post("/api/crates")
    async def create_crate(body: CrateCreateRequest) -> JSONResponse:
        if not body.title.strip():
            return JSONResponse({"error": "title is required"}, status_code=400)
        try:
            crate = await ctx.pr_manager.create_milestone(
                title=body.title.strip(),
                description=body.description,
                due_on=body.due_on,
            )
            return JSONResponse(crate.model_dump())
        except RuntimeError as exc:
            logger.error("Failed to create crate: %s", exc)
            return JSONResponse({"error": "Failed to create crate"}, status_code=500)

    @router.patch("/api/crates/{crate_number}")
    async def update_crate(crate_number: int, body: CrateUpdateRequest) -> JSONResponse:
        fields = {k: body.model_dump()[k] for k in body.model_fields_set}
        if not fields:
            return JSONResponse({"error": "no fields to update"}, status_code=400)
        try:
            crate = await ctx.pr_manager.update_milestone(crate_number, **fields)
            return JSONResponse(crate.model_dump())
        except RuntimeError as exc:
            logger.error("Failed to update crate #%d: %s", crate_number, exc)
            return JSONResponse({"error": "Failed to update crate"}, status_code=500)

    @router.delete("/api/crates/{crate_number}")
    async def delete_crate(crate_number: int) -> JSONResponse:
        try:
            await ctx.pr_manager.delete_milestone(crate_number)
            return JSONResponse({"ok": True})
        except RuntimeError as exc:
            logger.error("Failed to delete crate #%d: %s", crate_number, exc)
            return JSONResponse({"error": "Failed to delete crate"}, status_code=500)

    @router.post("/api/crates/{crate_number}/items")
    async def add_crate_items(
        crate_number: int, body: CrateItemsRequest
    ) -> JSONResponse:
        try:
            for issue_number in body.issue_numbers:
                await ctx.pr_manager.set_issue_milestone(issue_number, crate_number)
            return JSONResponse({"ok": True, "added": len(body.issue_numbers)})
        except RuntimeError as exc:
            logger.error("Failed to add items to crate #%d: %s", crate_number, exc)
            return JSONResponse(
                {"error": "Failed to add items to crate"}, status_code=500
            )

    @router.delete("/api/crates/{crate_number}/items")
    async def remove_crate_items(
        crate_number: int, body: CrateItemsRequest
    ) -> JSONResponse:
        try:
            current_issues = await ctx.pr_manager.list_milestone_issues(crate_number)
            current_nums = {i.get("number") for i in current_issues}
            removed = 0
            for issue_number in body.issue_numbers:
                if issue_number in current_nums:
                    await ctx.pr_manager.set_issue_milestone(issue_number, None)
                    removed += 1
            return JSONResponse({"ok": True, "removed": removed})
        except RuntimeError as exc:
            logger.error(
                "Failed to remove items from crate #%d: %s",
                crate_number,
                exc,
            )
            return JSONResponse(
                {"error": "Failed to remove items from crate"},
                status_code=500,
            )

    @router.get("/api/crates/active")
    async def get_active_crate() -> JSONResponse:
        orch = ctx.get_orchestrator()
        active_number = ctx.state.get_active_crate_number()
        result: dict[str, Any] = {
            "crate_number": active_number,
            "title": None,
            "progress": 0,
            "open_issues": 0,
            "closed_issues": 0,
            "total_issues": 0,
        }
        if active_number is not None and orch is not None:
            try:
                crates = await ctx.pr_manager.list_milestones(state="all")
                active = next((c for c in crates if c.number == active_number), None)
                if active:
                    total = active.open_issues + active.closed_issues
                    result["title"] = active.title
                    result["open_issues"] = active.open_issues
                    result["closed_issues"] = active.closed_issues
                    result["total_issues"] = total
                    result["progress"] = (
                        round(active.closed_issues / total * 100) if total > 0 else 0
                    )
            except Exception:
                logger.warning("Failed to enrich active crate details", exc_info=True)
        return JSONResponse(result)

    @router.post("/api/crates/active")
    async def set_active_crate(body: dict[str, Any]) -> JSONResponse:
        crate_number = body.get("crate_number")
        if crate_number is not None and not isinstance(crate_number, int):
            return JSONResponse(
                {
                    "status": "error",
                    "detail": "crate_number must be an integer or null",
                },
                status_code=400,
            )
        orch = ctx.get_orchestrator()
        if orch is None:
            ctx.state.set_active_crate_number(crate_number)
            return JSONResponse({"status": "ok", "crate_number": crate_number})
        if crate_number is not None:
            await orch.crate_manager.activate_crate(crate_number)
        else:
            ctx.state.set_active_crate_number(None)
        return JSONResponse({"status": "ok", "crate_number": crate_number})

    @router.post("/api/crates/advance")
    async def advance_crate() -> JSONResponse:
        orch = ctx.get_orchestrator()
        cm = orch.crate_manager if orch is not None else None
        if cm is None:
            ctx.state.set_active_crate_number(None)
            return JSONResponse({"status": "ok", "previous": None, "next": None})
        previous = cm.active_crate_number
        ctx.state.set_active_crate_number(None)
        try:
            crates = await ctx.pr_manager.list_milestones(state="open")
            candidates = sorted(
                (c for c in crates if c.open_issues > 0 and c.number != previous),
                key=lambda c: c.number,
            )
            if candidates:
                await cm.activate_crate(candidates[0].number)
                return JSONResponse(
                    {
                        "status": "ok",
                        "previous": previous,
                        "next": candidates[0].number,
                    }
                )
        except Exception:
            logger.warning("Failed to find next crate during advance", exc_info=True)
        return JSONResponse({"status": "ok", "previous": previous, "next": None})
