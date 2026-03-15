"""Timeline, intent, report, and session route handlers for the HydraFlow dashboard."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._context import RepoSlugParam
from models import (
    IntentRequest,
    IntentResponse,
    PendingReport,
    ReportHistoryEntry,
    ReportIssueRequest,
    ReportIssueResponse,
    TrackedReport,
    TrackedReportUpdate,
)
from timeline import TimelineBuilder

if TYPE_CHECKING:
    from dashboard_routes._context import RouterContext

logger = logging.getLogger("hydraflow.dashboard")


def register_misc_routes(router: APIRouter, ctx: RouterContext) -> None:
    """Register timeline, intent, report, and session routes on *router*."""

    @router.get("/api/timeline")
    async def get_timeline() -> JSONResponse:
        """Return timelines for all tracked issues."""
        builder = TimelineBuilder(ctx.event_bus)
        timelines = builder.build_all()
        return JSONResponse([t.model_dump() for t in timelines])

    @router.get("/api/timeline/issue/{issue_number}")
    async def get_timeline_issue(issue_number: int) -> JSONResponse:
        """Return the event timeline for a single issue."""
        builder = TimelineBuilder(ctx.event_bus)
        timeline = builder.build_for_issue(issue_number)
        if timeline is None:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return JSONResponse(timeline.model_dump())

    @router.post("/api/intent")
    async def submit_intent(request: IntentRequest) -> JSONResponse:
        """Create a GitHub issue from a user intent typed in the dashboard."""
        title = request.text[:120]
        body = request.text
        labels = list(ctx.config.planner_label)

        issue_number = await ctx.pr_manager.create_issue(
            title=title, body=body, labels=labels
        )

        if issue_number == 0:
            return JSONResponse({"error": "Failed to create issue"}, status_code=500)

        url = f"https://github.com/{ctx.config.repo}/issues/{issue_number}"
        response = IntentResponse(issue_number=issue_number, title=title, url=url)
        return JSONResponse(response.model_dump())

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

        title = f"[Bug Report] {request.description[:100]}"
        response = ReportIssueResponse(
            issue_number=0, title=title, url="", status="queued"
        )
        return JSONResponse(response.model_dump())

    @router.get("/api/reports")
    async def list_tracked_reports(reporter_id: str = "") -> JSONResponse:
        """List tracked reports for a given reporter."""
        if not reporter_id:
            return JSONResponse([])
        reports = ctx.state.get_tracked_reports(reporter_id)
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
        valid_actions: dict[str, list[str]] = {
            "confirm_fixed": ["fixed"],
            "reopen": ["fixed", "in-progress", "closed"],
            "cancel": ["queued", "in-progress", "fixed", "reopened"],
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
            tuple[Literal["queued", "in-progress", "fixed", "closed", "reopened"], str],
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

    @router.get("/api/sessions")
    async def get_sessions(repo: RepoSlugParam = None) -> JSONResponse:
        """Return session logs for the selected repo."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        sessions = _state.load_sessions()
        repo_filter = (repo or "").strip()
        if repo_filter and ctx.registry is None:
            normalized = repo_filter.lower()
            sessions = [
                session
                for session in sessions
                if (session.repo or "").lower() == normalized
            ]
        return JSONResponse([s.model_dump() for s in sessions])

    @router.get("/api/sessions/{session_id}")
    async def get_session_detail(
        session_id: str,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return a single session by ID with associated events."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        session = _state.get_session(session_id)
        if session is None:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        all_events = _bus.get_history()
        session_events = [
            e.model_dump() for e in all_events if e.session_id == session_id
        ]
        data = session.model_dump()
        data["events"] = session_events
        return JSONResponse(data)

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Delete a session by ID. Returns 400 if active, 404 if not found."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        try:
            deleted = _state.delete_session(session_id)
        except ValueError as exc:
            logger.warning("Failed to delete session %s: %s", session_id, exc)
            return JSONResponse(
                {"error": "Cannot delete active session"}, status_code=400
            )
        if not deleted:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse({"status": "ok"})
