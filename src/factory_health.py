"""Factory health — longitudinal analysis of retrospective metrics.

Computes rolling averages, memory-impact cohort comparisons, and
regression detection over the retrospective JSONL log. Consumed by
the factory health dashboard route.
"""

from __future__ import annotations

import math
from typing import Any

# Metrics where lower values indicate better outcomes.
_LOWER_IS_BETTER: frozenset[str] = frozenset(
    {
        "quality_fix_rounds",
        "ci_fix_rounds",
        "duration_seconds",
    }
)

# Numeric metrics extracted directly from retrospective entries.
_NUMERIC_METRICS: tuple[str, ...] = (
    "plan_accuracy_pct",
    "quality_fix_rounds",
    "ci_fix_rounds",
    "duration_seconds",
)


def _extract_metric(entry: dict[str, Any], metric: str) -> float | None:
    """Extract a numeric metric value from a retrospective entry dict."""
    if metric == "first_pass_rate":
        verdict = entry.get("review_verdict", "")
        return 1.0 if verdict == "approve" else 0.0
    val = entry.get(metric)
    if isinstance(val, int | float):
        return float(val)
    return None


def compute_rolling_averages(
    entries: list[dict[str, Any]],
    window_size: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    """Compute rolling averages for key metrics over a sliding window.

    Returns a dict mapping metric name → list of data-point dicts, each
    with keys ``value``, ``window_start``, ``window_end``.
    """
    if not entries:
        return {}

    all_metrics = list(_NUMERIC_METRICS) + ["first_pass_rate"]
    result: dict[str, list[dict[str, Any]]] = {m: [] for m in all_metrics}

    n = len(entries)
    if n < window_size:
        # Not enough entries for a full window — compute one data point
        # covering all entries.
        for metric in all_metrics:
            values = [
                v for e in entries if (v := _extract_metric(e, metric)) is not None
            ]
            if values:
                avg = sum(values) / len(values)
                result[metric].append(
                    {
                        "value": avg,
                        "window_start": 0,
                        "window_end": n - 1,
                    }
                )
        return result

    for start in range(n - window_size + 1):
        window = entries[start : start + window_size]
        for metric in all_metrics:
            values = [
                v for e in window if (v := _extract_metric(e, metric)) is not None
            ]
            if values:
                avg = sum(values) / len(values)
                result[metric].append(
                    {
                        "value": avg,
                        "window_start": start,
                        "window_end": start + window_size - 1,
                    }
                )

    return result


def compute_cohorts(
    retro_entries: list[dict[str, Any]],
    telemetry_entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Split retrospective entries into memory-available and memory-unavailable cohorts.

    Joins on ``issue_number``. An issue is "memory available" if any
    matching telemetry record has ``context_chars_before > 0``.
    """
    # Build lookup: issue_number → max context_chars_before
    context_by_issue: dict[int, int] = {}
    for t in telemetry_entries:
        issue = t.get("issue_number")
        chars = t.get("context_chars_before", 0)
        if isinstance(issue, int) and isinstance(chars, int | float):
            context_by_issue[issue] = max(context_by_issue.get(issue, 0), int(chars))

    available: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    for entry in retro_entries:
        issue = entry.get("issue_number")
        if isinstance(issue, int) and context_by_issue.get(issue, 0) > 0:
            available.append(entry)
        else:
            unavailable.append(entry)

    return {
        "memory_available": _cohort_stats(available),
        "memory_unavailable": _cohort_stats(unavailable),
    }


def _cohort_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate stats for a cohort of retrospective entries."""
    n = len(entries)
    if n == 0:
        return {"count": 0}

    stats: dict[str, Any] = {"count": n}
    for metric in _NUMERIC_METRICS:
        values = [v for e in entries if (v := _extract_metric(e, metric)) is not None]
        if values:
            stats[metric] = sum(values) / len(values)
    # first_pass_rate
    verdicts = [_extract_metric(e, "first_pass_rate") for e in entries]
    valid = [v for v in verdicts if v is not None]
    if valid:
        stats["first_pass_rate"] = sum(valid) / len(valid)
    return stats


def detect_regressions(
    entries: list[dict[str, Any]],
    baseline_window: int = 20,
    recent_window: int = 5,
) -> list[dict[str, Any]]:
    """Detect metric regressions comparing recent entries to a baseline.

    A regression is flagged when the recent window mean deviates by >2σ
    from the baseline mean in the "worse" direction.
    """
    min_entries = baseline_window + recent_window
    if len(entries) < min_entries:
        return []

    baseline = entries[-min_entries:-recent_window]
    recent = entries[-recent_window:]

    metrics_keys = list(_NUMERIC_METRICS) + ["first_pass_rate"]
    regressions: list[dict[str, Any]] = []

    for metric in metrics_keys:
        base_vals = [
            v for e in baseline if (v := _extract_metric(e, metric)) is not None
        ]
        recent_vals = [
            v for e in recent if (v := _extract_metric(e, metric)) is not None
        ]

        if len(base_vals) < 2 or not recent_vals:
            continue

        base_mean = sum(base_vals) / len(base_vals)
        base_stddev = math.sqrt(
            sum((v - base_mean) ** 2 for v in base_vals) / len(base_vals)
        )

        if base_stddev == 0:
            continue

        recent_mean = sum(recent_vals) / len(recent_vals)
        deviation = abs(recent_mean - base_mean) / base_stddev

        if deviation <= 2.0:
            continue

        # Check direction: is this actually worse?
        if metric in _LOWER_IS_BETTER:
            is_worse = recent_mean > base_mean
        else:
            is_worse = recent_mean < base_mean

        if is_worse:
            regressions.append(
                {
                    "metric": metric,
                    "baseline_mean": round(base_mean, 2),
                    "recent_mean": round(recent_mean, 2),
                    "stddev": round(base_stddev, 2),
                    "deviation_sigma": round(deviation, 2),
                }
            )

    return regressions


def compute_summary(
    retro_entries: list[dict[str, Any]],
    telemetry_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute the full factory health summary for dashboard consumption."""
    return {
        "rolling_averages": compute_rolling_averages(retro_entries),
        "cohorts": compute_cohorts(retro_entries, telemetry_entries),
        "regressions": detect_regressions(retro_entries),
    }
