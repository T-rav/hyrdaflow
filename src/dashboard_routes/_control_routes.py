"""Control route handlers extracted from _routes.py."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from admin_tasks import run_clean, run_ensure_labels, run_prep, run_scaffold
from app_version import get_app_version
from config import HydraFlowConfig, save_config_file
from dashboard_routes._common import _INTERVAL_BOUNDS
from dashboard_routes._routes import RouteContext
from events import EventType, HydraFlowEvent
from models import (
    BackgroundWorkersResponse,
    BackgroundWorkerState,
    BackgroundWorkerStatus,
    BGWorkerHealth,
    ControlStatus,
    OrchestratorStatusPayload,
)
from prompt_telemetry import PromptTelemetry
from route_types import ControlStatusConfig, ControlStatusResponse, RepoSlugParam
from update_check import load_cached_update_result

logger = logging.getLogger("hydraflow.dashboard")

# Known workers with human-friendly labels (pipeline loops + background)
_bg_worker_defs = [
    (
        "triage",
        "Triage",
        "Classifies freshly discovered issues and routes them into the pipeline.",
    ),
    (
        "plan",
        "Plan",
        "Builds implementation plans for triaged issues that are ready to execute.",
    ),
    (
        "implement",
        "Implement",
        "Runs coding agents to implement planned issues and open pull requests.",
    ),
    (
        "review",
        "Review",
        "Reviews PRs, applies fixes, and merges approved work when checks pass.",
    ),
    (
        "memory_sync",
        "Memory Manager",
        "Ingests memory and transcript issues into durable learnings and proposals.",
    ),
    (
        "retrospective",
        "Retrospective",
        "Captures post-merge outcomes and identifies recurring delivery patterns.",
    ),
    (
        "review_insights",
        "Review Insights",
        "Aggregates recurring review feedback into improvement opportunities.",
    ),
    (
        "pipeline_poller",
        "Pipeline Poller",
        "Refreshes live pipeline snapshots for dashboard queue/status rendering.",
    ),
    (
        "pr_unsticker",
        "PR Unsticker",
        "Requeues stalled HITL PRs by validating requirements and reopening flow.",
    ),
    (
        "report_issue",
        "Report Issue",
        "Processes queued bug reports into GitHub issues via the configured agent.",
    ),
    (
        "adr_reviewer",
        "ADR Reviewer",
        "Reviews proposed ADRs via a 3-judge council and routes to accept, reject, or escalate.",
    ),
]

# Workers that have independent configurable intervals
_INTERVAL_WORKERS = {
    "memory_sync",
    "pr_unsticker",
    "pipeline_poller",
    "report_issue",
}
# Pipeline loops share poll_interval (read-only display)
_PIPELINE_WORKERS = {"triage", "plan", "implement", "review"}
_WORKER_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "plan": ("planner",),
    "implement": ("agent",),
    "review": ("reviewer", "merge_conflict", "fresh_rebuild"),
}

_DEFAULT_PIPELINE_WORKERS = ("triage", "plan", "implement", "review", "hitl")


def register(router: APIRouter, ctx: RouteContext) -> None:  # noqa: PLR0915
    """Register control-related routes on *router*."""

    # Mutable fields that can be changed at runtime via PATCH
    _MUTABLE_FIELDS = {
        "max_triagers",
        "max_workers",
        "max_planners",
        "max_reviewers",
        "max_hitl_workers",
        "model",
        "review_model",
        "planner_model",
        "batch_size",
        "max_ci_fix_attempts",
        "max_quality_fix_attempts",
        "max_review_fix_attempts",
        "min_review_findings",
        "max_merge_conflict_fix_attempts",
        "ci_check_timeout",
        "ci_poll_interval",
        "poll_interval",
        "pr_unstick_interval",
        "pr_unstick_batch_size",
        "unstick_auto_merge",
        "unstick_all_causes",
        "memory_auto_approve",
        "workspace_base",
    }

    def _build_system_worker_inference_stats() -> dict[str, dict[str, int]]:
        """Aggregate prompt-telemetry inference stats keyed by worker name."""
        telemetry = PromptTelemetry(ctx.config)
        source_totals = telemetry.get_source_totals()

        worker_totals: dict[str, dict[str, int]] = {}
        for worker_name, _label, _description in _bg_worker_defs:
            sources = (worker_name, *_WORKER_SOURCE_ALIASES.get(worker_name, ()))
            totals = {
                "inference_calls": 0,
                "total_tokens": 0,
                "pruned_chars_total": 0,
            }
            for source_name in sources:
                source_entry = source_totals.get(source_name)
                if not source_entry:
                    continue
                totals["inference_calls"] += source_entry["inference_calls"]
                totals["total_tokens"] += source_entry["total_tokens"]
                totals["pruned_chars_total"] += source_entry["pruned_chars_total"]
            if totals["inference_calls"] > 0:
                saved_tokens_est = round(totals["pruned_chars_total"] / 4)
                worker_totals[worker_name] = {
                    "inference_calls": totals["inference_calls"],
                    "total_tokens": totals["total_tokens"],
                    "pruned_chars_total": totals["pruned_chars_total"],
                    "saved_tokens_est": saved_tokens_est,
                    "unpruned_tokens_est": totals["total_tokens"] + saved_tokens_est,
                }
        return worker_totals

    def _compute_next_run(
        last_run: str | None, interval_seconds: int | None
    ) -> str | None:
        """Compute next run ISO timestamp from last_run + interval."""
        if not last_run or not interval_seconds:
            return None
        try:
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            next_dt = last_dt + timedelta(seconds=interval_seconds)
            return next_dt.isoformat()
        except (ValueError, TypeError):
            return None

    @router.post("/api/control/start")
    async def start_orchestrator() -> JSONResponse:
        """Create and start a new orchestrator instance."""
        orch = ctx.get_orchestrator()
        if orch and orch.running:
            return JSONResponse({"error": "already running"}, status_code=409)

        from orchestrator import HydraFlowOrchestrator

        # Remove pipeline workers from the disabled set
        existing_disabled = ctx.state.get_disabled_workers()
        pipeline_names = set(_DEFAULT_PIPELINE_WORKERS)
        cleaned = existing_disabled - pipeline_names
        if cleaned != existing_disabled:
            ctx.state.set_disabled_workers(cleaned)

        new_orch = HydraFlowOrchestrator(
            ctx.config,
            event_bus=ctx.event_bus,
            state=ctx.state,
            pipeline_enabled=False,
        )
        ctx.set_orchestrator(new_orch)
        ctx.set_run_task(asyncio.create_task(new_orch.run()))
        await ctx.event_bus.publish(
            HydraFlowEvent(
                type=EventType.ORCHESTRATOR_STATUS,
                data=OrchestratorStatusPayload(status="running", reset=True),
            )
        )
        return JSONResponse({"status": "started"})

    @router.post("/api/control/stop")
    async def stop_orchestrator() -> JSONResponse:
        """Request a graceful stop of the running orchestrator."""
        orch = ctx.get_orchestrator()
        if not orch or not orch.running:
            return JSONResponse({"error": "not running"}, status_code=400)
        await orch.request_stop()
        return JSONResponse({"status": "stopping"})

    @router.post("/api/control/clear-credit-pause")
    async def clear_credit_pause() -> JSONResponse:
        """Clear an active credit pause, waking any sleeping loops."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        if orch.credits_paused_until is None:
            return JSONResponse({"error": "not paused"}, status_code=400)
        orch.clear_credit_pause()
        return JSONResponse({"status": "cleared"})

    @router.get("/api/control/status")
    async def get_control_status(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return orchestrator run status, config summary, and version info."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        status = "idle"
        current_session = None
        latest_version = ""
        update_available = False
        if orch:
            status = orch.run_status
            current_session = orch.current_session_id
        update_result = load_cached_update_result(current_version=get_app_version())
        if update_result is not None:
            latest_version = update_result.latest_version or ""
            update_available = update_result.update_available
        credits_until = (
            orch.credits_paused_until.isoformat()
            if orch and orch.credits_paused_until
            else None
        )
        try:
            control_status = ControlStatus(status)
        except ValueError:
            control_status = ControlStatus.IDLE
        response = ControlStatusResponse(
            status=control_status,
            credits_paused_until=credits_until,
            config=ControlStatusConfig(
                app_version=get_app_version(),
                latest_version=latest_version,
                update_available=update_available,
                repo=_cfg.repo,
                ready_label=_cfg.ready_label,
                find_label=_cfg.find_label,
                planner_label=_cfg.planner_label,
                review_label=_cfg.review_label,
                hitl_label=_cfg.hitl_label,
                hitl_active_label=_cfg.hitl_active_label,
                fixed_label=_cfg.fixed_label,
                max_triagers=_cfg.max_triagers,
                max_workers=_cfg.max_workers,
                max_planners=_cfg.max_planners,
                max_reviewers=_cfg.max_reviewers,
                max_hitl_workers=_cfg.max_hitl_workers,
                batch_size=_cfg.batch_size,
                model=_cfg.model,
                pr_unstick_batch_size=_cfg.pr_unstick_batch_size,
                workspace_base=str(_cfg.workspace_base),
            ),
        )
        data = response.model_dump()
        data["current_session_id"] = current_session
        return JSONResponse(data)

    @router.post("/api/control/credit-refresh")
    async def credit_refresh(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Attempt to clear credit pause and resume processing."""
        from subprocess_util import probe_credit_availability

        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        if orch.credits_paused_until is None:
            return JSONResponse({"status": "not_paused"})
        credits_available = await probe_credit_availability()
        if not credits_available:
            return JSONResponse({"status": "still_exhausted"})
        cleared = orch.try_clear_credit_pause()
        if not cleared:
            return JSONResponse({"status": "not_paused"})
        return JSONResponse({"status": "resuming"})

    @router.post("/api/admin/prep")
    async def admin_prep(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("prep", run_prep, repo)

    @router.post("/api/admin/scaffold")
    async def admin_scaffold(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("scaffold", run_scaffold, repo)

    @router.post("/api/admin/clean")
    async def admin_clean(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("clean", run_clean, repo)

    @router.post("/api/admin/ensure-labels")
    async def admin_ensure_labels(
        repo: str | None = Query(default=None, description="Repo slug to target"),
    ) -> JSONResponse:
        return await ctx.execute_admin_task("ensure-labels", run_ensure_labels, repo)

    @router.patch("/api/control/config")
    async def patch_config(
        body: dict[str, Any],
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Update runtime config fields. Pass ``persist: true`` to save to disk."""
        persist = body.pop("persist", False)
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)

        updates: dict[str, Any] = {}

        for key, value in body.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if not hasattr(_cfg, key):
                continue
            updates[key] = value

        if not updates:
            return JSONResponse({"status": "ok", "updated": {}})

        # Validate updates through Pydantic field constraints
        test_values = _cfg.model_dump()
        test_values.update(updates)
        try:
            validated = HydraFlowConfig.model_validate(test_values)
        except ValidationError as exc:
            errors = exc.errors()
            msg = "; ".join(
                f"{e['loc'][-1]}: {e['msg']}" for e in errors if e.get("loc")
            )
            return JSONResponse(
                {"status": "error", "message": msg or "Invalid configuration"},
                status_code=422,
            )

        # Apply validated values to the live config
        applied: dict[str, Any] = {}
        for key in updates:
            validated_value = getattr(validated, key)
            object.__setattr__(_cfg, key, validated_value)
            applied[key] = validated_value

        if applied:
            if repo and ctx.repo_store is not None:
                ctx.repo_store.update_overrides(repo, applied)
            elif persist:
                save_config_file(_cfg.config_file, applied)

        return JSONResponse({"status": "ok", "updated": applied})

    @router.get("/api/system/workers")
    async def get_system_workers(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return last known status of each background worker."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        bg_states = orch.get_bg_worker_states() if orch else {}
        persisted_states: dict[str, BackgroundWorkerState] = {}
        if not orch:
            try:
                persisted_states = _state.get_bg_worker_states()
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Failed to load persisted bg worker states")
        inference_by_worker = _build_system_worker_inference_stats()
        workers = []
        for name, label, description in _bg_worker_defs:
            enabled = orch.is_bg_worker_enabled(name) if orch else True

            # Determine interval for this worker
            interval: int | None = None
            if name in _INTERVAL_WORKERS and orch:
                interval = orch.get_bg_worker_interval(name)
            elif name in _INTERVAL_WORKERS:
                if name == "memory_sync":
                    interval = _cfg.memory_sync_interval
                elif name == "pr_unsticker":
                    interval = _cfg.pr_unstick_interval
                elif name == "pipeline_poller":
                    interval = 5
            elif name in _PIPELINE_WORKERS:
                interval = _cfg.poll_interval

            entry = bg_states.get(name) or persisted_states.get(name)
            if entry:
                last_run = entry.get("last_run")
                raw_details = entry.get("details", {})
                details: dict[str, Any] = (
                    dict(raw_details)
                    if isinstance(raw_details, dict)
                    else {"raw_details": str(raw_details)}
                )
                details.update(inference_by_worker.get(name, {}))
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        description=description,
                        status=BGWorkerHealth(
                            entry.get("status", BGWorkerHealth.DISABLED)
                        ),
                        enabled=enabled,
                        last_run=last_run,
                        interval_seconds=interval,
                        next_run=_compute_next_run(last_run, interval),
                        details=details,
                    )
                )
            else:
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        description=description,
                        enabled=enabled,
                        interval_seconds=interval,
                        details=inference_by_worker.get(name, {}),
                    )
                )
        return JSONResponse(BackgroundWorkersResponse(workers=workers).model_dump())

    @router.post("/api/control/bg-worker")
    async def toggle_bg_worker(body: dict[str, Any]) -> JSONResponse:
        """Enable or disable a background worker."""
        name = body.get("name")
        enabled = body.get("enabled")
        if not name or enabled is None:
            return JSONResponse(
                {"error": "name and enabled are required"}, status_code=400
            )
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        orch.set_bg_worker_enabled(name, bool(enabled))
        return JSONResponse({"status": "ok", "name": name, "enabled": bool(enabled)})

    @router.post("/api/control/bg-worker/trigger")
    async def trigger_bg_worker(body: dict[str, Any]) -> JSONResponse:
        """Trigger an immediate execution of a background worker."""
        name = body.get("name")
        if not name:
            return JSONResponse({"error": "name is required"}, status_code=400)
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        triggered = orch.trigger_bg_worker(name)
        if not triggered:
            return JSONResponse({"error": f"unknown worker '{name}'"}, status_code=404)
        return JSONResponse({"status": "ok", "name": name})

    @router.post("/api/control/bg-worker/interval")
    async def set_bg_worker_interval(body: dict[str, Any]) -> JSONResponse:
        """Update the polling interval for a background worker."""
        name = body.get("name")
        interval = body.get("interval_seconds")
        if not name or interval is None:
            return JSONResponse(
                {"error": "name and interval_seconds are required"}, status_code=400
            )
        if name not in _INTERVAL_BOUNDS:
            return JSONResponse(
                {"error": f"interval not editable for worker '{name}'"}, status_code=400
            )
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            return JSONResponse(
                {"error": "interval_seconds must be an integer"}, status_code=400
            )
        lo, hi = _INTERVAL_BOUNDS[name]
        if interval < lo or interval > hi:
            return JSONResponse(
                {"error": f"interval_seconds must be between {lo} and {hi}"},
                status_code=422,
            )
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        orch.set_bg_worker_interval(name, interval)
        return JSONResponse(
            {"status": "ok", "name": name, "interval_seconds": interval}
        )

    @router.get("/api/bot-pr/settings")
    async def get_bot_pr_settings() -> JSONResponse:
        """Return current bot PR auto-merge settings."""
        settings = ctx.state.get_bot_pr_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/bot-pr/settings")
    async def set_bot_pr_settings(body: dict[str, Any]) -> JSONResponse:
        """Update bot PR auto-merge settings."""
        current = ctx.state.get_bot_pr_settings()
        update = current.model_dump()
        for key in ("authors", "failure_strategy", "review_mode"):
            if key in body:
                update[key] = body[key]

        try:
            from models import BotPRSettings  # noqa: PLC0415

            new_settings = BotPRSettings(**update)
        except (ValueError, ValidationError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        ctx.state.set_bot_pr_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- Stale Issue Settings ---

    @router.get("/api/stale-issue/settings")
    async def get_stale_issue_settings() -> JSONResponse:
        """Return current stale issue cleanup settings."""
        settings = ctx.state.get_stale_issue_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/stale-issue/settings")
    async def set_stale_issue_settings(body: dict[str, Any]) -> JSONResponse:
        """Update stale issue cleanup settings."""
        current = ctx.state.get_stale_issue_settings()
        update = current.model_dump()
        for key in ("staleness_days", "excluded_labels", "dry_run"):
            if key in body:
                update[key] = body[key]
        try:
            from models import StaleIssueSettings  # noqa: PLC0415

            new_settings = StaleIssueSettings(**update)
        except (ValueError, ValidationError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        ctx.state.set_stale_issue_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- Security Patch Settings ---

    @router.get("/api/security-patch/settings")
    async def get_security_patch_settings() -> JSONResponse:
        """Return current security patch settings."""
        settings = ctx.state.get_security_patch_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/security-patch/settings")
    async def set_security_patch_settings(body: dict[str, Any]) -> JSONResponse:
        """Update security patch settings."""
        current = ctx.state.get_security_patch_settings()
        update = current.model_dump()
        for key in ("severity_levels",):
            if key in body:
                update[key] = body[key]
        try:
            from models import SecurityPatchSettings  # noqa: PLC0415

            new_settings = SecurityPatchSettings(**update)
        except (ValueError, ValidationError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        ctx.state.set_security_patch_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- CI Monitor Settings ---

    @router.get("/api/ci-monitor/settings")
    async def get_ci_monitor_settings() -> JSONResponse:
        """Return current CI monitor settings."""
        settings = ctx.state.get_ci_monitor_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/ci-monitor/settings")
    async def set_ci_monitor_settings(body: dict[str, Any]) -> JSONResponse:
        """Update CI monitor settings."""
        current = ctx.state.get_ci_monitor_settings()
        update = current.model_dump()
        for key in ("branch", "workflows", "create_issue"):
            if key in body:
                update[key] = body[key]
        try:
            from models import CIMonitorSettings  # noqa: PLC0415

            new_settings = CIMonitorSettings(**update)
        except (ValueError, ValidationError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        ctx.state.set_ci_monitor_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})

    # --- Code Grooming Settings ---

    @router.get("/api/code-grooming/settings")
    async def get_code_grooming_settings() -> JSONResponse:
        """Return current code grooming settings."""
        settings = ctx.state.get_code_grooming_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/code-grooming/settings")
    async def set_code_grooming_settings(body: dict[str, Any]) -> JSONResponse:
        """Update code grooming settings."""
        current = ctx.state.get_code_grooming_settings()
        update = current.model_dump()
        for key in (
            "max_issues_per_cycle",
            "min_priority",
            "enabled_audits",
            "dry_run",
        ):
            if key in body:
                update[key] = body[key]
        try:
            from models import CodeGroomingSettings  # noqa: PLC0415

            new_settings = CodeGroomingSettings(**update)
        except (ValueError, ValidationError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        ctx.state.set_code_grooming_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})
