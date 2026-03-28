"""Crate (milestone) route handlers extracted from _routes.py."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext
from models import CrateCreateRequest, CrateItemsRequest, CrateUpdateRequest

logger = logging.getLogger("hydraflow.dashboard")


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register crate-related routes on *router*."""

    @router.get("/api/crates")
    async def get_crates() -> JSONResponse:
        """List all milestones as crates with enriched progress data."""
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
        """Create a new milestone (crate)."""
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
        """Update a milestone (crate).

        Only fields present in the request JSON are forwarded.  Sending
        ``"due_on": null`` clears the milestone due date.
        """
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
        """Delete a milestone (crate)."""
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
        """Assign issues to a milestone (crate)."""
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
        """Remove issues from a milestone (crate) by clearing their milestone.

        Only clears the milestone if the issue is currently assigned to the
        specified crate (milestone), avoiding unintended removal from a
        different milestone.
        """
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
            logger.error("Failed to remove items from crate #%d: %s", crate_number, exc)
            return JSONResponse(
                {"error": "Failed to remove items from crate"}, status_code=500
            )

    @router.get("/api/crates/active")
    async def get_active_crate() -> JSONResponse:
        """Return the active crate number, title, and progress."""
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
        """Set the active crate. Body: ``{"crate_number": N}`` or ``{"crate_number": null}``."""
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
            # Fallback: update state directly when orchestrator isn't running
            ctx.state.set_active_crate_number(crate_number)
            return JSONResponse({"status": "ok", "crate_number": crate_number})
        if crate_number is not None:
            await orch.crate_manager.activate_crate(crate_number)
        else:
            ctx.state.set_active_crate_number(None)
        return JSONResponse({"status": "ok", "crate_number": crate_number})

    @router.post("/api/crates/advance")
    async def advance_crate() -> JSONResponse:
        """Advance past the current active crate to the next open one.

        Calls ``check_and_advance()`` which completes the active crate
        and activates the next milestone with open issues.  If the
        current crate still has open issues, it is force-cleared first
        so the pipeline moves forward regardless.
        """
        orch = ctx.get_orchestrator()
        cm = orch.crate_manager if orch is not None else None
        if cm is None:
            ctx.state.set_active_crate_number(None)
            return JSONResponse({"status": "ok", "previous": None, "next": None})
        previous = cm.active_crate_number
        # Force-clear first so check_and_advance will see no active
        # crate (if it still has open issues, check_and_advance would
        # be a no-op otherwise).
        ctx.state.set_active_crate_number(None)
        # Now find the next open crate
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
