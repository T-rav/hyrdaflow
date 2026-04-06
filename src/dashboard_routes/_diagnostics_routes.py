"""Diagnostics dashboard routes.

Nine read-only endpoints that surface factory metrics (read from
``<data_root>/diagnostics/factory_metrics.jsonl``) and per-run trace
artifacts (``<data_root>/traces/<issue>/<phase>/run-N/``) for the
Diagnostics tab of the dashboard UI.

All endpoints accept a ``range`` query parameter (``24h``/``7d``/``30d``/
``all``) that is forwarded to :func:`factory_metrics.load_metrics`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

from factory_metrics import (
    aggregate_top_skills,
    aggregate_top_subagents,
    aggregate_top_tools,
    cost_by_phase,
    headline_metrics,
    issues_table,
    load_metrics,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.dashboard.diagnostics")


def _safe_traces_subdir(data_root: Path, *parts: str | int) -> Path | None:
    """Resolve a path under ``<data_root>/traces`` and reject traversal.

    Returns the resolved ``Path`` on success, or ``None`` if the resulting
    path escapes the traces directory (e.g. via ``..`` segments).
    """
    safe_root = (data_root / "traces").resolve()
    candidate = (data_root / "traces").joinpath(*[str(p) for p in parts]).resolve()
    try:
        candidate.relative_to(safe_root)
    except ValueError:
        return None
    return candidate


def _sort_issues(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Return ``rows`` sorted by ``sort`` key (descending for numeric)."""
    if sort == "duration":
        return sorted(rows, key=lambda r: r.get("duration_seconds") or 0, reverse=True)
    if sort == "issue":
        return sorted(rows, key=lambda r: r.get("issue") or 0)
    # default: tokens descending
    return sorted(rows, key=lambda r: r.get("tokens") or 0, reverse=True)


def _parse_event_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _cache_hit_rate_buckets(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a list of ``{timestamp, cache_hit_rate}`` rows, one per hour.

    Events without a parseable timestamp are dropped. Buckets are sorted
    ascending by hour.
    """
    buckets: dict[datetime, dict[str, int]] = {}
    for event in events:
        ts = _parse_event_timestamp(event.get("timestamp"))
        if ts is None:
            continue
        hour = ts.replace(minute=0, second=0, microsecond=0)
        tokens = event.get("tokens") or {}
        if not isinstance(tokens, dict):
            continue
        input_value = tokens.get("input", 0)
        cache_read_value = tokens.get("cache_read", 0)
        slot = buckets.setdefault(hour, {"input": 0, "cache_read": 0})
        if isinstance(input_value, int | float):
            slot["input"] += int(input_value)
        if isinstance(cache_read_value, int | float):
            slot["cache_read"] += int(cache_read_value)

    rows: list[dict[str, Any]] = []
    for hour in sorted(buckets.keys()):
        totals = buckets[hour]
        denom = totals["input"] + totals["cache_read"]
        rate = round(totals["cache_read"] / denom, 4) if denom > 0 else 0.0
        rows.append(
            {
                "timestamp": hour.isoformat(),
                "cache_hit_rate": rate,
            }
        )
    return rows


def _load_json_file(path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None
    if isinstance(data, dict):
        return data
    return None


def build_diagnostics_router(config: HydraFlowConfig) -> APIRouter:
    """Build the ``/api/diagnostics`` router.

    The returned router exposes nine GET endpoints that read from the
    factory metrics JSONL store and the per-run trace artifact directory.
    """

    router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

    def _load(time_range: str) -> list[dict[str, Any]]:
        return load_metrics(config.factory_metrics_path, time_range=time_range)

    @router.get("/overview")
    def overview(range: str = Query("7d")) -> dict[str, Any]:
        events = _load(range)
        return headline_metrics(events)

    @router.get("/tools")
    def tools(
        range: str = Query("7d"),
        top_n: int = Query(10, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        events = _load(range)
        return [
            {"name": name, "count": count}
            for name, count in aggregate_top_tools(events, top_n=top_n)
        ]

    @router.get("/skills")
    def skills(
        range: str = Query("7d"),
        top_n: int = Query(10, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        events = _load(range)
        return aggregate_top_skills(events, top_n=top_n)

    @router.get("/subagents")
    def subagents(
        range: str = Query("7d"),
        top_n: int = Query(10, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        events = _load(range)
        # aggregate_top_subagents returns list[tuple[str, int]] — currently
        # always [] until per-subagent name attribution lands in the
        # collector. The wrapping below assumes the tuple shape and will
        # need to be revisited if the upstream signature changes.
        return [
            {"name": name, "count": count}
            for name, count in aggregate_top_subagents(events, top_n=top_n)
        ]

    @router.get("/cost-by-phase")
    def cost_by_phase_route(range: str = Query("7d")) -> dict[str, int]:
        events = _load(range)
        return cost_by_phase(events)

    @router.get("/issues")
    def issues(
        range: str = Query("7d"),
        sort: str = Query("tokens"),
    ) -> list[dict[str, Any]]:
        events = _load(range)
        rows = issues_table(events)
        return _sort_issues(rows, sort)

    @router.get("/issue/{issue}/{phase}")
    def issue_phase(issue: int, phase: str) -> list[dict[str, Any]]:
        phase_dir = _safe_traces_subdir(config.data_root, issue, phase)
        if phase_dir is None or not phase_dir.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for run_dir in sorted(phase_dir.iterdir()):
            if not run_dir.is_dir() or not run_dir.name.startswith("run-"):
                continue
            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                continue
            data = _load_json_file(summary_path)
            if data is not None:
                summaries.append(data)
        return summaries

    @router.get("/issue/{issue}/{phase}/{run_id}")
    def issue_phase_run(issue: int, phase: str, run_id: int) -> dict[str, Any]:
        run_dir = _safe_traces_subdir(config.data_root, issue, phase, f"run-{run_id}")
        if run_dir is None or not run_dir.is_dir():
            return {"error": "not found"}
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            return {"error": "not found"}
        summary = _load_json_file(summary_path)
        if summary is None:
            return {"error": "not found"}
        subprocesses: list[dict[str, Any]] = []
        for sub_path in sorted(run_dir.glob("subprocess-*.json")):
            data = _load_json_file(sub_path)
            if data is not None:
                subprocesses.append(data)
        return {"summary": summary, "subprocesses": subprocesses}

    @router.get("/cache")
    def cache(range: str = Query("7d")) -> list[dict[str, Any]]:
        events = _load(range)
        return _cache_hit_rate_buckets(events)

    return router
