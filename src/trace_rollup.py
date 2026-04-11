"""Aggregate per-subprocess trace files into a per-phase-run TraceSummary."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from models import (
    SubprocessTrace,
    TraceSkillProfile,
    TraceSpanStats,
    TraceSummary,
    TraceTokenStats,
    TraceToolProfile,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.trace_rollup")


def write_phase_rollup(
    *,
    config: HydraFlowConfig,
    issue_number: int,
    phase: str,
    run_id: int,
) -> TraceSummary | None:
    """Aggregate all subprocess-*.json files in run-N/ into summary.json.

    Idempotent. Updates the ``latest`` pointer file at the phase
    directory level. Returns the TraceSummary or None if no
    subprocess files exist.
    """
    run_dir = config.data_root / "traces" / str(issue_number) / phase / f"run-{run_id}"
    if not run_dir.is_dir():
        return None

    subprocess_files = sorted(run_dir.glob("subprocess-*.json"))
    if not subprocess_files:
        return None

    traces: list[SubprocessTrace] = []
    for path in subprocess_files:
        try:
            traces.append(
                SubprocessTrace.model_validate_json(path.read_text(encoding="utf-8"))
            )
        except Exception:
            logger.warning("Skipping malformed subprocess trace: %s", path)

    if not traces:
        return None

    # Also read skill_results.json if the agent._run_skill hook wrote one.
    skill_results: list[dict] = []
    skill_results_path = run_dir / "skill_results.json"
    if skill_results_path.exists():
        try:
            import json  # noqa: PLC0415

            loaded = json.loads(skill_results_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                skill_results = loaded
        except Exception:
            logger.warning("Failed to read %s", skill_results_path, exc_info=True)

    summary = _aggregate(
        traces,
        issue_number=issue_number,
        phase=phase,
        run_id=run_id,
        skill_results=skill_results,
    )

    summary_path = run_dir / "summary.json"
    summary_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")

    # Update the latest pointer atomically (temp write + replace)
    latest_path = run_dir.parent / "latest"
    latest_tmp = run_dir.parent / "latest.tmp"
    latest_tmp.write_text(f"run-{run_id}\n", encoding="utf-8")
    try:
        latest_tmp.replace(latest_path)
    except OSError:
        latest_tmp.unlink(missing_ok=True)
        raise

    # Append to factory_metrics.jsonl for the diagnostics dashboard
    try:
        _append_factory_metric(config, summary, traces, skill_results)
    except Exception:
        logger.warning("Failed to append factory metric", exc_info=True)

    return summary


def _aggregate(
    traces: list[SubprocessTrace],
    *,
    issue_number: int,
    phase: str,
    run_id: int,
    skill_results: list[dict] | None = None,
) -> TraceSummary:
    prompt_total = sum(t.tokens.prompt_tokens for t in traces)
    completion_total = sum(t.tokens.completion_tokens for t in traces)
    cache_read_total = sum(t.tokens.cache_read_tokens for t in traces)
    cache_creation_total = sum(t.tokens.cache_creation_tokens for t in traces)
    cache_input_total = prompt_total + cache_read_total
    cache_hit_rate = (
        cache_read_total / cache_input_total if cache_input_total > 0 else 0.0
    )

    tool_counts: dict[str, int] = {}
    tool_errors: dict[str, int] = {}
    for t in traces:
        for tool, cnt in t.tools.tool_counts.items():
            tool_counts[tool] = tool_counts.get(tool, 0) + cnt
        for tool, cnt in t.tools.tool_errors.items():
            tool_errors[tool] = tool_errors.get(tool, 0) + cnt

    skill_counts: dict[str, int] = {}
    for t in traces:
        for sr in t.skill_results:
            skill_counts[sr.skill_name] = skill_counts.get(sr.skill_name, 0) + 1
    # Merge in skill results from skill_results.json (written by agent._run_skill)
    for sr_dict in skill_results or []:
        name = str(sr_dict.get("skill_name", "unknown"))
        skill_counts[name] = skill_counts.get(name, 0) + 1
    total_skills = sum(skill_counts.values())

    inference_total = sum(t.inference_count for t in traces)
    turn_total = sum(t.turn_count for t in traces)

    started_ats = sorted(t.started_at for t in traces if t.started_at)
    ended_ats = sorted(
        (t.ended_at or t.started_at) for t in traces if (t.ended_at or t.started_at)
    )
    started_at = started_ats[0] if started_ats else ""
    ended_at = ended_ats[-1] if ended_ats else ""
    duration_seconds = _duration_seconds(started_at, ended_at)

    crashed = any(t.crashed for t in traces)

    return TraceSummary(
        issue_number=issue_number,
        phase=phase,
        harvested_at=datetime.now(UTC).isoformat(),
        trace_ids=[],
        spans=TraceSpanStats(
            total_spans=sum(len(t.tool_calls) for t in traces) + inference_total,
            total_turns=turn_total,
            total_inference_calls=inference_total,
            duration_seconds=duration_seconds,
        ),
        tokens=TraceTokenStats(
            prompt_tokens=prompt_total,
            completion_tokens=completion_total,
            cache_read_tokens=cache_read_total,
            cache_creation_tokens=cache_creation_total,
            cache_hit_rate=round(cache_hit_rate, 4),
        ),
        tools=TraceToolProfile(
            tool_counts=tool_counts,
            tool_errors=tool_errors,
            total_invocations=sum(tool_counts.values()),
        ),
        skills=TraceSkillProfile(
            skill_counts=skill_counts,
            subagent_counts={},  # subagent tracking lives in tool_counts as "Task" tool
            total_skills=total_skills,
            total_subagents=tool_counts.get("Task", 0),
        ),
        run_id=run_id,
        subprocess_count=len(traces),
        crashed=crashed,
        phase_run_started_at=started_at,
        phase_run_ended_at=ended_at,
    )


def _duration_seconds(started_at: str, ended_at: str) -> float:
    if not started_at or not ended_at:
        return 0.0
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        return max(0.0, (end - start).total_seconds())
    except (ValueError, TypeError):
        return 0.0


def _append_factory_metric(
    config: HydraFlowConfig,
    summary: TraceSummary,
    traces: list[SubprocessTrace],
    external_skill_results: list[dict],
) -> None:
    """Append one event to factory_metrics.jsonl describing this phase run."""
    import json  # noqa: PLC0415

    metrics_path = config.factory_metrics_path
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    skill_entries: list[dict] = []
    for t in traces:
        for sr in t.skill_results:
            skill_entries.append(
                {"name": sr.skill_name, "passed": sr.passed, "attempts": sr.attempts}
            )
    for sr_dict in external_skill_results:
        skill_entries.append(
            {
                "name": str(sr_dict.get("skill_name", "unknown")),
                "passed": bool(sr_dict.get("passed", False)),
                "attempts": int(sr_dict.get("attempts", 0)),
            }
        )

    event = {
        "timestamp": summary.harvested_at,
        "issue": summary.issue_number,
        "phase": summary.phase,
        "run_id": summary.run_id,
        "tokens": {
            "input": summary.tokens.prompt_tokens,
            "output": summary.tokens.completion_tokens,
            "cache_read": summary.tokens.cache_read_tokens,
            "cache_creation": summary.tokens.cache_creation_tokens,
        },
        "tools": dict(summary.tools.tool_counts),
        "skills": skill_entries,
        "subagents": summary.skills.total_subagents,
        "duration_seconds": summary.spans.duration_seconds,
        "crashed": summary.crashed,
    }

    with open(metrics_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
