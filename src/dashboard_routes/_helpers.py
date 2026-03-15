"""Module-level helper functions and constants for dashboard routes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from events import EventType
from issue_store import IssueStoreStage
from models import (
    IssueHistoryEntry,
    IssueHistoryLink,
    IssueHistoryPR,
    IssueOutcome,
)

logger = logging.getLogger("hydraflow.dashboard")

_SAFE_SLUG_COMPONENT = re.compile(r"^[A-Za-z0-9_.\-]+$")

_SUPERVISOR_UNAVAILABLE_PREFIXES: tuple[str, ...] = (
    "hydraflow supervisor is not running.",
    "hf supervisor is not running.",
)
_SUPERVISOR_UNAVAILABLE_MESSAGE = (
    "HydraFlow supervisor is not running. "
    "Start HydraFlow inside the target repository with `make run`."
)

# Internal pipeline labels that must not be treated as epic names in the history panel.
_EPIC_INTERNAL_LABELS: frozenset[str] = frozenset(
    {"hydraflow-epic-child", "hydraflow-epic"}
)

# Backend stage keys → frontend stage names
_STAGE_NAME_MAP: dict[str, str] = {
    IssueStoreStage.FIND: "triage",
    IssueStoreStage.PLAN: "plan",
    IssueStoreStage.READY: "implement",
    IssueStoreStage.REVIEW: "review",
    IssueStoreStage.HITL: "hitl",
}

# Frontend stage key → config label field name (for request-changes)
_FRONTEND_STAGE_TO_LABEL_FIELD = {
    "triage": "find_label",
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


# ------------------------------------------------------------------
# Pure helper functions (no closure dependencies)
# ------------------------------------------------------------------


async def _run_dialog_command(*cmd: str, timeout_seconds: float = 30.0) -> str | None:
    """Run a folder-picker shell command and return trimmed stdout on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except (FileNotFoundError, OSError, TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    selected = (stdout or b"").decode().strip()
    return selected or None


async def _pick_folder_with_dialog() -> str | None:
    """Open a best-effort native folder picker and return the selected path."""
    if sys.platform == "darwin":
        selected = await _run_dialog_command(
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Select repository folder")',
        )
        if selected:
            return selected
    elif sys.platform.startswith("linux"):
        selected = await _run_dialog_command(
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Select repository folder",
        )
        if selected:
            return selected
    elif sys.platform.startswith("win"):
        selected = await _run_dialog_command(
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "[System.Reflection.Assembly]::LoadWithPartialName"
                "('System.Windows.Forms') | Out-Null; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }"
            ),
        )
        if selected:
            return selected
    return None


def _allowed_repo_roots() -> tuple[str, ...]:
    """Return normalized filesystem roots that repo browsing is allowed within."""
    roots = [
        os.path.realpath(str(Path.home())),
        os.path.realpath(tempfile.gettempdir()),
    ]
    deduped: list[str] = []
    for root in roots:
        if root not in deduped:
            deduped.append(root)
    return tuple(deduped)


def _normalize_allowed_dir(
    raw_path: str | None,
    allowed_roots: tuple[str, ...] | None = None,
) -> tuple[Path | None, str | None]:
    """Validate and normalize a directory path constrained to allowed roots.

    Parameters
    ----------
    allowed_roots:
        Override the default roots returned by :func:`_allowed_repo_roots`.
        Useful for testing without patching private module internals.
    """
    candidate = (raw_path or "").strip()
    if not candidate:
        return None, "path required"
    expanded = os.path.expanduser(candidate)
    if "\x00" in expanded:
        return None, "invalid path"
    candidate_abs = os.path.abspath(expanded)
    for root in allowed_roots if allowed_roots is not None else _allowed_repo_roots():
        root_real = os.path.realpath(root)
        with contextlib.suppress(ValueError):
            relative = os.path.relpath(candidate_abs, root_real)
            if relative == os.pardir or relative.startswith(f"{os.pardir}{os.sep}"):
                continue
            parts = [part for part in Path(relative).parts if part not in ("", ".")]
            if any(part == os.pardir for part in parts):
                continue
            resolved = Path(root_real).joinpath(*parts).resolve(strict=False)
            if os.path.commonpath([str(resolved), root_real]) != root_real:
                continue
            return resolved, None
    return None, "path must be inside your home directory or temp directory"


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


