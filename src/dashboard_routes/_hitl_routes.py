"""HITL route handlers extracted from _routes.py."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._routes import RouteContext
from events import EventType, HydraFlowEvent
from github_cache import GitHubDataCache
from models import (
    HITLCloseRequest,
    HITLSkipRequest,
    HITLUpdatePayload,
    IssueOutcomeType,
)
from route_types import RepoSlugParam

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator

logger = logging.getLogger("hydraflow.dashboard")


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register HITL-related routes on *router*."""

    def _clear_hitl_state(
        orch: HydraFlowOrchestrator | None,
        issue_number: int,
    ) -> None:
        """Clear all HITL tracking state for an issue."""
        if orch:
            orch.skip_hitl_issue(issue_number)
        ctx.state.clear_hitl_state(issue_number)

    async def _resolve_hitl_item(
        issue_number: int,
        orch: HydraFlowOrchestrator,
        *,
        action: str,
        comment_heading: str,
        comment_body: str,
        outcome_type: IssueOutcomeType,
        reason: str,
    ) -> JSONResponse:
        """Clear HITL state, record outcome, post comment, and publish event."""
        _clear_hitl_state(orch, issue_number)
        ctx.state.record_outcome(
            issue_number,
            outcome_type,
            reason=reason,
            phase="hitl",
        )

        try:
            await ctx.pr_manager.post_comment(
                issue_number,
                f"**{comment_heading}** — {comment_body}\n\n---\n*HydraFlow Dashboard*",
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post %s comment for issue #%d",
                action,
                issue_number,
                exc_info=True,
            )

        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number,
                    status="resolved",
                    action=action,
                    reason=reason,
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    @router.get("/api/hitl")
    async def get_hitl(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Fetch issues/PRs labeled for human-in-the-loop (stuck on CI)."""
        if not ctx.is_repo_pipeline_active(repo):
            return JSONResponse([])
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        # Use cached data when available
        if orch and isinstance(getattr(orch, "github_cache", None), GitHubDataCache):
            items = orch.github_cache.get_hitl_items()
        else:
            hitl_labels = list(
                dict.fromkeys([*_cfg.hitl_label, *_cfg.hitl_active_label])
            )
            manager = ctx.pr_manager_for(_cfg, _bus)
            items = await manager.list_hitl_items(hitl_labels)
        enriched = []
        for item in items:
            data = (
                dict(item) if isinstance(item, dict) else item.model_dump(by_alias=True)
            )
            issue_num: int = int(
                data.get("issue", 0) if isinstance(item, dict) else item.issue
            )
            if orch:
                data["status"] = orch.get_hitl_status(issue_num)
            cause = _state.get_hitl_cause(issue_num)
            origin = _state.get_hitl_origin(issue_num)
            if not cause and origin:
                if origin in _cfg.review_label:
                    cause = "Review escalation"
                elif origin in _cfg.find_label:
                    cause = "Triage escalation"
                else:
                    cause = "Escalation (reason not recorded)"
            if cause:
                data["cause"] = cause
            # Flag items held for issue type review
            if cause and (
                "epic detected" in cause.lower()
                or "bug report detected" in cause.lower()
            ):
                data["issueTypeReview"] = True
            cached_summary = ctx.state.get_hitl_summary(issue_num)
            data["llmSummary"] = cached_summary or ""
            data["llmSummaryUpdatedAt"] = ctx.state.get_hitl_summary_updated_at(
                issue_num
            )
            visual_ev = ctx.state.get_hitl_visual_evidence(issue_num)
            if visual_ev:
                data["visualEvidence"] = visual_ev.model_dump()
            if (
                not cached_summary
                and ctx.config.transcript_summarization_enabled
                and not ctx.config.dry_run
                and bool(ctx.config.gh_token)
                and ctx.hitl_summary_retry_due(issue_num)
            ):
                asyncio.create_task(
                    ctx.warm_hitl_summary(issue_num, cause=cause or "", origin=origin)
                )
            enriched.append(data)

        return JSONResponse(enriched)

    @router.get("/api/hitl/{issue_number}/summary")
    async def get_hitl_summary(issue_number: int) -> JSONResponse:
        """Return cached HITL summary, generating one if missing."""
        cached = ctx.state.get_hitl_summary(issue_number)
        if cached:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": cached,
                    "updated_at": ctx.state.get_hitl_summary_updated_at(issue_number),
                    "cached": True,
                }
            )

        cause = ctx.state.get_hitl_cause(issue_number) or ""
        origin = ctx.state.get_hitl_origin(issue_number)
        summary = await ctx.compute_hitl_summary(
            issue_number, cause=cause, origin=origin
        )
        if summary:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": summary,
                    "updated_at": ctx.state.get_hitl_summary_updated_at(issue_number),
                    "cached": False,
                }
            )
        return JSONResponse(
            {
                "issue": issue_number,
                "summary": "",
                "updated_at": None,
                "cached": False,
            }
        )

    @router.post("/api/hitl/{issue_number}/correct")
    async def hitl_correct(issue_number: int, body: dict[str, Any]) -> JSONResponse:
        """Submit a correction for a HITL issue to guide retry."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        correction = body.get("correction") or ""
        if not correction.strip():
            return JSONResponse(
                {"status": "error", "detail": "Correction text must not be empty"},
                status_code=400,
            )
        orch.submit_hitl_correction(issue_number, correction)

        # Swap labels for immediate dashboard feedback
        await ctx.pr_manager.swap_pipeline_labels(
            issue_number, ctx.config.hitl_active_label[0]
        )

        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number,
                    status="processing",
                    action="correct",
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/skip")
    async def hitl_skip(issue_number: int, body: HITLSkipRequest) -> JSONResponse:
        """Remove a HITL issue from the queue without action (reason required)."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        # Read origin before clearing state
        ctx.state.get_hitl_origin(issue_number)

        await ctx.pr_manager.close_issue(issue_number)

        return await _resolve_hitl_item(
            issue_number,
            orch,
            action="skip",
            comment_heading="HITL Skip",
            comment_body=f"Operator skipped this issue.\n\n**Reason:** {body.reason}",
            outcome_type=IssueOutcomeType.HITL_SKIPPED,
            reason=body.reason,
        )

    @router.post("/api/hitl/{issue_number}/close")
    async def hitl_close(issue_number: int, body: HITLCloseRequest) -> JSONResponse:
        """Close a HITL issue on GitHub (reason required)."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        await ctx.pr_manager.close_issue(issue_number)

        return await _resolve_hitl_item(
            issue_number,
            orch,
            action="close",
            comment_heading="HITL Close",
            comment_body=f"Operator closed this issue.\n\n**Reason:** {body.reason}",
            outcome_type=IssueOutcomeType.HITL_CLOSED,
            reason=body.reason,
        )

    @router.post("/api/hitl/{issue_number}/approve-process")
    async def hitl_approve_process(issue_number: int) -> JSONResponse:
        """Approve a HITL item held for issue type review.

        All issue types (bugs, epics, etc.) route to triage first.
        """
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        target_label = ctx.config.find_label[0]
        target_stage = "triage"

        await ctx.pr_manager.swap_pipeline_labels(issue_number, target_label)

        return await _resolve_hitl_item(
            issue_number,
            orch,
            action="approved_for_processing",
            comment_heading="Approved for processing",
            comment_body=(
                f"Operator approved this issue.\n\n"
                f"Routing to **{target_stage}** (`{target_label}`)."
            ),
            outcome_type=IssueOutcomeType.HITL_APPROVED,
            reason=f"Operator approved issue type for processing ({target_stage})",
        )

    @router.get("/api/human-input")
    async def get_human_input_requests(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return pending human-input prompts from the orchestrator."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            return JSONResponse(orch.human_input_requests)
        return JSONResponse({})

    @router.post("/api/human-input/{issue_number}")
    async def provide_human_input(
        issue_number: int,
        body: dict[str, Any],
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Submit an operator answer to a pending human-input request."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            answer = body.get("answer", "")
            orch.provide_human_input(issue_number, answer)
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "no orchestrator"}, status_code=400)
