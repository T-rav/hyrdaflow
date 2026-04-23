"""Issue-level cost waterfall aggregator (spec §4.11 point 1).

Reads ``<data_root>/traces/<issue>/<phase>/run-N/subprocess-*.json`` and
``<data_root>/metrics/prompt/inferences.jsonl``, groups actions by canonical
phase, orders chronologically, and computes cost on the fly via
``ModelPricing.estimate_cost`` so pricing-sheet updates retroactively
re-price historical issues.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from model_pricing import ModelPricingTable, load_pricing
from tracing_context import source_to_phase

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.dashboard.waterfall")

PHASE_ORDER: tuple[str, ...] = (
    "triage",
    "discover",
    "shape",
    "plan",
    "implement",
    "review",
    "merge",
)

# Off-pipeline sources that fold into a canonical phase for the waterfall.
_OFFPIPELINE_FOLD: dict[str, str] = {
    "hitl": "review",
    "find": "triage",
}


def _phase_for_source(source: str) -> str:
    """Map a runner source to a canonical waterfall phase."""
    canonical = source_to_phase(source)
    return _OFFPIPELINE_FOLD.get(canonical, canonical)


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


def _load_inferences_for_issue(
    config: HydraFlowConfig,
    issue: int,
    pricing: ModelPricingTable | None = None,
) -> list[dict[str, Any]]:
    """Load per-issue inference rows via the shared cross-issue aggregator.

    Routes through ``_cost_rollups.iter_priced_inferences_for_issue`` so
    there's exactly one read+price path; the rows come back with ``cost_usd``
    and ``phase`` already filled in. ``_action_llm`` below prefers the row's
    ``cost_usd`` when present, so callers that pass ``pricing=None`` still
    get identical behaviour to the pre-refactor path.
    """
    # Lazy import — ``_cost_rollups`` imports ``_phase_for_source`` from this
    # module, so we defer the import to break the cycle.
    from dashboard_routes._cost_rollups import (  # noqa: PLC0415
        iter_priced_inferences_for_issue,
    )

    pricing = pricing or load_pricing()
    try:
        return list(
            iter_priced_inferences_for_issue(config, issue=issue, pricing=pricing)
        )
    except OSError:
        logger.warning("Failed to read inferences for waterfall", exc_info=True)
        return []


def _load_subprocess_traces(
    config: HydraFlowConfig, issue: int
) -> list[dict[str, Any]]:
    base = config.data_root / "traces" / str(issue)
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for sub_path in base.rglob("subprocess-*.json"):
        try:
            data = json.loads(sub_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _load_loop_traces_in_window(
    config: HydraFlowConfig,
    first_seen: datetime | None,
    merged_at: datetime | None,
) -> list[dict[str, Any]]:
    if first_seen is None:
        return []
    base = config.data_root / "traces" / "_loops"
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    upper = merged_at or datetime.now(UTC)
    for run_path in base.rglob("run-*.json"):
        try:
            data = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") != "loop":
            continue
        started = _parse_iso(data.get("started_at"))
        if started is None:
            continue
        if first_seen <= started <= upper:
            out.append(data)
    return out


def _action_llm(rec: dict[str, Any], pricing: ModelPricingTable) -> dict[str, Any]:
    """Build an LLM action dict from a priced or unpriced inference row.

    If ``rec`` already has a ``cost_usd`` key (as produced by
    ``_cost_rollups.iter_priced_inferences``), use it directly. Otherwise
    compute cost via the supplied ``pricing`` table. This lets callers
    share a single priced-row stream with the cross-issue aggregator
    without forcing a second pricing lookup.
    """
    input_tokens = int(rec.get("input_tokens", 0) or 0)
    output_tokens = int(rec.get("output_tokens", 0) or 0)
    cache_write = int(rec.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(rec.get("cache_read_input_tokens", 0) or 0)
    model = str(rec.get("model", ""))
    if "cost_usd" in rec:
        cost_usd = float(rec.get("cost_usd", 0.0) or 0.0)
    else:
        cost = pricing.estimate_cost(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
        )
        cost_usd = round(cost, 6) if cost is not None else 0.0
    return {
        "kind": "llm",
        "model": model,
        "started_at": str(rec.get("timestamp", "")),
        "tokens_in": input_tokens,
        "tokens_out": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "duration_ms": int(float(rec.get("duration_seconds", 0.0)) * 1000),
        "cost_usd": cost_usd,
    }


def _action_skill(skill: dict[str, Any], trace_started_at: str) -> dict[str, Any]:
    return {
        "kind": "skill",
        "skill": str(skill.get("skill_name", "?")),
        "started_at": trace_started_at,
        "duration_ms": int(float(skill.get("duration_seconds", 0.0)) * 1000),
        "passed": bool(skill.get("passed", False)),
        "blocking": bool(skill.get("blocking", False)),
    }


def _action_subprocess(tc: dict[str, Any]) -> dict[str, Any] | None:
    if tc.get("tool_name") != "Bash":
        return None
    return {
        "kind": "subprocess",
        "command": str(tc.get("input_summary", ""))[:500],
        "started_at": str(tc.get("started_at", "")),
        "duration_ms": int(tc.get("duration_ms", 0) or 0),
        "succeeded": bool(tc.get("succeeded", False)),
    }


def _action_loop(data: dict[str, Any]) -> dict[str, Any]:
    cmd = data.get("command", [])
    cmd_str = " ".join(str(x) for x in cmd) if isinstance(cmd, list) else str(cmd)
    return {
        "kind": "loop",
        "loop": str(data.get("loop", "?")),
        "started_at": str(data.get("started_at", "")),
        "command": cmd_str[:500],
        "duration_ms": int(data.get("duration_ms", 0) or 0),
        "exit_code": int(data.get("exit_code", 0) or 0),
    }


def _phase_for_loop_time(
    started: datetime,
    phase_windows: dict[str, tuple[datetime, datetime]],
) -> str:
    """Return canonical phase whose window contains ``started``; fallback 'implement'."""
    for phase in PHASE_ORDER:
        win = phase_windows.get(phase)
        if win is None:
            continue
        lo, hi = win
        if lo <= started <= hi:
            return phase
    return "implement"


def _empty_phase_rollup(phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "wall_clock_seconds": 0,
        "actions": [],
    }


def build_waterfall(
    config: HydraFlowConfig,
    *,
    issue: int,
    issue_meta: dict[str, Any],
    pricing: ModelPricingTable | None = None,
) -> dict[str, Any]:
    """Build the issue cost waterfall payload (spec §4.11 point 1).

    Args:
        config: HydraFlowConfig (for ``data_root`` / ``data_path``).
        issue: Issue number.
        issue_meta: Pre-fetched issue metadata dict with ``number``,
            ``title``, ``labels``, and optionally ``first_seen`` /
            ``merged_at`` ISO timestamps.
        pricing: Optional pre-loaded pricing table. Tests inject mocks.

    Returns:
        Waterfall payload matching spec §4.11 point 1 shape. Phases
        that produced zero telemetry are listed in ``missing_phases``
        and omitted from ``phases``.
    """
    pricing = pricing or load_pricing()
    first_seen = _parse_iso(issue_meta.get("first_seen"))
    merged_at = _parse_iso(issue_meta.get("merged_at"))

    inferences = _load_inferences_for_issue(config, issue, pricing=pricing)
    traces = _load_subprocess_traces(config, issue)
    loop_traces = _load_loop_traces_in_window(config, first_seen, merged_at)

    # Group actions by canonical phase.
    per_phase_actions: dict[str, list[dict[str, Any]]] = {p: [] for p in PHASE_ORDER}

    # Phase windows (started_at..ended_at) for loop-trace attribution.
    phase_windows: dict[str, tuple[datetime, datetime]] = {}

    for rec in inferences:
        phase = _phase_for_source(str(rec.get("source", "")))
        if phase not in per_phase_actions:
            per_phase_actions[phase] = []
        per_phase_actions[phase].append(_action_llm(rec, pricing))

    for tr in traces:
        phase = _phase_for_source(str(tr.get("source", tr.get("phase", ""))))
        if phase not in per_phase_actions:
            per_phase_actions[phase] = []
        started = _parse_iso(tr.get("started_at"))
        ended = _parse_iso(tr.get("ended_at")) or started
        if started and ended:
            lo, hi = phase_windows.get(phase, (started, ended))
            phase_windows[phase] = (min(lo, started), max(hi, ended))

        for skill in tr.get("skill_results", []) or []:
            if isinstance(skill, dict):
                per_phase_actions[phase].append(
                    _action_skill(skill, str(tr.get("started_at", "")))
                )
        for tc in tr.get("tool_calls", []) or []:
            if isinstance(tc, dict):
                act = _action_subprocess(tc)
                if act is not None:
                    per_phase_actions[phase].append(act)

    for loop in loop_traces:
        started = _parse_iso(loop.get("started_at"))
        if started is None:
            continue
        phase = _phase_for_loop_time(started, phase_windows)
        per_phase_actions.setdefault(phase, []).append(_action_loop(loop))

    # Build phase rollups in canonical order; flag missing phases.
    phases_out: list[dict[str, Any]] = []
    missing: list[str] = []
    total_in = total_out = total_cache_r = total_cache_w = 0
    total_cost = 0.0

    for phase in PHASE_ORDER:
        actions = per_phase_actions.get(phase, [])
        if not actions:
            missing.append(phase)
            continue
        actions.sort(key=lambda a: (a.get("started_at") or "", a.get("kind", "")))
        rollup = _empty_phase_rollup(phase)
        rollup["actions"] = actions
        for a in actions:
            rollup["tokens_in"] += int(a.get("tokens_in", 0) or 0)
            rollup["tokens_out"] += int(a.get("tokens_out", 0) or 0)
            rollup["cache_read_tokens"] += int(a.get("cache_read_tokens", 0) or 0)
            rollup["cache_write_tokens"] += int(a.get("cache_write_tokens", 0) or 0)
            rollup["cost_usd"] += float(a.get("cost_usd", 0.0) or 0.0)
        win = phase_windows.get(phase)
        if win is not None:
            rollup["wall_clock_seconds"] = max(
                0, int((win[1] - win[0]).total_seconds())
            )
        rollup["cost_usd"] = round(rollup["cost_usd"], 6)
        phases_out.append(rollup)

        total_in += rollup["tokens_in"]
        total_out += rollup["tokens_out"]
        total_cache_r += rollup["cache_read_tokens"]
        total_cache_w += rollup["cache_write_tokens"]
        total_cost += rollup["cost_usd"]

    wall = 0
    if first_seen and merged_at:
        wall = max(0, int((merged_at - first_seen).total_seconds()))

    return {
        "issue": issue,
        "title": str(issue_meta.get("title", "")),
        "labels": list(issue_meta.get("labels", []) or []),
        "total": {
            "tokens_in": total_in,
            "tokens_out": total_out,
            "cache_read_tokens": total_cache_r,
            "cache_write_tokens": total_cache_w,
            "cost_usd": round(total_cost, 6),
            "wall_clock_seconds": wall,
            "first_seen": first_seen.isoformat() if first_seen else None,
            "merged_at": merged_at.isoformat() if merged_at else None,
        },
        "phases": phases_out,
        "missing_phases": missing,
    }