def _event_issue_number(data: Mapping[str, Any]) -> int | None:
    """Extract the issue number from an event data dict, coercing strings."""
    value = data.get("issue")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalise_event_status(
    event_type: EventType, data: Mapping[str, Any]
) -> str | None:
    """Map an event type and its data to a normalised history status string."""
    status = str(data.get("status", "")).lower()
    result: str | None = None
    if event_type == EventType.MERGE_UPDATE:
        result = "merged" if status == "merged" else None
    elif event_type == EventType.HITL_ESCALATION:
        result = "hitl"
    elif event_type == EventType.HITL_UPDATE:
        result = "reviewed" if status == "resolved" else "hitl"
    elif event_type == EventType.REVIEW_UPDATE:
        if status == "done":
            result = "reviewed"
        elif status == "failed":
            result = "failed"
        else:
            result = "active"
    elif event_type in {
        EventType.WORKER_UPDATE,
        EventType.PLANNER_UPDATE,
        EventType.TRIAGE_UPDATE,
    }:
        if status == "done":
            done_map = {
                EventType.WORKER_UPDATE: "implemented",
                EventType.PLANNER_UPDATE: "planned",
                EventType.TRIAGE_UPDATE: "triaged",
            }
            result = done_map.get(event_type, "active")
        elif status == "failed":
            result = "failed"
        else:
            result = "active"
    elif event_type == EventType.PR_CREATED:
        result = "in_review"
    return result


