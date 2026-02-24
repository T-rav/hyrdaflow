"""Route handlers for the HydraFlow dashboard API."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError

from config import HydraFlowConfig, save_config_file
from events import EventBus, EventType, HydraFlowEvent
from metrics_manager import get_metrics_cache_dir
from models import (
    BackgroundWorkersResponse,
    BackgroundWorkerStatus,
    ControlStatusConfig,
    ControlStatusResponse,
    IntentRequest,
    IntentResponse,
    MetricsHistoryResponse,
    MetricsResponse,
    MetricsSnapshot,
    PipelineIssue,
    PipelineSnapshot,
    QueueStats,
)
from pr_manager import PRManager
from state import StateTracker
from timeline import TimelineBuilder

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator

logger = logging.getLogger("hydraflow.dashboard")

# Backend stage keys → frontend stage names
_STAGE_NAME_MAP = {
    "find": "triage",
    "plan": "plan",
    "ready": "implement",
    "review": "review",
    "hitl": "hitl",
}

# Frontend stage key → config label field name (for request-changes)
_FRONTEND_STAGE_TO_LABEL_FIELD = {
    "triage": "find_label",
    "plan": "planner_label",
    "implement": "ready_label",
    "review": "review_label",
}


def create_router(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    pr_manager: PRManager,
    get_orchestrator: Callable[[], HydraFlowOrchestrator | None],
    set_orchestrator: Callable[[HydraFlowOrchestrator], None],
    set_run_task: Callable[[asyncio.Task[None]], None],
    ui_dist_dir: Path,
    template_dir: Path,
) -> APIRouter:
    """Create an APIRouter with all dashboard route handlers."""
    router = APIRouter()

    def _serve_spa_index() -> HTMLResponse:
        """Serve the SPA index.html, falling back to template or placeholder."""
        react_index = ui_dist_dir / "index.html"
        if react_index.exists():
            return HTMLResponse(react_index.read_text())
        template_path = template_dir / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text())
        return HTMLResponse(
            "<h1>HydraFlow Dashboard</h1><p>Run 'make ui' to build.</p>"
        )

    def _load_local_metrics_cache(
        limit: int = 100,
    ) -> list[MetricsSnapshot]:
        """Load metrics snapshots from local disk cache without requiring the orchestrator."""
        cache_file = get_metrics_cache_dir(config) / "snapshots.jsonl"
        if not cache_file.exists():
            return []
        snapshots: list[MetricsSnapshot] = []
        with open(cache_file) as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    snapshots.append(MetricsSnapshot.model_validate_json(stripped))
                except ValidationError:
                    logger.debug(
                        "Skipping corrupt metrics snapshot line",
                        exc_info=True,
                    )
                    continue
        return snapshots[-limit:]

    @router.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return _serve_spa_index()

    @router.get("/api/state")
    async def get_state() -> JSONResponse:
        return JSONResponse(state.to_dict())

    @router.get("/api/stats")
    async def get_stats() -> JSONResponse:
        data: dict[str, Any] = state.get_lifetime_stats().model_dump()
        orch = get_orchestrator()
        if orch:
            data["queue"] = orch.issue_store.get_queue_stats().model_dump()
        return JSONResponse(data)

    @router.get("/api/queue")
    async def get_queue() -> JSONResponse:
        """Return current queue depths, active counts, and throughput."""
        orch = get_orchestrator()
        if orch:
            return JSONResponse(orch.issue_store.get_queue_stats().model_dump())
        return JSONResponse(QueueStats().model_dump())

    @router.post("/api/request-changes")
    async def request_changes(body: dict[str, Any]) -> JSONResponse:
        """Escalate an issue to HITL with user feedback."""
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

        stage_labels: list[str] = getattr(config, label_field, [])
        origin_label: str = stage_labels[0]

        for lbl in stage_labels:
            await pr_manager.remove_label(issue_number, lbl)
        await pr_manager.add_labels(issue_number, config.hitl_label)

        state.set_hitl_cause(issue_number, feedback)
        state.set_hitl_origin(issue_number, origin_label)

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_ESCALATION,
                data={
                    "issue": issue_number,
                    "cause": feedback,
                    "origin": origin_label,
                },
            )
        )

        return JSONResponse({"status": "ok"})

    @router.get("/api/pipeline")
    async def get_pipeline() -> JSONResponse:
        """Return current pipeline snapshot with issues per stage."""
        orch = get_orchestrator()
        if orch:
            raw = orch.issue_store.get_pipeline_snapshot()
            mapped: dict[str, list[dict[str, object]]] = {}
            for backend_stage, issues in raw.items():
                frontend_stage = _STAGE_NAME_MAP.get(backend_stage, backend_stage)
                mapped[frontend_stage] = issues
            snapshot = PipelineSnapshot(
                stages={
                    k: [PipelineIssue(**i) for i in v]  # type: ignore[arg-type]
                    for k, v in mapped.items()
                }
            )
            return JSONResponse(snapshot.model_dump())
        return JSONResponse(PipelineSnapshot().model_dump())

    @router.get("/api/events")
    async def get_events(since: str | None = None) -> JSONResponse:
        if since is not None:
            from datetime import datetime

            try:
                since_dt = datetime.fromisoformat(since)
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=UTC)
                events = await event_bus.load_events_since(since_dt)
                if events is not None:
                    return JSONResponse([e.model_dump() for e in events])
            except (ValueError, TypeError):
                pass  # Fall through to in-memory history
        history = event_bus.get_history()
        return JSONResponse([e.model_dump() for e in history])

    @router.get("/api/prs")
    async def get_prs() -> JSONResponse:
        """Fetch all open HydraFlow PRs from GitHub."""
        all_labels = list(
            {
                *config.ready_label,
                *config.review_label,
                *config.fixed_label,
                *config.hitl_label,
                *config.hitl_active_label,
                *config.planner_label,
                *config.improve_label,
            }
        )
        items = await pr_manager.list_open_prs(all_labels)
        return JSONResponse([item.model_dump() for item in items])

    @router.get("/api/hitl")
    async def get_hitl() -> JSONResponse:
        """Fetch issues/PRs labeled for human-in-the-loop (stuck on CI)."""
        items = await pr_manager.list_hitl_items(config.hitl_label)
        orch = get_orchestrator()
        enriched = []
        for item in items:
            data = item.model_dump()
            if orch:
                data["status"] = orch.get_hitl_status(item.issue)
            cause = state.get_hitl_cause(item.issue)
            origin = state.get_hitl_origin(item.issue)
            if not cause and origin:
                if origin in config.improve_label:
                    cause = "Self-improvement proposal"
                elif origin in config.review_label:
                    cause = "Review escalation"
                elif origin in config.find_label:
                    cause = "Triage escalation"
                else:
                    cause = "Escalation (reason not recorded)"
            if cause:
                data["cause"] = cause
            if origin and origin in config.improve_label:
                data["isMemorySuggestion"] = True
            enriched.append(data)
        return JSONResponse(enriched)

    @router.post("/api/hitl/{issue_number}/correct")
    async def hitl_correct(issue_number: int, body: dict[str, Any]) -> JSONResponse:
        """Submit a correction for a HITL issue to guide retry."""
        orch = get_orchestrator()
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
        await pr_manager.swap_pipeline_labels(issue_number, config.hitl_active_label[0])

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "processing",
                    "action": "correct",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/skip")
    async def hitl_skip(issue_number: int) -> JSONResponse:
        """Remove a HITL issue from the queue without action."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)

        # Read origin before clearing state
        origin = state.get_hitl_origin(issue_number)

        orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        state.remove_hitl_cause(issue_number)

        # If this was an improve issue, transition to triage for implementation
        if origin and origin in config.improve_label and config.find_label:
            await pr_manager.swap_pipeline_labels(issue_number, config.find_label[0])
        else:
            # Just remove all pipeline labels
            for lbl in config.all_pipeline_labels:
                await pr_manager.remove_label(issue_number, lbl)

        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "skip",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/close")
    async def hitl_close(issue_number: int) -> JSONResponse:
        """Close a HITL issue on GitHub."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"status": "no orchestrator"}, status_code=400)
        orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        await pr_manager.close_issue(issue_number)
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "close",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.post("/api/hitl/{issue_number}/approve-memory")
    async def hitl_approve_memory(issue_number: int) -> JSONResponse:
        """Approve a HITL item as a memory suggestion, relabeling for sync."""
        # Remove all pipeline labels and add memory label
        for lbl in config.all_pipeline_labels:
            await pr_manager.remove_label(issue_number, lbl)
        await pr_manager.add_labels(issue_number, config.memory_label)
        orch = get_orchestrator()
        if orch:
            orch.skip_hitl_issue(issue_number)
        state.remove_hitl_origin(issue_number)
        state.remove_hitl_cause(issue_number)
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.HITL_UPDATE,
                data={
                    "issue": issue_number,
                    "status": "resolved",
                    "action": "approved_as_memory",
                },
            )
        )
        return JSONResponse({"status": "ok"})

    @router.get("/api/human-input")
    async def get_human_input_requests() -> JSONResponse:
        orch = get_orchestrator()
        if orch:
            return JSONResponse(orch.human_input_requests)
        return JSONResponse({})

    @router.post("/api/human-input/{issue_number}")
    async def provide_human_input(
        issue_number: int, body: dict[str, Any]
    ) -> JSONResponse:
        orch = get_orchestrator()
        if orch:
            answer = body.get("answer", "")
            orch.provide_human_input(issue_number, answer)
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "no orchestrator"}, status_code=400)

    @router.post("/api/control/start")
    async def start_orchestrator() -> JSONResponse:
        orch = get_orchestrator()
        if orch and orch.running:
            return JSONResponse({"error": "already running"}, status_code=409)

        from orchestrator import HydraFlowOrchestrator

        new_orch = HydraFlowOrchestrator(
            config,
            event_bus=event_bus,
            state=state,
        )
        set_orchestrator(new_orch)
        set_run_task(asyncio.create_task(new_orch.run()))
        await event_bus.publish(
            HydraFlowEvent(
                type=EventType.ORCHESTRATOR_STATUS,
                data={"status": "running", "reset": True},
            )
        )
        return JSONResponse({"status": "started"})

    @router.post("/api/control/stop")
    async def stop_orchestrator() -> JSONResponse:
        orch = get_orchestrator()
        if not orch or not orch.running:
            return JSONResponse({"error": "not running"}, status_code=400)
        await orch.request_stop()
        return JSONResponse({"status": "stopping"})

    @router.get("/api/control/status")
    async def get_control_status() -> JSONResponse:
        orch = get_orchestrator()
        status = "idle"
        current_session = None
        if orch:
            status = orch.run_status
            current_session = orch.current_session_id
        response = ControlStatusResponse(
            status=status,
            config=ControlStatusConfig(
                repo=config.repo,
                ready_label=config.ready_label,
                find_label=config.find_label,
                planner_label=config.planner_label,
                review_label=config.review_label,
                hitl_label=config.hitl_label,
                hitl_active_label=config.hitl_active_label,
                fixed_label=config.fixed_label,
                improve_label=config.improve_label,
                memory_label=config.memory_label,
                max_workers=config.max_workers,
                max_planners=config.max_planners,
                max_reviewers=config.max_reviewers,
                max_hitl_workers=config.max_hitl_workers,
                batch_size=config.batch_size,
                model=config.model,
                memory_auto_approve=config.memory_auto_approve,
                unstick_max_workers=config.unstick_max_workers,
            ),
        )
        data = response.model_dump()
        data["current_session_id"] = current_session
        return JSONResponse(data)

    # Mutable fields that can be changed at runtime via PATCH
    _MUTABLE_FIELDS = {
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
        "memory_auto_approve",
        "unstick_max_workers",
        "unstick_auto_merge",
        "unstick_all_causes",
    }

    @router.patch("/api/control/config")
    async def patch_config(body: dict[str, Any]) -> JSONResponse:
        """Update runtime config fields. Pass ``persist: true`` to save to disk."""
        persist = body.pop("persist", False)
        updates: dict[str, Any] = {}

        for key, value in body.items():
            if key not in _MUTABLE_FIELDS:
                continue
            if not hasattr(config, key):
                continue
            updates[key] = value

        if not updates:
            return JSONResponse({"status": "ok", "updated": {}})

        # Validate updates through Pydantic field constraints
        test_values = config.model_dump()
        test_values.update(updates)
        try:
            validated = HydraFlowConfig.model_validate(test_values)
        except ValidationError as exc:
            errors = exc.errors()
            msg = "; ".join(
                f"{e['loc'][-1]}: {e['msg']}" for e in errors if e.get("loc")
            )
            return JSONResponse(
                {"status": "error", "message": msg or str(exc)},
                status_code=422,
            )

        # Apply validated values to the live config
        applied: dict[str, Any] = {}
        for key in updates:
            validated_value = getattr(validated, key)
            object.__setattr__(config, key, validated_value)
            applied[key] = validated_value

        if persist and applied:
            save_config_file(config.config_file, applied)

        return JSONResponse({"status": "ok", "updated": applied})

    # Known workers with human-friendly labels (pipeline loops + background)
    _bg_worker_defs = [
        ("triage", "Triage"),
        ("plan", "Plan"),
        ("implement", "Implement"),
        ("review", "Review"),
        ("memory_sync", "Memory Manager"),
        ("retrospective", "Retrospective"),
        ("metrics", "Metrics"),
        ("review_insights", "Review Insights"),
        ("pipeline_poller", "Pipeline Poller"),
        ("pr_unsticker", "PR Unsticker"),
    ]

    # Workers that have independent configurable intervals
    _INTERVAL_WORKERS = {"memory_sync", "metrics", "pr_unsticker", "pipeline_poller"}
    # Pipeline loops share poll_interval (read-only display)
    _PIPELINE_WORKERS = {"triage", "plan", "implement", "review"}

    def _compute_next_run(
        last_run: str | None, interval_seconds: int | None
    ) -> str | None:
        """Compute next run ISO timestamp from last_run + interval."""
        if not last_run or not interval_seconds:
            return None
        from datetime import datetime, timedelta

        try:
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            next_dt = last_dt + timedelta(seconds=interval_seconds)
            return next_dt.isoformat()
        except (ValueError, TypeError):
            return None

    @router.get("/api/system/workers")
    async def get_system_workers() -> JSONResponse:
        """Return last known status of each background worker."""
        orch = get_orchestrator()
        bg_states = orch.get_bg_worker_states() if orch else {}
        workers = []
        for name, label in _bg_worker_defs:
            enabled = orch.is_bg_worker_enabled(name) if orch else True

            # Determine interval for this worker
            interval: int | None = None
            if name in _INTERVAL_WORKERS and orch:
                interval = orch.get_bg_worker_interval(name)
            elif name in _INTERVAL_WORKERS:
                if name == "memory_sync":
                    interval = config.memory_sync_interval
                elif name == "metrics":
                    interval = config.metrics_sync_interval
                elif name == "pr_unsticker":
                    interval = config.pr_unstick_interval
                elif name == "pipeline_poller":
                    interval = 5
            elif name in _PIPELINE_WORKERS:
                interval = config.poll_interval

            if name in bg_states:
                entry = bg_states[name]
                last_run = entry.get("last_run")
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        status=entry["status"],
                        enabled=enabled,
                        last_run=last_run,
                        interval_seconds=interval,
                        next_run=_compute_next_run(last_run, interval),
                        details=entry.get("details", {}),
                    )
                )
            else:
                workers.append(
                    BackgroundWorkerStatus(
                        name=name,
                        label=label,
                        enabled=enabled,
                        interval_seconds=interval,
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
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        orch.set_bg_worker_enabled(name, bool(enabled))
        return JSONResponse({"status": "ok", "name": name, "enabled": bool(enabled)})

    # Interval bounds per editable worker.
    # memory_sync, metrics, pr_unsticker bounds must match config.py Field constraints.
    # pipeline_poller has no config Field; 5s minimum matches the hardcoded default.
    _INTERVAL_BOUNDS = {
        "memory_sync": (10, 14400),
        "metrics": (30, 14400),
        "pr_unsticker": (60, 86400),
        "pipeline_poller": (5, 14400),
    }

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
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        orch.set_bg_worker_interval(name, interval)
        return JSONResponse(
            {"status": "ok", "name": name, "interval_seconds": interval}
        )

    @router.get("/api/metrics")
    async def get_metrics() -> JSONResponse:
        """Return lifetime stats, derived rates, time-to-merge, and thresholds."""
        lifetime = state.get_lifetime_stats()
        rates: dict[str, float] = {}
        total_reviews = (
            lifetime.total_review_approvals + lifetime.total_review_request_changes
        )
        if lifetime.issues_completed > 0:
            rates["merge_rate"] = lifetime.prs_merged / lifetime.issues_completed
            rates["quality_fix_rate"] = (
                lifetime.total_quality_fix_rounds / lifetime.issues_completed
            )
            rates["hitl_escalation_rate"] = (
                lifetime.total_hitl_escalations / lifetime.issues_completed
            )
            rates["avg_implementation_seconds"] = (
                lifetime.total_implementation_seconds / lifetime.issues_completed
            )
        if total_reviews > 0:
            rates["first_pass_approval_rate"] = (
                lifetime.total_review_approvals / total_reviews
            )
            rates["reviewer_fix_rate"] = lifetime.total_reviewer_fixes / total_reviews
        time_to_merge = state.get_merge_duration_stats()
        thresholds = state.check_thresholds(
            config.quality_fix_rate_threshold,
            config.approval_rate_threshold,
            config.hitl_rate_threshold,
        )
        retries = state.get_retries_summary()
        if retries:
            rates["retries_per_stage"] = sum(retries.values())
        return JSONResponse(
            MetricsResponse(
                lifetime=lifetime,
                rates=rates,
                time_to_merge=time_to_merge,
                thresholds=thresholds,
            ).model_dump()
        )

    @router.get("/api/metrics/github")
    async def get_github_metrics() -> JSONResponse:
        """Query GitHub for issue/PR counts by label state."""
        counts = await pr_manager.get_label_counts(config)
        return JSONResponse(counts)

    @router.get("/api/metrics/history")
    async def get_metrics_history() -> JSONResponse:
        """Historical snapshots from the metrics issue + current in-memory snapshot.

        Falls back to local disk cache when the orchestrator is not running.
        """
        orch = get_orchestrator()
        if orch is None:
            # Serve from local cache without requiring the orchestrator
            snapshots = _load_local_metrics_cache()
            return JSONResponse(
                MetricsHistoryResponse(snapshots=snapshots).model_dump()
            )
        mgr = orch.metrics_manager
        snapshots = await mgr.fetch_history_from_issue()
        current = mgr.latest_snapshot
        return JSONResponse(
            MetricsHistoryResponse(
                snapshots=snapshots,
                current=current,
            ).model_dump()
        )

    @router.get("/api/runs")
    async def list_run_issues() -> JSONResponse:
        """Return issue numbers that have recorded runs."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse([])
        return JSONResponse(orch.run_recorder.list_issues())

    @router.get("/api/runs/{issue_number}")
    async def get_runs(issue_number: int) -> JSONResponse:
        """Return all recorded runs for an issue."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse([])
        runs = orch.run_recorder.list_runs(issue_number)
        return JSONResponse([r.model_dump() for r in runs])

    @router.get("/api/runs/{issue_number}/{timestamp}/{filename}")
    async def get_run_artifact(
        issue_number: int, timestamp: str, filename: str
    ) -> Response:
        """Return a specific artifact file from a recorded run."""
        orch = get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        content = orch.run_recorder.get_run_artifact(issue_number, timestamp, filename)
        if content is None:
            return JSONResponse({"error": "artifact not found"}, status_code=404)
        return Response(content=content, media_type="text/plain")

    @router.get("/api/harness-insights")
    async def get_harness_insights() -> JSONResponse:
        """Return recent harness failure patterns and improvement suggestions."""
        from harness_insights import (
            HarnessInsightStore,
            generate_suggestions,
        )

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        records = store.load_recent(config.harness_insight_window)
        proposed = store.get_proposed_patterns()
        suggestions = generate_suggestions(
            records, config.harness_pattern_threshold, proposed
        )

        # Build category summary
        cat_counts: Counter[str] = Counter(r.category for r in records)
        sub_counts: Counter[str] = Counter()
        for r in records:
            for sub in r.subcategories:
                sub_counts[sub] += 1

        return JSONResponse(
            {
                "total_failures": len(records),
                "category_counts": dict(cat_counts.most_common()),
                "subcategory_counts": dict(sub_counts.most_common()),
                "suggestions": [s.model_dump() for s in suggestions],
                "proposed_patterns": sorted(proposed),
            }
        )

    @router.get("/api/harness-insights/history")
    async def get_harness_insights_history() -> JSONResponse:
        """Return raw failure records for historical analysis."""
        from harness_insights import HarnessInsightStore

        memory_dir = config.repo_root / ".hydraflow" / "memory"
        store = HarnessInsightStore(memory_dir)
        records = store.load_recent(config.harness_insight_window)
        return JSONResponse([r.model_dump() for r in records])

    @router.get("/api/timeline")
    async def get_timeline() -> JSONResponse:
        builder = TimelineBuilder(event_bus)
        timelines = builder.build_all()
        return JSONResponse([t.model_dump() for t in timelines])

    @router.get("/api/timeline/issue/{issue_num}")
    async def get_timeline_issue(issue_num: int) -> JSONResponse:
        builder = TimelineBuilder(event_bus)
        timeline = builder.build_for_issue(issue_num)
        if timeline is None:
            return JSONResponse({"error": "Issue not found"}, status_code=404)
        return JSONResponse(timeline.model_dump())

    @router.post("/api/intent")
    async def submit_intent(request: IntentRequest) -> JSONResponse:
        """Create a GitHub issue from a user intent typed in the dashboard."""
        title = request.text[:120]
        body = request.text
        labels = list(config.planner_label)

        issue_number = await pr_manager.create_issue(
            title=title, body=body, labels=labels
        )

        if issue_number == 0:
            return JSONResponse({"error": "Failed to create issue"}, status_code=500)

        url = f"https://github.com/{config.repo}/issues/{issue_number}"
        response = IntentResponse(issue_number=issue_number, title=title, url=url)
        return JSONResponse(response.model_dump())

    @router.get("/api/sessions")
    async def get_sessions(repo: str | None = None) -> JSONResponse:
        """Return session logs, optionally filtered by repo."""
        sessions = state.load_sessions(repo=repo)
        return JSONResponse([s.model_dump() for s in sessions])

    @router.get("/api/sessions/{session_id}")
    async def get_session_detail(session_id: str) -> JSONResponse:
        """Return a single session by ID with associated events."""
        session = state.get_session(session_id)
        if session is None:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        # Include events tagged with this session_id
        all_events = event_bus.get_history()
        session_events = [
            e.model_dump() for e in all_events if e.session_id == session_id
        ]
        data = session.model_dump()
        data["events"] = session_events
        return JSONResponse(data)

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> JSONResponse:
        """Delete a session by ID. Returns 400 if active, 404 if not found."""
        try:
            deleted = state.delete_session(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not deleted:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse({"status": "ok"})

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()

        # Snapshot history BEFORE subscribing to avoid duplicates.
        # Events published between snapshot and subscribe are picked
        # up by the live queue, never sent twice.
        history = event_bus.get_history()

        async with event_bus.subscription() as queue:
            # Send history on connect
            for event in history:
                try:
                    await ws.send_text(event.model_dump_json())
                except Exception:
                    logger.warning(
                        "WebSocket error during history replay", exc_info=True
                    )
                    return

            # Stream live events
            try:
                while True:
                    event: HydraFlowEvent = await queue.get()
                    await ws.send_text(event.model_dump_json())
            except WebSocketDisconnect:
                pass
            except Exception:
                logger.warning("WebSocket error during live streaming", exc_info=True)

    # SPA catch-all: serve index.html for any path not matched above.
    # This must be registered LAST so it doesn't shadow API/WS routes.
    @router.get("/{path:path}", response_model=None)
    async def spa_catchall(path: str) -> Response:
        # Don't catch API, WebSocket, or static-asset paths
        if path.startswith(("api/", "ws/", "assets/", "static/")) or path == "ws":
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        # Serve root-level static files from ui/dist/ (e.g. logos, favicon)
        static_file = (ui_dist_dir / path).resolve()
        if static_file.is_relative_to(ui_dist_dir.resolve()) and static_file.is_file():
            return FileResponse(static_file)

        return _serve_spa_index()

    return router
