"""HITL (Human-in-the-Loop) route handlers for the HydraFlow dashboard."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._context import RepoSlugParam
from events import EventType, HydraFlowEvent
from models import (
    HITLCloseRequest,
    HITLSkipRequest,
    HITLUpdatePayload,
    IssueOutcomeType,
)

if TYPE_CHECKING:
    from dashboard_routes._context import RouterContext

logger = logging.getLogger("hydraflow.dashboard")


def register_hitl_routes(router: APIRouter, ctx: RouterContext) -> None:
    """Register HITL-related routes on *router*."""

    @router.get("/api/hitl")
    async def get_hitl(repo: RepoSlugParam = None) -> JSONResponse:
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        hitl_labels = list(dict.fromkeys([*_cfg.hitl_label, *_cfg.hitl_active_label]))
        manager = ctx.pr_manager_for(_cfg, _bus)
        items = await manager.list_hitl_items(hitl_labels)
        orch = _get_orch()
        enriched: list[dict[str, Any]] = []
        for item in items:
            data = item.model_dump()
            if orch:
                data["status"] = orch.get_hitl_status(item.issue)
            cause = _state.get_hitl_cause(item.issue)
            origin = _state.get_hitl_origin(item.issue)
            if not cause and origin:
                if origin in _cfg.improve_label:
                    cause = "Self-improvement proposal"
                elif origin in _cfg.review_label:
                    cause = "Review escalation"
                elif origin in _cfg.find_label:
                    cause = "Triage escalation"
                else:
                    cause = "Escalation (reason not recorded)"
            if cause:
                data["cause"] = cause
            if origin and origin in _cfg.improve_label:
                data["isMemorySuggestion"] = True
            if cause and (
                "epic detected" in cause.lower()
                or "bug report detected" in cause.lower()
            ):
                data["issueTypeReview"] = True
            # HITL summary uses the default (closure) config/state, not resolved ones.
            cached_summary = ctx.state.get_hitl_summary(item.issue)
            data["llmSummary"] = cached_summary or ""
            data["llmSummaryUpdatedAt"] = ctx.state.get_hitl_summary_updated_at(
                item.issue
            )
            visual_ev = ctx.state.get_hitl_visual_evidence(item.issue)
            if visual_ev:
                data["visualEvidence"] = visual_ev.model_dump()
            if (
                not cached_summary
                and ctx.config.transcript_summarization_enabled
                and not ctx.config.dry_run
                and bool(ctx.config.gh_token)
                and ctx.hitl_summary_retry_due(item.issue)
            ):
                asyncio.create_task(
                    ctx.warm_hitl_summary(item.issue, cause=cause or "", origin=origin)
                )
            enriched.append(data)
        return JSONResponse(enriched)

    @router.get("/api/hitl/{issue_number}/summary")
    async def get_hitl_summary(issue_number: int) -> JSONResponse:
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
            {"issue": issue_number, "summary": "", "updated_at": None, "cached": False}
        )

    @router.post("/api/hitl/{issue_number}/correct")
    async def hitl_correct(issue_number: int, body: dict[str, Any]) -> JSONResponse:
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
        await ctx.pr_manager.swap_pipeline_labels(
            issue_number, ctx.config.hitl_active_label[0]
        )
        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number, status="processing", action="correct"
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/skip")
    async def hitl_skip(issue_number: int, body: HITLSkipRequest) -> JSONResponse:
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        origin = ctx.state.get_hitl_origin(issue_number)
        if origin and origin in ctx.config.improve_label and ctx.config.find_label:
            await ctx.pr_manager.swap_pipeline_labels(
                issue_number, ctx.config.find_label[0]
            )
        else:
            for lbl in ctx.config.all_pipeline_labels:
                await ctx.pr_manager.remove_label(issue_number, lbl)
        return await ctx.resolve_hitl_item(
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
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        await ctx.pr_manager.close_issue(issue_number)
        return await ctx.resolve_hitl_item(
            issue_number,
            orch,
            action="close",
            comment_heading="HITL Close",
            comment_body=f"Operator closed this issue.\n\n**Reason:** {body.reason}",
            outcome_type=IssueOutcomeType.HITL_CLOSED,
            reason=body.reason,
        )

    @router.post("/api/hitl/{issue_number}/approve-memory")
    async def hitl_approve_memory(issue_number: int) -> JSONResponse:
        for lbl in ctx.config.all_pipeline_labels:
            await ctx.pr_manager.remove_label(issue_number, lbl)
        await ctx.pr_manager.add_labels(issue_number, ctx.config.memory_label)
        ctx.clear_hitl_state(ctx.get_orchestrator(), issue_number)
        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data=HITLUpdatePayload(
                    issue=issue_number,
                    status="resolved",
                    action="approved_as_memory",
                ),
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/approve-process")
    async def hitl_approve_process(issue_number: int) -> JSONResponse:
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        target_label = ctx.config.find_label[0]
        target_stage = "triage"
        await ctx.pr_manager.swap_pipeline_labels(issue_number, target_label)
        return await ctx.resolve_hitl_item(
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
        issue_number: int, body: dict[str, Any], repo: RepoSlugParam = None
    ) -> JSONResponse:
        """Submit an operator answer to a pending human-input request."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch:
            answer = body.get("answer", "")
            orch.provide_human_input(issue_number, answer)
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "no orchestrator"}, status_code=400)
