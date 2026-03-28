"""Report route handlers extracted from _routes.py."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext, _extract_issue_number
from models import (
    PendingReport,
    ReportHistoryEntry,
    ReportIssueRequest,
    ReportIssueResponse,
    TrackedReport,
    TrackedReportUpdate,
)

logger = logging.getLogger("hydraflow.dashboard")


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register report-related routes on *router*."""

    @router.post("/api/report")
    async def submit_report(request: ReportIssueRequest) -> JSONResponse:
        """Queue a bug report for async processing by the report issue worker."""
        report = PendingReport(
            description=request.description,
            screenshot_base64=request.screenshot_base64,
            environment=request.environment,
            reporter_id=request.reporter_id,
        )
        ctx.state.enqueue_report(report)

        # Create a tracked report for the reporter if a reporter_id is provided
        if request.reporter_id:
            tracked = TrackedReport(
                id=report.id,
                reporter_id=request.reporter_id,
                description=request.description,
                status="queued",
                history=[
                    ReportHistoryEntry(
                        action="submitted",
                        detail="Bug report submitted via dashboard",
                    )
                ],
            )
            ctx.state.add_tracked_report(tracked)

        # Trigger the report-issue worker immediately so the report
        # doesn't wait for the next polling interval.
        orch = ctx.get_orchestrator()
        if orch is not None:
            orch.trigger_bg_worker("report_issue")

        title = f"[Bug Report] {request.description[:100]}"
        response = ReportIssueResponse(
            issue_number=0, title=title, url="", status="queued"
        )
        return JSONResponse(response.model_dump())

    @router.get("/api/reports")
    async def list_tracked_reports(
        reporter_id: str = "", status: str | None = None
    ) -> JSONResponse:
        """List tracked reports for a given reporter, optionally filtered by status."""
        if not reporter_id:
            return JSONResponse([])
        reports = ctx.state.get_tracked_reports(reporter_id, status=status)
        return JSONResponse([r.model_dump() for r in reports])

    @router.patch("/api/reports/{report_id}")
    async def update_tracked_report(
        report_id: str, body: TrackedReportUpdate
    ) -> JSONResponse:
        """Update a tracked report (confirm fixed, reopen, cancel)."""
        report = ctx.state.get_tracked_report(report_id)
        if report is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        if (
            body.reporter_id
            and report.reporter_id
            and body.reporter_id != report.reporter_id
        ):
            return JSONResponse({"error": "Forbidden"}, status_code=403)
        # Validate state-machine transitions
        valid_actions: dict[str, list[str]] = {
            "confirm_fixed": ["fixed"],
            "reopen": ["filed", "fixed", "in-progress", "closed"],
            "cancel": ["queued", "in-progress", "filed", "fixed", "reopened"],
        }
        if report.status not in valid_actions.get(body.action, []):
            return JSONResponse(
                {
                    "error": f"Action '{body.action}' is not allowed in status '{report.status}'"
                },
                status_code=422,
            )
        action_map: dict[
            str,
            tuple[
                Literal[
                    "queued",
                    "in-progress",
                    "filed",
                    "fixed",
                    "closed",
                    "reopened",
                ],
                str,
            ],
        ] = {
            "confirm_fixed": ("closed", "Confirmed fixed by reporter"),
            "reopen": ("reopened", "Reopened by reporter"),
            "cancel": ("closed", "Cancelled by reporter"),
        }
        status, default_detail = action_map[body.action]
        updated = ctx.state.update_tracked_report(
            report_id,
            status=status,
            detail=body.detail or default_detail,
            action_label=body.action,
        )
        if updated is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        return JSONResponse(updated.model_dump())

    @router.get("/api/reports/{report_id}/history")
    async def get_report_history(report_id: str) -> JSONResponse:
        """Get the timeline/history for a tracked report."""
        report = ctx.state.get_tracked_report(report_id)
        if report is None:
            return JSONResponse({"error": "Report not found"}, status_code=404)
        return JSONResponse([entry.model_dump() for entry in report.history])

    @router.post("/api/reports/refresh")
    async def refresh_report_statuses(reporter_id: str = "") -> JSONResponse:
        """Refresh statuses for filed and stale-queued reports."""
        refreshed: list[dict[str, str]] = []

        # --- filed -> fixed when linked issue is closed as completed ---
        for report in ctx.state.get_filed_reports():
            if reporter_id and report.reporter_id != reporter_id:
                continue
            issue_number = _extract_issue_number(report.linked_issue_url)
            if issue_number <= 0:
                continue
            issue_state = await ctx.pr_manager.get_issue_state(issue_number)
            if issue_state == "COMPLETED":
                ctx.state.update_tracked_report(
                    report.id,
                    status="fixed",
                    action_label="fixed",
                    detail=f"Issue #{issue_number} resolved",
                )
                refreshed.append({"id": report.id, "new_status": "fixed"})
            elif issue_state == "NOT_PLANNED":
                ctx.state.update_tracked_report(
                    report.id,
                    status="closed",
                    action_label="closed",
                    detail=f"Issue #{issue_number} closed as won't fix",
                )
                refreshed.append({"id": report.id, "new_status": "closed"})

        # --- stale queued -> re-enqueue pending ---
        pending_ids = {p.id for p in ctx.state.get_pending_reports()}
        for report in ctx.state.get_stale_queued_reports(stale_minutes=30):
            if reporter_id and report.reporter_id != reporter_id:
                continue
            # Only re-enqueue if there's no pending entry already
            if report.id not in pending_ids:
                ctx.state.enqueue_report(
                    PendingReport(
                        id=report.id,
                        description=report.description,
                        reporter_id=report.reporter_id,
                    )
                )
                ctx.state.update_tracked_report(
                    report.id,
                    action_label="retry",
                    detail="Stale queued report re-enqueued for processing",
                )
                refreshed.append({"id": report.id, "new_status": "queued"})

        return JSONResponse({"refreshed": refreshed})