_HISTORY_STATUSES = {
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


def _coerce_history_status(value: str) -> str:
    """Normalize dashboard history statuses and default to ``unknown``."""
    cleaned = str(value).strip().lower()
    if cleaned in _HISTORY_STATUSES:
        return cleaned
    logger.warning("Unknown history status %r; falling back to 'unknown'", value)
    return "unknown"


def _status_rank(status: str) -> int:
    """Return a numeric rank for a history status used for ordering."""
    ranks = {
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
    return ranks.get(status, 0)


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


def _is_expected_supervisor_unavailable(exc: Exception) -> bool:
    """Return True for the expected local-dev supervisor-down condition."""
    text = str(exc).strip().lower()
    return any(text.startswith(prefix) for prefix in _SUPERVISOR_UNAVAILABLE_PREFIXES)


def _find_repo_match(slug: str, repos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a repo entry matching *slug* using cascading strategies."""
    if not slug:
        return None

    slug = slug.strip().strip("/")
    if not slug:
        return None

    slug_lower = slug.lower()
    short = slug.rsplit("/", maxsplit=1)[-1] if "/" in slug else None
    short_lower = short.lower() if short else None

    def _slug_match(target: str) -> dict[str, Any] | None:
        lower = target.lower()
        for r in repos:
            if r.get("slug") == target:
                return r
        for r in repos:
            repo_slug = r.get("slug")
            if repo_slug and repo_slug.lower() == lower:
                return r
        return None

    result = _slug_match(slug)
    if not result and short:
        result = _slug_match(short)

    if not result:
        candidates = [slug_lower]
        if short_lower:
            candidates.append(short_lower)
        for candidate in candidates:
            for r in repos:
                path = r.get("path") or ""
                if path and Path(path).name.lower() == candidate:
                    result = r
                    break
            if result:
                break

    if not result:
        for r in repos:
            path = r.get("path") or ""
            if path and slug_lower in path.lower().split("/"):
                result = r
                break

    return result


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


def _extract_repo_slug(
    req: dict[str, Any] | None,
    req_query: str | None,
    slug_query: str | None,
    repo_query: str | None,
) -> str:
    """Extract repo slug from supported request shapes."""
    return _extract_field_from_sources(
        ("slug", "repo"),
        req,
        req_query,
        (slug_query, repo_query),
        query_params_first=True,
    )


def _extract_repo_path(
    req: dict[str, Any] | None,
    req_query: str | None,
    path_query: str | None,
    repo_path_query: str | None,
) -> str:
    """Extract repo path from supported body/query payload shapes."""
    return _extract_field_from_sources(
        ("path", "repo_path"),
        req,
        req_query,
        (path_query, repo_path_query),
        query_params_first=False,
    )


def _extract_field_from_sources(
    field_names: tuple[str, str],
    req: dict[str, Any] | None,
    req_query: str | None,
    query_params: tuple[str | None, str | None],
    *,
    query_params_first: bool = False,
) -> str:
    """Extract a value from query params, body dict, and JSON query."""
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


def _is_likely_disconnect(exc: BaseException) -> bool:
    """Return True if *exc* looks like a normal WebSocket disconnect."""
    disconnect_types = (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
    )
    if isinstance(exc, disconnect_types):
        return True
    name = type(exc).__name__
    return name in {
        "WebSocketDisconnect",
        "ConnectionClosedError",
        "ConnectionClosedOK",
    }


# ------------------------------------------------------------------
# Issue history aggregation helpers
# ------------------------------------------------------------------


def _build_history_links(
    raw: dict[int, dict[str, Any]] | Iterable[Any],
) -> list[IssueHistoryLink]:
    """Convert the internal linked_issues accumulator to a sorted list."""
    if isinstance(raw, dict):
        return sorted(
            (
                IssueHistoryLink(
                    target_id=int(v["target_id"]),
                    kind=v.get("kind", "relates_to"),
                    target_url=v.get("target_url"),
                )
                for v in raw.values()
                if isinstance(v, dict) and _coerce_int(v.get("target_id")) > 0
            ),
            key=lambda lnk: lnk.target_id,
        )
    return sorted(
        (IssueHistoryLink(target_id=int(v)) for v in raw if _coerce_int(v) > 0),
        key=lambda lnk: lnk.target_id,
    )


def _touch_issue_timestamps(row: dict[str, Any], timestamp: str | None) -> None:
    """Update the first_seen / last_seen bounds of a history row."""
    if not timestamp:
        return
    current_first = row.get("first_seen")
    current_last = row.get("last_seen")
    if not isinstance(current_first, str) or timestamp < current_first:
        row["first_seen"] = timestamp
    if not isinstance(current_last, str) or timestamp > current_last:
        row["last_seen"] = timestamp


def _build_issue_history_entry(
    row: dict[str, Any],
    outcome: IssueOutcome | None,
) -> IssueHistoryEntry:
    """Build an ``IssueHistoryEntry`` from a raw aggregation row."""
    issue_number = int(row["issue_number"])
    title = str(row.get("title", f"Issue #{issue_number}"))
    row_status = str(row.get("status", "unknown")).lower()

    linked_issues = _build_history_links(row.get("linked_issues", {}))
    prs_map = row.get("prs", {})
    if not isinstance(prs_map, dict):
        prs_map = {}
    pr_rows = sorted(
        (
            IssueHistoryPR(
                number=int(pr_data["number"]),
                url=str(pr_data.get("url", "")),
                merged=bool(pr_data.get("merged", False)),
            )
            for pr_data in prs_map.values()
            if isinstance(pr_data, dict) and _coerce_int(pr_data.get("number")) > 0
        ),
        key=lambda p: p.number,
        reverse=True,
    )

    return IssueHistoryEntry(
        issue_number=issue_number,
        title=title,
        issue_url=str(row.get("issue_url", "")),
        status=_coerce_history_status(row_status),
        epic=str(row.get("epic", "")),
        crate_number=row.get("crate_number"),
        crate_title=str(row.get("crate_title", "")),
        linked_issues=linked_issues,
        prs=pr_rows,
        session_ids=sorted(str(s) for s in row.get("session_ids", set()) if str(s)),
        source_calls=dict(sorted(row.get("source_calls", {}).items())),
        model_calls=dict(sorted(row.get("model_calls", {}).items())),
        inference={k: _coerce_int(v) for k, v in row.get("inference", {}).items()},
        first_seen=row.get("first_seen"),
        last_seen=row.get("last_seen"),
        outcome=outcome,
    )


def _aggregate_telemetry_record(
    row: dict[str, Any],
    record: dict[str, Any],
    pr_to_issue: dict[int, int],
    *,
    sum_counters: bool = False,
) -> None:
    """Extract shared metadata from a telemetry record into *row*."""
    issue_number = int(row["issue_number"])
    timestamp = record.get("timestamp")
    _touch_issue_timestamps(row, timestamp if isinstance(timestamp, str) else None)

    session_id = str(record.get("session_id", "")).strip()
    if session_id:
        row["session_ids"].add(session_id)

    source = str(record.get("source", "")).strip()
    if source:
        row["source_calls"][source] = row["source_calls"].get(source, 0) + 1

    model = str(record.get("model", "")).strip()
    if model:
        row["model_calls"][model] = row["model_calls"].get(model, 0) + 1

    if sum_counters:
        for key in _INFERENCE_COUNTER_KEYS:
            row["inference"][key] += _coerce_int(record.get(key))

    pr_number = _coerce_int(record.get("pr_number"))
    if pr_number > 0:
        prs: dict[int, dict[str, Any]] = row["prs"]
        if pr_number not in prs:
            prs[pr_number] = {
                "number": pr_number,
                "url": "",
                "merged": False,
            }
        pr_to_issue.setdefault(pr_number, issue_number)
