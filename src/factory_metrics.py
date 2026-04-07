"""Factory metrics — read, filter, and aggregate factory_metrics.jsonl events.

Reads the time-series store at ``<data_root>/diagnostics/factory_metrics.jsonl``
written by the in-process tracing collector. Exposes aggregation helpers for
the Diagnostics dashboard.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("hydraflow.factory_metrics")


_TIME_RANGE_DELTAS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_metrics(
    path: Path,
    *,
    time_range: str | None = None,
    repo: str | None = None,
) -> list[dict[str, Any]]:
    """Load factory metrics events from a JSONL file.

    Args:
        path: Path to the ``factory_metrics.jsonl`` file.
        time_range: One of ``"24h"``, ``"7d"``, ``"30d"``, ``"all"``, or
            ``None``. When supplied (and not ``"all"``/``None``), events with
            a timestamp older than ``now - delta`` are dropped. Events with
            unparseable timestamps are retained.
        repo: Reserved for future multi-repo support. When set, only events
            whose ``repo`` field matches are returned.

    Returns:
        A list of event dicts. Empty if the file is missing. Malformed JSON
        lines are skipped with a warning.
    """

    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Skipping malformed factory_metrics line %d in %s: %s",
                        lineno,
                        path,
                        exc,
                    )
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError as exc:
        logger.warning("Failed to read factory_metrics file %s: %s", path, exc)
        return []

    if repo is not None:
        events = [e for e in events if e.get("repo") == repo]

    if time_range and time_range != "all":
        delta = _TIME_RANGE_DELTAS.get(time_range)
        if delta is not None:
            cutoff = datetime.now(UTC) - delta
            filtered: list[dict[str, Any]] = []
            for event in events:
                ts = _parse_timestamp(event.get("timestamp"))
                if ts is None:
                    # Keep unparseable timestamps rather than silently dropping.
                    filtered.append(event)
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts >= cutoff:
                    filtered.append(event)
            events = filtered
        else:
            logger.warning("Unknown time_range %r; returning all events", time_range)

    return events


def _event_tokens_total(event: dict[str, Any]) -> int:
    tokens = event.get("tokens") or {}
    if not isinstance(tokens, dict):
        return 0
    total = 0
    for key in ("input", "output", "cache_read", "cache_creation"):
        value = tokens.get(key, 0)
        if isinstance(value, int | float):
            total += int(value)
    return total


def headline_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return top-line aggregates across all supplied events.

    Keys:
        total_tokens: Sum of ``input + output + cache_read + cache_creation``
            across every event.
        total_runs: Number of events.
        total_tool_invocations: Sum of every tool count in ``event["tools"]``.
        total_subagents: Sum of ``event["subagents"]`` (integer total; names
            are not yet recorded upstream).
        cache_hit_rate: ``cache_read / (input + cache_read)`` rounded to 4
            decimal places. ``0.0`` when ``input + cache_read`` is zero.
    """

    total_tokens = 0
    total_tool_invocations = 0
    total_subagents = 0
    total_input = 0
    total_cache_read = 0

    for event in events:
        total_tokens += _event_tokens_total(event)

        tools = event.get("tools") or {}
        if isinstance(tools, dict):
            for value in tools.values():
                if isinstance(value, int | float):
                    total_tool_invocations += int(value)

        subagents = event.get("subagents", 0)
        if isinstance(subagents, int | float):
            total_subagents += int(subagents)

        tokens = event.get("tokens") or {}
        if isinstance(tokens, dict):
            input_value = tokens.get("input", 0)
            cache_read_value = tokens.get("cache_read", 0)
            if isinstance(input_value, int | float):
                total_input += int(input_value)
            if isinstance(cache_read_value, int | float):
                total_cache_read += int(cache_read_value)

    denom = total_input + total_cache_read
    cache_hit_rate = round(total_cache_read / denom, 4) if denom > 0 else 0.0

    return {
        "total_tokens": total_tokens,
        "total_runs": len(events),
        "total_tool_invocations": total_tool_invocations,
        "total_subagents": total_subagents,
        "cache_hit_rate": cache_hit_rate,
    }


def aggregate_top_tools(
    events: list[dict[str, Any]],
    top_n: int = 10,
) -> list[tuple[str, int]]:
    """Return the ``top_n`` most frequent tools across events."""

    counter: Counter[str] = Counter()
    for event in events:
        tools = event.get("tools") or {}
        if not isinstance(tools, dict):
            continue
        for name, value in tools.items():
            if isinstance(name, str) and isinstance(value, int | float):
                counter[name] += int(value)
    return counter.most_common(top_n)


def aggregate_top_skills(
    events: list[dict[str, Any]],
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """Return the ``top_n`` most-invoked skills with first-try pass rates.

    A skill invocation "passed on first try" when its entry has
    ``attempts == 1`` and ``passed is True``. The returned list is ordered by
    total invocation count (descending).
    """

    totals: Counter[str] = Counter()
    first_try_passes: Counter[str] = Counter()

    for event in events:
        skills = event.get("skills") or []
        if not isinstance(skills, list):
            continue
        for entry in skills:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            totals[name] += 1
            if entry.get("attempts") == 1 and entry.get("passed") is True:
                first_try_passes[name] += 1

    result: list[dict[str, Any]] = []
    for name, count in totals.most_common(top_n):
        pass_rate = round(first_try_passes[name] / count, 4) if count else 0.0
        result.append(
            {
                "name": name,
                "count": count,
                "first_try_pass_rate": pass_rate,
            }
        )
    return result


def aggregate_top_subagents(
    events: list[dict[str, Any]],
    top_n: int = 10,
) -> list[tuple[str, int]]:
    """Return the top-N invoked subagents by name.

    Currently returns ``[]`` because the factory_metrics event records
    subagents only as an integer total (derived from ``tools["Task"]``) and
    does not carry per-subagent names. This function is a placeholder until
    the upstream collector starts recording named subagent invocations.
    """

    del events, top_n  # unused until subagent names are recorded upstream
    return []


def cost_by_phase(events: list[dict[str, Any]]) -> dict[str, int]:
    """Return total token usage grouped by phase name."""

    by_phase: dict[str, int] = {}
    for event in events:
        phase = event.get("phase")
        if not isinstance(phase, str):
            continue
        by_phase[phase] = by_phase.get(phase, 0) + _event_tokens_total(event)
    return by_phase


def issues_table(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one row per event suitable for a per-issue detail table."""

    rows: list[dict[str, Any]] = []
    for event in events:
        tools = event.get("tools") or {}
        tool_count = 0
        if isinstance(tools, dict):
            for value in tools.values():
                if isinstance(value, int | float):
                    tool_count += int(value)

        skills = event.get("skills") or []
        skill_total = 0
        skill_pass_count = 0
        if isinstance(skills, list):
            for entry in skills:
                if not isinstance(entry, dict):
                    continue
                skill_total += 1
                if entry.get("passed") is True:
                    skill_pass_count += 1

        rows.append(
            {
                "issue": event.get("issue"),
                "phase": event.get("phase"),
                "run_id": event.get("run_id"),
                "tokens": _event_tokens_total(event),
                "tool_count": tool_count,
                "skill_pass_count": skill_pass_count,
                "skill_total": skill_total,
                "duration_seconds": event.get("duration_seconds"),
                "crashed": event.get("crashed"),
                "timestamp": event.get("timestamp"),
            }
        )
    return rows
