"""Parse Monocle trace JSON files into structured TraceSummary models."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from models import (
    TraceSkillProfile,
    TraceSpanStats,
    TraceSummary,
    TraceTokenStats,
    TraceToolProfile,
)

logger = logging.getLogger("hydraflow.trace_parser")


def parse_traces(trace_dir: Path, *, issue_number: int, phase: str) -> TraceSummary:
    """Parse all raw trace files in *trace_dir*/raw/ into a TraceSummary."""
    raw_dir = trace_dir / "raw"
    if not raw_dir.is_dir():
        return _empty_summary(issue_number, phase)

    all_spans: list[dict] = []
    trace_ids: set[str] = set()

    for path in sorted(raw_dir.glob("*.json")):
        try:
            spans = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Skipping malformed trace file: %s", path)
            continue
        if isinstance(spans, list):
            all_spans.extend(spans)
            for span in spans:
                # Collect trace IDs only from root workflow spans to avoid
                # picking up IDs from child spans that belong to a different file's trace.
                if span.get("attributes", {}).get("span.type") == "workflow":
                    tid = span.get("context", {}).get("trace_id")
                    if tid:
                        trace_ids.add(tid)

    if not all_spans:
        return _empty_summary(issue_number, phase)

    return _build_summary(all_spans, trace_ids, issue_number, phase)


def _build_summary(
    spans: list[dict],
    trace_ids: set[str],
    issue_number: int,
    phase: str,
) -> TraceSummary:
    total_turns = 0
    total_inference = 0
    duration_seconds = 0.0

    prompt_tokens = 0
    completion_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0

    tool_counts: dict[str, int] = {}
    tool_errors: dict[str, int] = {}
    skill_counts: dict[str, int] = {}
    subagent_counts: dict[str, int] = {}

    for span in spans:
        attrs = span.get("attributes", {})
        span_type = attrs.get("span.type", "")

        if span_type == "agentic.turn":
            total_turns += 1

        elif span_type == "inference":
            total_inference += 1
            for event in span.get("events", []):
                if event.get("name") == "metadata":
                    meta = event.get("attributes", {})
                    prompt_tokens += meta.get("prompt_tokens", 0)
                    completion_tokens += meta.get("completion_tokens", 0)
                    cache_read_tokens += meta.get("cache_read_tokens", 0)
                    cache_creation_tokens += meta.get("cache_creation_tokens", 0)

        elif span_type == "agentic.tool.invocation":
            tool_name = attrs.get("entity.1.name", "unknown")
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            status = span.get("status", {}).get("status_code", "OK")
            if status == "ERROR":
                tool_errors[tool_name] = tool_errors.get(tool_name, 0) + 1

            if tool_name == "Skill":
                _extract_skill(span, skill_counts)
            elif tool_name == "Agent":
                _extract_subagent(span, subagent_counts)

        elif span_type == "workflow":
            duration_seconds = _compute_duration(span)

    total_prompt_and_cache = prompt_tokens + cache_read_tokens
    cache_hit_rate = (
        cache_read_tokens / total_prompt_and_cache
        if total_prompt_and_cache > 0
        else 0.0
    )

    total_invocations = sum(tool_counts.values())
    total_skills = sum(skill_counts.values())
    total_subagents = sum(subagent_counts.values())

    return TraceSummary(
        issue_number=issue_number,
        phase=phase,
        harvested_at=datetime.now(UTC).isoformat(),
        trace_ids=sorted(trace_ids),
        spans=TraceSpanStats(
            total_spans=len(spans),
            total_turns=total_turns,
            total_inference_calls=total_inference,
            duration_seconds=duration_seconds,
        ),
        tokens=TraceTokenStats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_hit_rate=round(cache_hit_rate, 4),
        ),
        tools=TraceToolProfile(
            tool_counts=tool_counts,
            tool_errors=tool_errors,
            total_invocations=total_invocations,
        ),
        skills=TraceSkillProfile(
            skill_counts=skill_counts,
            subagent_counts=subagent_counts,
            total_skills=total_skills,
            total_subagents=total_subagents,
        ),
    )


def _extract_skill(span: dict, skill_counts: dict[str, int]) -> None:
    """Extract skill name from a Skill tool invocation span."""
    for event in span.get("events", []):
        if event.get("name") == "data.input":
            raw = event.get("attributes", {}).get("input", "")
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                name = data.get("skill", "")
                if name:
                    skill_counts[name] = skill_counts.get(name, 0) + 1
            except (json.JSONDecodeError, AttributeError):
                pass
            return


def _extract_subagent(span: dict, subagent_counts: dict[str, int]) -> None:
    """Extract subagent_type from an Agent tool invocation span."""
    for event in span.get("events", []):
        if event.get("name") == "data.input":
            raw = event.get("attributes", {}).get("input", "")
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                agent_type = data.get("subagent_type", "")
                if agent_type:
                    subagent_counts[agent_type] = subagent_counts.get(agent_type, 0) + 1
            except (json.JSONDecodeError, AttributeError):
                pass
            return


def _compute_duration(span: dict) -> float:
    """Compute duration in seconds from workflow span timestamps."""
    try:
        start = datetime.fromisoformat(span["start_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(span["end_time"].replace("Z", "+00:00"))
        return (end - start).total_seconds()
    except (KeyError, ValueError):
        return 0.0


def _empty_summary(issue_number: int, phase: str) -> TraceSummary:
    return TraceSummary(
        issue_number=issue_number,
        phase=phase,
        harvested_at=datetime.now(UTC).isoformat(),
        trace_ids=[],
        spans=TraceSpanStats(
            total_spans=0, total_turns=0, total_inference_calls=0, duration_seconds=0.0
        ),
        tokens=TraceTokenStats(
            prompt_tokens=0,
            completion_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        ),
        tools=TraceToolProfile(tool_counts={}, tool_errors={}, total_invocations=0),
        skills=TraceSkillProfile(
            skill_counts={}, subagent_counts={}, total_skills=0, total_subagents=0
        ),
    )
