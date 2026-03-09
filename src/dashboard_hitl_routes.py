"""HITL (Human-in-the-Loop) route handlers for the dashboard API."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_router_deps import RouterDeps
from events import EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from models import (
    GitHubIssue,
    HITLCloseRequest,
    HITLSkipRequest,
    HITLUpdatePayload,
    IssueOutcomeType,
)
from transcript_summarizer import TranscriptSummarizer

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator

logger = logging.getLogger("hydraflow.dashboard")


def _parse_iso_or_none(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to a datetime, or return None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _build_hitl_context(issue: GitHubIssue, *, cause: str, origin: str | None) -> str:
    """Build a text context block for HITL summary generation."""
    body = issue.body.strip()
    comments = issue.comments
    recent_comments = [str(c).strip() for c in comments[-5:] if str(c).strip()]
    comments_block = "\n".join(f"- {c[:400]}" for c in recent_comments)
    origin_text = origin or "unknown"
    return (
        f"Issue #{issue.number}: {issue.title}\n"
        f"Escalation cause: {cause or 'not recorded'}\n"
        f"Escalation origin: {origin_text}\n\n"
        f"Issue body:\n{body[:6000]}\n\n"
        f"Recent comments:\n{comments_block[:3000]}"
    )


def _normalise_summary_lines(raw: str) -> str:
    """Strip bullet prefixes and cap a summary to 8 lines."""
    lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip()]
    return "\n".join(lines[:8]).strip()


def create_hitl_router(deps: RouterDeps) -> APIRouter:
    """Create an APIRouter with all HITL endpoints."""
    router = APIRouter()

    issue_fetcher = IssueFetcher(deps.config)
    hitl_summarizer = TranscriptSummarizer(
        deps.config, deps.pr_manager, deps.event_bus, deps.state
    )

    # ------------------------------------------------------------------
    # HITL summary helpers
    # ------------------------------------------------------------------

    def _hitl_summary_retry_due(issue_number: int) -> bool:
        """Return True if enough time has passed to retry a failed HITL summary."""
        failed_at, _ = deps.state.get_hitl_summary_failure(issue_number)
        failed_dt = _parse_iso_or_none(failed_at)
        if failed_dt is None:
            return True
        age = (datetime.now(UTC) - failed_dt).total_seconds()
        return age >= deps.hitl_summary_cooldown_seconds

    async def _compute_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> str | None:
        """Fetch issue, generate and normalise a HITL summary, then persist to state."""
        if (
            not deps.config.transcript_summarization_enabled
            or deps.config.dry_run
            or not deps.config.gh_token
        ):
            return None
        issue = await issue_fetcher.fetch_issue_by_number(issue_number)
        if issue is None:
            deps.state.set_hitl_summary_failure(issue_number, "Issue fetch failed")
            return None
        context = _build_hitl_context(issue, cause=cause, origin=origin)
        generated = await hitl_summarizer.summarize_hitl_context(context)
        if not generated:
            deps.state.set_hitl_summary_failure(
                issue_number, "Summary model returned empty"
            )
            return None
        summary = _normalise_summary_lines(generated)
        if not summary:
            deps.state.set_hitl_summary_failure(
                issue_number, "Summary normalization produced empty output"
            )
            return None
        deps.state.set_hitl_summary(issue_number, summary)
        deps.state.clear_hitl_summary_failure(issue_number)
        return summary

    async def _warm_hitl_summary(
        issue_number: int, *, cause: str, origin: str | None
    ) -> None:
        """Schedule background HITL summary generation, guarded by inflight tracking."""
        if issue_number in deps.hitl_summary_inflight:
            return
        deps.hitl_summary_inflight.add(issue_number)
        try:
            async with deps.hitl_summary_slots:
                await _compute_hitl_summary(issue_number, cause=cause, origin=origin)
        except Exception as exc:
            deps.state.set_hitl_summary_failure(
                issue_number,
                f"{type(exc).__name__}: {exc}",
            )
            logger.exception(
                "Failed to warm HITL summary for issue #%d",
                issue_number,
            )
        finally:
            deps.hitl_summary_inflight.discard(issue_number)

    # ------------------------------------------------------------------
    # HITL state helpers
    # ------------------------------------------------------------------

    def _clear_hitl_state(
        orch: HydraFlowOrchestrator | None,
        issue_number: int,
    ) -> None:
        """Clear all HITL tracking state for an issue."""
        if orch:
            orch.skip_hitl_issue(issue_number)
        deps.state.remove_hitl_origin(issue_number)
        deps.state.remove_hitl_cause(issue_number)
        deps.state.remove_hitl_summary(issue_number)

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
        deps.state.record_outcome(
            issue_number,
            outcome_type,
            reason=reason,
            phase="hitl",
        )

        try:
            await deps.pr_manager.post_comment(
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

        await deps.event_bus.publish(
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

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    @router.get("/api/hitl")
    async def get_hitl(
        repo: str | None = None,
    ) -> JSONResponse:
        """Fetch issues/PRs labeled for human-in-the-loop (stuck on CI)."""
        _cfg, _state, _bus, _get_orch = deps.resolve_runtime(repo)
        hitl_labels = list(dict.fromkeys([*_cfg.hitl_label, *_cfg.hitl_active_label]))
        manager = deps.pr_manager_for(_cfg, _bus)
        items = await manager.list_hitl_items(hitl_labels)
        orch = _get_orch()
        enriched = []
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
            # Flag items held for issue type review
            if cause and (
                "epic detected" in cause.lower()
                or "bug report detected" in cause.lower()
            ):
                data["issueTypeReview"] = True
            cached_summary = deps.state.get_hitl_summary(item.issue)
            data["llmSummary"] = cached_summary or ""
            data["llmSummaryUpdatedAt"] = deps.state.get_hitl_summary_updated_at(
                item.issue
            )
            visual_ev = deps.state.get_hitl_visual_evidence(item.issue)
            if visual_ev:
                data["visualEvidence"] = visual_ev.model_dump()
            if (
                not cached_summary
                and deps.config.transcript_summarization_enabled
                and not deps.config.dry_run
                and bool(deps.config.gh_token)
                and _hitl_summary_retry_due(item.issue)
            ):
                asyncio.create_task(
                    _warm_hitl_summary(item.issue, cause=cause or "", origin=origin)
                )
            enriched.append(data)

        # When memory auto-approve is on, filter out memory suggestions that
        # were queued before the setting was enabled.
        if deps.config.memory_auto_approve:
            enriched = [d for d in enriched if not d.get("isMemorySuggestion")]

        return JSONResponse(enriched)

    @router.get("/api/hitl/{issue_number}/summary")
    async def get_hitl_summary(issue_number: int) -> JSONResponse:
        """Return cached HITL summary, generating one if missing."""
        cached = deps.state.get_hitl_summary(issue_number)
        if cached:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": cached,
                    "updated_at": deps.state.get_hitl_summary_updated_at(issue_number),
                    "cached": True,
                }
            )

        cause = deps.state.get_hitl_cause(issue_number) or ""
        origin = deps.state.get_hitl_origin(issue_number)
        summary = await _compute_hitl_summary(issue_number, cause=cause, origin=origin)
        if summary:
            return JSONResponse(
                {
                    "issue": issue_number,
                    "summary": summary,
                    "updated_at": deps.state.get_hitl_summary_updated_at(issue_number),
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
        orch = deps.get_orchestrator()
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
        await deps.pr_manager.swap_pipeline_labels(
            issue_number, deps.config.hitl_active_label[0]
        )

        await deps.event_bus.publish(
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
        orch = deps.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        # Read origin before clearing state
        origin = deps.state.get_hitl_origin(issue_number)

        # If this was an improve issue, transition to triage for implementation
        if origin and origin in deps.config.improve_label and deps.config.find_label:
            await deps.pr_manager.swap_pipeline_labels(
                issue_number, deps.config.find_label[0]
            )
        else:
            # Just remove all pipeline labels
            for lbl in deps.config.all_pipeline_labels:
                await deps.pr_manager.remove_label(issue_number, lbl)

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
        orch = deps.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        await deps.pr_manager.close_issue(issue_number)

        return await _resolve_hitl_item(
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
        """Approve a HITL item as a memory suggestion, relabeling for sync."""
        # Remove all pipeline labels and add memory label
        for lbl in deps.config.all_pipeline_labels:
            await deps.pr_manager.remove_label(issue_number, lbl)
        await deps.pr_manager.add_labels(issue_number, deps.config.memory_label)
        _clear_hitl_state(deps.get_orchestrator(), issue_number)
        await deps.event_bus.publish(
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
        """Approve a HITL item held for issue type review.

        All issue types (bugs, epics, etc.) route to triage first.
        """
        orch = deps.get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        target_label = deps.config.find_label[0]
        target_stage = "triage"

        await deps.pr_manager.swap_pipeline_labels(issue_number, target_label)

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

    return router
