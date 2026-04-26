"""Shared cross-issue cost-rollup aggregator (spec §4.11 points 4–5).

Three iterators over the same three sources the issue waterfall uses:
* ``metrics/prompt/inferences.jsonl`` — LLM inferences.
* ``traces/<issue>/<phase>/run-N/subprocess-*.json`` — subprocess traces.
* ``traces/_loops/<slug>/run-*.json`` — loop-subprocess traces.

Five builders that answer the five endpoints in ``_diagnostics_routes.py``:
* ``build_rolling_24h`` — last-24h totals + per-phase + per-loop.
* ``build_top_issues`` — N most expensive issues in window.
* ``build_by_loop``    — per-loop tick / wall-clock share.
* ``build_per_loop_cost`` — machinery-level per-loop dashboard row.
* ``build_cost_by_model`` — cross-loop per-model spend breakdown.

All cost values are re-priced on every call via
``ModelPricing.estimate_cost`` — storage is token counts only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from dashboard_routes._waterfall_builder import _phase_for_source
from model_pricing import ModelPricingTable, load_pricing
from trace_collector import _slug_for_loop

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.dashboard.cost_rollups")


_RANGE_MAP: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}


def _utcnow() -> datetime:
    """Injectable now() for tests."""
    return datetime.now(UTC)


def _parse_range(value: str | None) -> timedelta:
    """Parse a ``range`` query-string value into a ``timedelta``.

    Default is ``7d``. Raises ``ValueError`` on unknown tokens.
    """
    if not value:
        return _RANGE_MAP["7d"]
    if value not in _RANGE_MAP:
        msg = f"unsupported range: {value!r}"
        raise ValueError(msg)
    return _RANGE_MAP[value]


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _empty_model_bucket() -> dict[str, float | int]:
    """Initial bucket shape for per-model cost/token aggregation.

    Used by ``build_per_loop_cost`` (per-loop nested) and
    ``build_cost_by_model`` (cross-loop). Keeping the shape in one
    place prevents schema drift between the two surfaces.
    """
    return {
        "cost_usd": 0.0,
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def iter_priced_inferences(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable,
) -> Iterator[dict[str, Any]]:
    """Stream inference rows in ``[since, until)`` with re-priced cost.

    Yields dicts with the raw row fields plus:
    * ``ts``: parsed ``datetime`` of ``timestamp``.
    * ``cost_usd``: ``float``; ``0.0`` when the pricing table has no entry.
    * ``phase``: canonical phase (via ``_phase_for_source``).
    """
    path = config.data_path("metrics", "prompt", "inferences.jsonl")
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                ts = _parse_iso(rec.get("timestamp"))
                if ts is None or ts < since or ts >= until:
                    continue
                cost = pricing.estimate_cost(
                    str(rec.get("model", "")),
                    input_tokens=int(rec.get("input_tokens", 0) or 0),
                    output_tokens=int(rec.get("output_tokens", 0) or 0),
                    cache_write_tokens=int(
                        rec.get("cache_creation_input_tokens", 0) or 0
                    ),
                    cache_read_tokens=int(rec.get("cache_read_input_tokens", 0) or 0),
                )
                rec["ts"] = ts
                rec["cost_usd"] = round(cost, 6) if cost is not None else 0.0
                rec["phase"] = _phase_for_source(str(rec.get("source", "")))
                yield rec
    except OSError:
        logger.warning("Failed to read inferences.jsonl for rollup", exc_info=True)


def iter_priced_inferences_for_issue(
    config: HydraFlowConfig,
    *,
    issue: int,
    pricing: ModelPricingTable,
) -> Iterator[dict[str, Any]]:
    """Stream priced inference rows for a single issue (wide time window).

    Shares the read+price path with :func:`iter_priced_inferences` so the
    waterfall builder and cross-issue rollups compute cost identically.
    """
    # Use a very wide window so we don't drop rows — the filter is by issue.
    since = datetime(1970, 1, 1, tzinfo=UTC)
    until = datetime(9999, 1, 1, tzinfo=UTC)
    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        if rec.get("issue_number") == issue:
            yield rec


def iter_subprocess_traces(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
) -> Iterator[dict[str, Any]]:
    """Stream subprocess traces (issue-scoped) whose ``started_at`` falls in window."""
    base = config.data_root / "traces"
    if not base.is_dir():
        return
    for path in base.rglob("subprocess-*.json"):
        # Skip the _loops subtree — those are loop-scoped, handled elsewhere.
        if "_loops" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        ts = _parse_iso(data.get("started_at"))
        if ts is None or ts < since or ts >= until:
            continue
        data["ts"] = ts
        yield data


def iter_loop_traces(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
) -> Iterator[dict[str, Any]]:
    """Stream loop-subprocess traces whose ``started_at`` falls in window."""
    base = config.data_root / "traces" / "_loops"
    if not base.is_dir():
        return
    for path in base.rglob("run-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") != "loop":
            continue
        ts = _parse_iso(data.get("started_at"))
        if ts is None or ts < since or ts >= until:
            continue
        data["ts"] = ts
        yield data


def build_rolling_24h(
    config: HydraFlowConfig,
    *,
    pricing: ModelPricingTable | None = None,
) -> dict[str, Any]:
    """Return last-24h totals grouped by phase and loop (§4.11 point 4)."""
    pricing = pricing or load_pricing()
    now = _utcnow()
    since = now - timedelta(hours=24)

    phase_cost: dict[str, float] = defaultdict(float)
    phase_tokens_in: dict[str, int] = defaultdict(int)
    phase_tokens_out: dict[str, int] = defaultdict(int)
    total_cost = 0.0
    total_in = 0
    total_out = 0

    for rec in iter_priced_inferences(config, since=since, until=now, pricing=pricing):
        phase = rec["phase"]
        phase_cost[phase] += rec["cost_usd"]
        phase_tokens_in[phase] += int(rec.get("input_tokens", 0) or 0)
        phase_tokens_out[phase] += int(rec.get("output_tokens", 0) or 0)
        total_cost += rec["cost_usd"]
        total_in += int(rec.get("input_tokens", 0) or 0)
        total_out += int(rec.get("output_tokens", 0) or 0)

    by_phase = [
        {
            "phase": phase,
            "cost_usd": round(phase_cost[phase], 6),
            "tokens_in": phase_tokens_in[phase],
            "tokens_out": phase_tokens_out[phase],
        }
        for phase in sorted(phase_cost.keys())
    ]

    loop_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"ticks": 0, "wall_clock_seconds": 0}
    )
    for tr in iter_loop_traces(config, since=since, until=now):
        name = str(tr.get("loop", "?"))
        loop_stats[name]["ticks"] += 1
        loop_stats[name]["wall_clock_seconds"] += (
            int(tr.get("duration_ms", 0) or 0) // 1000
        )

    by_loop = [{"loop": name, **stats} for name, stats in sorted(loop_stats.items())]

    return {
        "generated_at": now.isoformat(),
        "window_hours": 24,
        "total": {
            "cost_usd": round(total_cost, 6),
            "tokens_in": total_in,
            "tokens_out": total_out,
        },
        "by_phase": by_phase,
        "by_loop": by_loop,
    }


def build_top_issues(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    limit: int = 10,
    pricing: ModelPricingTable | None = None,
) -> list[dict[str, Any]]:
    """Return the top-N most expensive issues in the window, descending by cost."""
    pricing = pricing or load_pricing()
    per_issue_cost: dict[int, float] = defaultdict(float)
    per_issue_secs: dict[int, int] = defaultdict(int)

    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        issue = rec.get("issue_number")
        if not isinstance(issue, int) or issue <= 0:
            continue
        per_issue_cost[issue] += rec["cost_usd"]
        per_issue_secs[issue] += int(float(rec.get("duration_seconds", 0.0) or 0.0))

    rows = [
        {
            "issue": issue,
            "cost_usd": round(per_issue_cost[issue], 6),
            "wall_clock_seconds": per_issue_secs[issue],
        }
        for issue in per_issue_cost
    ]
    rows.sort(key=lambda r: (-r["cost_usd"], r["issue"]))
    return rows[: max(1, int(limit))]


def build_by_loop(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    """Return per-loop tick count + wall-clock share over the window."""
    loop_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"ticks": 0, "wall_clock_seconds": 0}
    )
    for tr in iter_loop_traces(config, since=since, until=until):
        name = str(tr.get("loop", "?"))
        loop_stats[name]["ticks"] += 1
        loop_stats[name]["wall_clock_seconds"] += (
            int(tr.get("duration_ms", 0) or 0) // 1000
        )

    total_ticks = sum(s["ticks"] for s in loop_stats.values()) or 1
    return [
        {
            "loop": name,
            "ticks": stats["ticks"],
            "wall_clock_seconds": stats["wall_clock_seconds"],
            "share_of_ticks": round(stats["ticks"] / total_ticks, 4),
        }
        for name, stats in sorted(loop_stats.items())
    ]


def _tally_worker_events(events: list[Any]) -> dict[str, dict[str, Any]]:
    """Tally ``BACKGROUND_WORKER_STATUS`` events by worker name."""
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "ticks": 0,
            "ticks_errored": 0,
            "issues_filed": 0,
            "issues_closed": 0,
            "escalations": 0,
            "last_tick_at": "",
        }
    )
    for ev in events or []:
        type_val = getattr(ev, "type", None)
        if type_val is None and isinstance(ev, dict):
            type_val = ev.get("type")
        if str(type_val) not in (
            "background_worker_status",
            "BACKGROUND_WORKER_STATUS",
        ):
            continue
        data = getattr(ev, "data", None)
        if data is None and isinstance(ev, dict):
            data = ev.get("data")
        data = data or {}
        worker = str(data.get("worker", ""))
        if not worker:
            continue
        row = out[worker]
        row["ticks"] += 1
        if str(data.get("status", "")).lower() == "error":
            row["ticks_errored"] += 1
        details = data.get("details") or {}
        if isinstance(details, dict):
            row["issues_filed"] += int(details.get("filed", 0) or 0)
            row["issues_closed"] += int(details.get("closed", 0) or 0)
            row["escalations"] += int(details.get("escalated", 0) or 0)
        last = str(data.get("last_run", "")) or str(getattr(ev, "timestamp", "") or "")
        row["last_tick_at"] = max(row["last_tick_at"], last)
    return out


def build_per_loop_cost(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable | None = None,
    event_bus: EventBus | None = None,
) -> list[dict[str, Any]]:
    """Return the machinery-level per-loop dashboard rows (spec §4.11 point 5).

    Per-row fields: loop, cost_usd, tokens_in, tokens_out, llm_calls,
    issues_filed, issues_closed, escalations, ticks, tick_cost_avg_usd,
    wall_clock_seconds, tick_cost_avg_usd_prev_period, model_breakdown.

    ``model_breakdown`` is a dict keyed by model name (or "unknown" for
    records missing the field), with nested {cost_usd, calls, input_tokens,
    output_tokens, cache_read_tokens, cache_write_tokens}.
    """
    pricing = pricing or load_pricing()

    # Attribution from loop-trace temporal overlap with inference rows.
    loop_ticks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tr in iter_loop_traces(config, since=since, until=until):
        loop_ticks[str(tr.get("loop", "?"))].append(tr)

    inferences = list(
        iter_priced_inferences(config, since=since, until=until, pricing=pricing)
    )

    per_loop_cost: dict[str, float] = defaultdict(float)
    per_loop_tokens_in: dict[str, int] = defaultdict(int)
    per_loop_tokens_out: dict[str, int] = defaultdict(int)
    per_loop_llm_calls: dict[str, int] = defaultdict(int)
    per_loop_wall: dict[str, int] = defaultdict(int)
    per_loop_model: dict[str, dict[str, dict[str, float | int]]] = defaultdict(
        lambda: defaultdict(_empty_model_bucket)
    )

    for name, ticks in loop_ticks.items():
        for tick in ticks:
            per_loop_wall[name] += int(tick.get("duration_ms", 0) or 0) // 1000
            started = tick["ts"]
            ended = started + timedelta(
                milliseconds=int(tick.get("duration_ms", 0) or 0)
            )
            for rec in inferences:
                if started <= rec["ts"] <= ended:
                    per_loop_cost[name] += rec["cost_usd"]
                    per_loop_tokens_in[name] += int(rec.get("input_tokens", 0) or 0)
                    per_loop_tokens_out[name] += int(rec.get("output_tokens", 0) or 0)
                    per_loop_llm_calls[name] += 1
                    model_key = str(rec.get("model") or "").strip() or "unknown"
                    bucket = per_loop_model[name][model_key]
                    bucket["cost_usd"] += float(rec["cost_usd"])
                    bucket["calls"] += 1
                    bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
                    bucket["output_tokens"] += int(rec.get("output_tokens", 0) or 0)
                    bucket["cache_read_tokens"] += int(
                        rec.get("cache_read_input_tokens", 0) or 0
                    )
                    bucket["cache_write_tokens"] += int(
                        rec.get("cache_creation_input_tokens", 0) or 0
                    )

    # Event-based counters (filed / closed / escalations / errored ticks).
    worker_stats: dict[str, dict[str, Any]] = {}
    if event_bus is not None:
        try:
            events = asyncio.run(event_bus.load_events_since(since))
        except RuntimeError:
            # Called from an already-running event loop — fall back.
            logger.debug("build_per_loop_cost: nested event loop; skipping events")
            events = []
        worker_stats = _tally_worker_events(events or [])

    # Prior-period loop-tick counts (rough signal for > 2× highlight).
    prev_until = since
    prev_since = since - (until - since)
    prev_loop_ticks: dict[str, int] = defaultdict(int)
    for tr in iter_loop_traces(config, since=prev_since, until=prev_until):
        prev_loop_ticks[str(tr.get("loop", "?"))] += 1
    prev_loop_cost: dict[str, float] = defaultdict(float)

    # Combine trace + event names. Trace names are ClassName (e.g.
    # "RCBudgetLoop"); event names are worker_name (e.g. "rc_budget").
    # Normalise to worker_name for the final output.
    name_set: set[str] = set()
    for name in loop_ticks:
        name_set.add(_slug_for_loop(name))
    name_set.update(worker_stats.keys())

    rows: list[dict[str, Any]] = []
    for worker in sorted(name_set):
        class_name = next(
            (n for n in loop_ticks if _slug_for_loop(n) == worker),
            worker,
        )
        stats = worker_stats.get(worker, {})
        ticks = int(stats.get("ticks", 0) or len(loop_ticks.get(class_name, [])))
        cost = per_loop_cost.get(class_name, 0.0)
        avg_cost = round(cost / ticks, 6) if ticks else 0.0
        prev_ticks = prev_loop_ticks.get(class_name, 0)
        prev_cost = prev_loop_cost.get(class_name, 0.0)
        prev_avg = round(prev_cost / prev_ticks, 6) if prev_ticks else 0.0
        breakdown_raw = per_loop_model.get(class_name, {})
        model_breakdown = {
            model: {
                "cost_usd": round(float(b["cost_usd"]), 6),
                "calls": int(b["calls"]),
                "input_tokens": int(b["input_tokens"]),
                "output_tokens": int(b["output_tokens"]),
                "cache_read_tokens": int(b["cache_read_tokens"]),
                "cache_write_tokens": int(b["cache_write_tokens"]),
            }
            for model, b in breakdown_raw.items()
        }
        rows.append(
            {
                "loop": worker,
                "cost_usd": round(cost, 6),
                "tokens_in": per_loop_tokens_in.get(class_name, 0),
                "tokens_out": per_loop_tokens_out.get(class_name, 0),
                "llm_calls": per_loop_llm_calls.get(class_name, 0),
                "issues_filed": int(stats.get("issues_filed", 0) or 0),
                "issues_closed": int(stats.get("issues_closed", 0) or 0),
                "escalations": int(stats.get("escalations", 0) or 0),
                "ticks": ticks,
                "ticks_errored": int(stats.get("ticks_errored", 0) or 0),
                "tick_cost_avg_usd": avg_cost,
                "wall_clock_seconds": per_loop_wall.get(class_name, 0),
                "last_tick_at": stats.get("last_tick_at", "") or None,
                "tick_cost_avg_usd_prev_period": prev_avg,
                "model_breakdown": model_breakdown,
            }
        )
    return rows


def build_cost_by_model(
    config: HydraFlowConfig,
    *,
    since: datetime,
    until: datetime,
    pricing: ModelPricingTable | None = None,
) -> list[dict[str, Any]]:
    """Return cross-loop cost broken out by model in ``[since, until)``.

    Each row: ``{model, cost_usd, calls, input_tokens, output_tokens,
    cache_read_tokens, cache_write_tokens}``. Sorted descending by
    ``cost_usd``; ties broken alphabetically by model name for deterministic
    output. Records with empty/missing ``model`` bucket under the
    literal string ``"unknown"``. Unpriced models surface their token
    counts with ``cost_usd == 0.0``.
    """
    pricing = pricing or load_pricing()

    by_model: dict[str, dict[str, float | int]] = defaultdict(_empty_model_bucket)

    for rec in iter_priced_inferences(
        config, since=since, until=until, pricing=pricing
    ):
        model_key = str(rec.get("model") or "").strip() or "unknown"
        bucket = by_model[model_key]
        bucket["cost_usd"] += rec["cost_usd"]
        bucket["calls"] += 1
        bucket["input_tokens"] += int(rec.get("input_tokens", 0) or 0)
        bucket["output_tokens"] += int(rec.get("output_tokens", 0) or 0)
        bucket["cache_read_tokens"] += int(rec.get("cache_read_input_tokens", 0) or 0)
        bucket["cache_write_tokens"] += int(
            rec.get("cache_creation_input_tokens", 0) or 0
        )

    rows = [
        {
            "model": model,
            "cost_usd": round(float(b["cost_usd"]), 6),
            "calls": int(b["calls"]),
            "input_tokens": int(b["input_tokens"]),
            "output_tokens": int(b["output_tokens"]),
            "cache_read_tokens": int(b["cache_read_tokens"]),
            "cache_write_tokens": int(b["cache_write_tokens"]),
        }
        for model, b in by_model.items()
    ]
    rows.sort(key=lambda r: (-r["cost_usd"], r["model"]))
    return rows
