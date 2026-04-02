"""Shared constants and helpers for dashboard route sub-modules.

When ``dashboard_routes`` is split into smaller sub-routers, import these
symbols from here rather than copy-pasting definitions.  The guard test in
``tests/test_dashboard_routes_common.py`` will catch any accidental
duplication.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from issue_store import IssueStoreStage

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_SAFE_SLUG_COMPONENT = re.compile(r"^[A-Za-z0-9_.\-]+$")

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

# Interval bounds per editable worker.
# memory_sync, metrics, pr_unsticker, adr_reviewer bounds must match config.py Field constraints.
# pipeline_poller has no config Field; 5s minimum matches the hardcoded default.
_INTERVAL_BOUNDS: dict[str, tuple[int, int]] = {
    "memory_sync": (10, 14400),
    "metrics": (30, 14400),
    "pr_unsticker": (60, 86400),
    "pipeline_poller": (5, 14400),
    "adr_reviewer": (28800, 432000),
    "verify_monitor": (60, 86400),
    "stale_issue": (300, 86400),
    "stale_issue_gc": (300, 86400),
    "ci_monitor": (60, 86400),
    "security_patch": (300, 86400),
    "code_grooming": (3600, 604800),
}

# Internal pipeline labels that must not be treated as epic names in the history panel.
_EPIC_INTERNAL_LABELS: frozenset[str] = frozenset(
    {"hydraflow-epic-child", "hydraflow-epic"}
)

# Backend stage keys → frontend stage names
_STAGE_NAME_MAP: dict[str, str] = {
    IssueStoreStage.FIND: "triage",
    IssueStoreStage.DISCOVER: "discover",
    IssueStoreStage.SHAPE: "shape",
    IssueStoreStage.PLAN: "plan",
    IssueStoreStage.READY: "implement",
    IssueStoreStage.REVIEW: "review",
    IssueStoreStage.HITL: "hitl",
    IssueStoreStage.MERGED: "merged",
}

# Frontend stage key → config label field name (for request-changes)
_FRONTEND_STAGE_TO_LABEL_FIELD: dict[str, str] = {
    "triage": "find_label",
    "discover": "discover_label",
    "shape": "shape_label",
    "plan": "planner_label",
    "implement": "ready_label",
    "review": "review_label",
}

_INFERENCE_COUNTER_KEYS: tuple[str, ...] = (
    "inference_calls",
    "prompt_est_tokens",
    "total_est_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "history_chars_saved",
    "context_chars_saved",
    "pruned_chars_total",
    "cache_hits",
    "cache_misses",
)

# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

_HISTORY_STATUSES: set[str] = {
    "unknown",
    "triaged",
    "planned",
    "implemented",
    "in_review",
    "reviewed",
    "hitl",
    "active",
    "failed",
    "merged",
}

_STATUS_RANKS: dict[str, int] = {
    "unknown": 0,
    "triaged": 1,
    "planned": 2,
    "implemented": 3,
    "in_review": 4,
    "reviewed": 5,
    "hitl": 6,
    "active": 7,
    "failed": 8,
    "merged": 9,
}


def _parse_iso_or_none(raw: str | None) -> datetime | None:
    """Parse an ISO 8601 string to datetime, returning None on failure."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _coerce_int(value: object) -> int:
    """Coerce a value to int, returning 0 for unconvertible inputs."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _coerce_history_status(value: str) -> str:
    """Normalize dashboard history statuses and default to ``unknown``."""

    cleaned = str(value).strip().lower()
    if cleaned in _HISTORY_STATUSES:
        return cleaned
    logging.getLogger("hydraflow.dashboard").warning(
        "Unknown history status %r; falling back to 'unknown'", value
    )
    return "unknown"


def _status_rank(status: str) -> int:
    """Return a numeric rank for a history status used for ordering."""
    return _STATUS_RANKS.get(status, 0)


def _is_timestamp_in_range(
    raw: str | None, since: datetime | None, until: datetime | None
) -> bool:
    """Return True if the ISO timestamp falls within the [since, until] window."""
    if raw is None:
        return since is None and until is None
    parsed = _parse_iso_or_none(raw)
    if parsed is None:
        return since is None and until is None
    if since is not None and parsed < since:
        return False
    return not (until is not None and parsed > until)


def _status_sort_key(status: str, timestamp: str | None) -> tuple[datetime, int]:
    """Build a sort key from a timestamp and status rank for ordering updates."""
    parsed = _parse_iso_or_none(timestamp)
    if parsed is None:
        parsed = datetime.min.replace(tzinfo=UTC)
    return (parsed, _status_rank(status))


def _parse_compat_json_object(raw: str | None) -> dict[str, Any] | None:
    """Best-effort parse of legacy query/body JSON object payloads."""

    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_field_from_sources(
    field_names: tuple[str, str],
    req: dict[str, Any] | None,
    req_query: str | None,
    query_params: tuple[str | None, str | None],
    *,
    query_params_first: bool = False,
) -> str:
    """Extract a value from query params, body dict, and JSON query.

    Args:
        field_names: Pair of field name keys to look up (primary, alias).
        req: Parsed request body dict.
        req_query: Raw ``req`` query parameter (may be JSON).
        query_params: Dedicated query-parameter values (primary, alias).
        query_params_first: When True, check query params before body;
            otherwise check body before query params.
    """
    candidates: list[str] = []

    def _push(value: str | int | float | bool | None) -> None:
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                candidates.append(trimmed)

    def _push_from_dict(src: dict[str, Any]) -> None:
        for name in field_names:
            _push(src.get(name))
        nested = src.get("req")
        if isinstance(nested, dict):
            for name in field_names:
                _push(nested.get(name))

    def _push_query_params() -> None:
        for qp in query_params:
            _push(qp)

    def _push_body() -> None:
        if isinstance(req, dict):
            _push_from_dict(req)

    # Ordering: query_params_first controls whether dedicated query
    # params are checked before or after the body dict.
    if query_params_first:
        _push_query_params()
        _push_body()
    else:
        _push_body()

    parsed_query = _parse_compat_json_object(req_query)
    if parsed_query:
        _push_from_dict(parsed_query)
    else:
        _push(req_query)

    if not query_params_first:
        _push_query_params()

    return candidates[0] if candidates else ""
