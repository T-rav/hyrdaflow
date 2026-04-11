"""Metrics route handlers extracted from _routes.py."""

from __future__ import annotations

import contextlib
import logging
from collections import Counter

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from config import HydraFlowConfig
from dashboard_routes._routes import RouteContext
from metrics_manager import get_metrics_cache_dir
from models import (
    MetricsHistoryResponse,
    MetricsResponse,
    MetricsSnapshot,
)
from prompt_telemetry import PromptTelemetry
from route_types import RepoSlugParam

logger = logging.getLogger("hydraflow.dashboard")


def register(router: APIRouter, ctx: RouteContext) -> None:  # noqa: PLR0915
    """Register metrics-related routes on *router*."""

    def _load_local_metrics_cache(
        target_config: HydraFlowConfig,
        limit: int = 100,
    ) -> list[MetricsSnapshot]:
        """Load metrics snapshots from local disk cache without requiring the orchestrator."""
        cache_file = get_metrics_cache_dir(target_config) / "snapshots.jsonl"
        if not cache_file.exists():
            return []
        snapshots: list[MetricsSnapshot] = []
        try:
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
        except OSError:
            logger.warning(
                "Could not read metrics cache %s",
                cache_file,
                exc_info=True,
            )
            return []
        return snapshots[-limit:]

    @router.get("/api/issues/outcomes")
    async def get_issue_outcomes() -> JSONResponse:
        """Return all recorded issue outcomes."""
        outcomes = ctx.state.get_all_outcomes()
        return JSONResponse({k: v.model_dump() for k, v in outcomes.items()})

    @router.get("/api/metrics")
    async def get_metrics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Return lifetime stats, derived rates, time-to-merge, and thresholds."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        lifetime = _state.get_lifetime_stats()
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
        time_to_merge = _state.get_merge_duration_stats()
        thresholds = _state.check_thresholds(
            _cfg.quality_fix_rate_threshold,
            _cfg.approval_rate_threshold,
            _cfg.hitl_rate_threshold,
        )
        retries = _state.get_retries_summary()
        if retries:
            rates["retries_per_stage"] = sum(retries.values())

        telemetry = PromptTelemetry(_cfg)
        inference_lifetime = telemetry.get_lifetime_totals()
        orch = _get_orch()
        session_id = orch.current_session_id if orch else ""
        inference_session = (
            telemetry.get_session_totals(session_id) if session_id else {}
        )

        return JSONResponse(
            MetricsResponse(
                lifetime=lifetime,
                rates=rates,
                time_to_merge=time_to_merge,
                thresholds=thresholds,
                inference_lifetime=inference_lifetime,
                inference_session=inference_session,
            ).model_dump()
        )

    @router.get("/api/metrics/github")
    async def get_github_metrics(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Query GitHub for issue/PR counts by label state."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        manager = ctx.pr_manager_for(_cfg, _bus)
        counts = await manager.get_label_counts(_cfg)
        return JSONResponse(counts)

    @router.get("/api/metrics/history")
    async def get_metrics_history(
        repo: RepoSlugParam = None,
    ) -> JSONResponse:
        """Historical snapshots from the metrics issue + current in-memory snapshot."""
        _cfg, _state, _bus, _get_orch = ctx.resolve_runtime(repo)
        orch = _get_orch()
        if orch is None:
            snapshots = _load_local_metrics_cache(_cfg)
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
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse([])
        return JSONResponse(orch.run_recorder.list_issues())

    @router.get("/api/runs/{issue_number}")
    async def get_runs(issue_number: int) -> JSONResponse:
        """Return all recorded runs for an issue."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse([])
        runs = orch.run_recorder.list_runs(issue_number)
        return JSONResponse([r.model_dump() for r in runs])

    @router.get("/api/runs/{issue_number}/{timestamp}/{filename}")
    async def get_run_artifact(
        issue_number: int, timestamp: str, filename: str
    ) -> Response:
        """Return a specific artifact file from a recorded run."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        content = orch.run_recorder.get_run_artifact(issue_number, timestamp, filename)
        if content is None:
            return JSONResponse({"error": "artifact not found"}, status_code=404)
        return Response(content=content, media_type="text/plain")

    @router.get("/api/artifacts/stats")
    async def get_artifact_stats() -> JSONResponse:
        """Return storage statistics for run artifacts."""
        orch = ctx.get_orchestrator()
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        stats = orch.run_recorder.get_storage_stats()
        stats["retention_days"] = ctx.config.artifact_retention_days
        stats["max_size_mb"] = ctx.config.artifact_max_size_mb
        return JSONResponse(stats)

    @router.get("/api/harness-insights")
    async def get_harness_insights() -> JSONResponse:
        """Return recent harness failure patterns and improvement suggestions."""
        from harness_insights import (
            HarnessInsightStore,
            generate_suggestions,
        )

        memory_dir = ctx.config.data_path("memory")
        store = HarnessInsightStore(memory_dir)
        records = store.load_recent(ctx.config.harness_insight_window)
        proposed = store.get_proposed_patterns()
        suggestions = generate_suggestions(
            records, ctx.config.harness_pattern_threshold, proposed
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

        memory_dir = ctx.config.data_path("memory")
        store = HarnessInsightStore(memory_dir)
        records = store.load_recent(ctx.config.harness_insight_window)
        return JSONResponse([r.model_dump() for r in records])

    @router.get("/api/review-insights")
    async def get_review_insights() -> JSONResponse:
        """Return aggregated review feedback patterns and category breakdown."""
        from review_insights import ReviewInsightStore, analyze_patterns

        memory_dir = ctx.config.data_path("memory")
        store = ReviewInsightStore(memory_dir)
        records = store.load_recent(ctx.config.review_insight_window)
        proposed = store.get_proposed_categories()

        verdict_counts: Counter[str] = Counter(r.verdict.value for r in records)
        category_counts: Counter[str] = Counter(
            cat for r in records for cat in r.categories
        )
        fixes_made_count = sum(1 for r in records if r.fixes_made)

        patterns_raw = analyze_patterns(records, ctx.config.harness_pattern_threshold)
        patterns = [
            {
                "category": cat,
                "count": cnt,
                "evidence": [
                    {
                        "issue_number": r.issue_number,
                        "pr_number": r.pr_number,
                        "summary": r.summary,
                    }
                    for r in evidence
                ],
            }
            for cat, cnt, evidence in patterns_raw
        ]

        return JSONResponse(
            {
                "total_reviews": len(records),
                "verdict_counts": dict(verdict_counts),
                "category_counts": dict(category_counts),
                "fixes_made_count": fixes_made_count,
                "patterns": patterns,
                "proposed_categories": sorted(proposed),
            }
        )

    @router.get("/api/retrospectives")
    async def get_retrospectives() -> JSONResponse:
        """Return aggregated retrospective stats and recent entries."""
        from retrospective import RetrospectiveEntry

        retro_path = ctx.config.data_path("memory", "retrospectives.jsonl")
        entries: list[RetrospectiveEntry] = []
        if retro_path.exists():
            for line in retro_path.read_text().strip().splitlines():
                with contextlib.suppress(Exception):
                    entries.append(RetrospectiveEntry.model_validate_json(line))
        entries = entries[-ctx.config.retrospective_window :]

        if not entries:
            return JSONResponse(
                {
                    "total_entries": 0,
                    "avg_plan_accuracy": 0,
                    "avg_quality_fix_rounds": 0,
                    "avg_ci_fix_rounds": 0,
                    "avg_duration_seconds": 0,
                    "reviewer_fix_rate": 0,
                    "verdict_counts": {},
                    "entries": [],
                }
            )

        n = len(entries)
        avg_accuracy = round(sum(e.plan_accuracy_pct for e in entries) / n, 1)
        avg_quality = round(sum(e.quality_fix_rounds for e in entries) / n, 2)
        avg_ci = round(sum(e.ci_fix_rounds for e in entries) / n, 2)
        avg_duration = round(sum(e.duration_seconds for e in entries) / n, 1)
        fix_count = sum(1 for e in entries if e.reviewer_fixes_made)
        verdict_counts: Counter[str] = Counter(
            str(e.review_verdict) for e in entries if e.review_verdict
        )

        return JSONResponse(
            {
                "total_entries": n,
                "avg_plan_accuracy": avg_accuracy,
                "avg_quality_fix_rounds": avg_quality,
                "avg_ci_fix_rounds": avg_ci,
                "avg_duration_seconds": avg_duration,
                "reviewer_fix_rate": round(fix_count / n, 3),
                "verdict_counts": dict(verdict_counts),
                "entries": [e.model_dump() for e in entries],
            }
        )
