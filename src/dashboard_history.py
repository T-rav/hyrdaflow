"""Issue history aggregation and route handlers for the dashboard API."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_router_deps import RouterDeps
from dashboard_routes import (
    _EPIC_INTERNAL_LABELS,
    _INFERENCE_COUNTER_KEYS,
    _coerce_history_status,
    _coerce_int,
    _event_issue_number,
    _is_timestamp_in_range,
    _normalise_event_status,
    _parse_iso_or_none,
    _status_sort_key,
)
from events import EventType
from issue_fetcher import IssueFetcher
from models import (
    IssueHistoryEntry,
    IssueHistoryLink,
    IssueHistoryPR,
    IssueHistoryResponse,
    IssueOutcome,
    IssueOutcomeType,
    parse_task_links,
)
from prompt_telemetry import PromptTelemetry

logger = logging.getLogger("hydraflow.dashboard")

_HISTORY_CACHE_TTL = 30  # seconds


# ------------------------------------------------------------------
# Pure helpers (no dependency on RouterDeps)
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
    # Legacy fallback: bare set of ints
    return sorted(
        (IssueHistoryLink(target_id=int(v)) for v in raw if _coerce_int(v) > 0),
        key=lambda lnk: lnk.target_id,
    )


def _new_issue_history_entry(issue_number: int, repo_slug_raw: str) -> dict[str, Any]:
    """Create a blank history aggregation row for an issue."""
    repo_slug = (repo_slug_raw or "").strip()
    if repo_slug.startswith("https://github.com/"):
        repo_slug = repo_slug[len("https://github.com/") :]
    elif repo_slug.startswith("http://github.com/"):
        repo_slug = repo_slug[len("http://github.com/") :]
    repo_slug = repo_slug.strip("/")
    issue_url = (
        f"https://github.com/{repo_slug}/issues/{issue_number}" if repo_slug else ""
    )
    return {
        "issue_number": issue_number,
        "title": f"Issue #{issue_number}",
        "issue_url": issue_url,
        "status": "unknown",
        "epic": "",
        "crate_number": None,
        "crate_title": "",
        "linked_issues": {},
        "prs": {},
        "session_ids": set(),
        "source_calls": {},
        "model_calls": {},
        "inference": dict.fromkeys(_INFERENCE_COUNTER_KEYS, 0),
        "first_seen": None,
        "last_seen": None,
        "status_updated_at": None,
    }


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


def _process_events_into_rows(
    events: list[Any],
    issue_rows: dict[int, dict[str, Any]],
    pr_to_issue: dict[int, int],
    since_dt: datetime | None,
    until_dt: datetime | None,
    repo_slug: str,
) -> None:
    """Process event-bus events into *issue_rows* in place."""
    for event in events:
        timestamp = event.timestamp
        if not _is_timestamp_in_range(timestamp, since_dt, until_dt):
            continue

        issue_number = _event_issue_number(event.data)
        if issue_number is None and event.type == EventType.MERGE_UPDATE:
            pr_num = _coerce_int(event.data.get("pr"))
            issue_number = pr_to_issue.get(pr_num)

        if issue_number is None or issue_number <= 0:
            continue

        row = issue_rows.setdefault(
            issue_number, _new_issue_history_entry(issue_number, repo_slug)
        )
        _touch_issue_timestamps(row, timestamp)

        maybe_title = str(event.data.get("title", "")).strip()
        if maybe_title:
            row["title"] = maybe_title

        maybe_url = str(event.data.get("url", "")).strip()
        if maybe_url.startswith(("http://", "https://")):
            row["issue_url"] = maybe_url

        if event.type == EventType.ISSUE_CREATED:
            labels = event.data.get("labels", [])
            if isinstance(labels, list) and not row.get("epic"):
                for lbl in labels:
                    s = str(lbl).strip()
                    if (
                        s
                        and "epic" in s.lower()
                        and s.lower() not in _EPIC_INTERNAL_LABELS
                    ):
                        row["epic"] = s
                        break
            milestone_num = _coerce_int(event.data.get("milestone_number"))
            if milestone_num > 0 and not row.get("crate_number"):
                row["crate_number"] = milestone_num

        if event.type == EventType.PR_CREATED:
            pr_number = _coerce_int(event.data.get("pr"))
            if pr_number > 0:
                pr_to_issue[pr_number] = issue_number
                prs = row["prs"]
                payload = prs.get(
                    pr_number,
                    {"number": pr_number, "url": "", "merged": False},
                )
                url = str(event.data.get("url", "")).strip()
                if url.startswith(("http://", "https://")):
                    payload["url"] = url
                prs[pr_number] = payload

        if event.type == EventType.MERGE_UPDATE:
            pr_number = _coerce_int(event.data.get("pr"))
            if pr_number > 0:
                prs = row["prs"]
                payload = prs.get(
                    pr_number,
                    {"number": pr_number, "url": "", "merged": False},
                )
                if str(event.data.get("status", "")).lower() == "merged":
                    payload["merged"] = True
                prs[pr_number] = payload

        normalised = _normalise_event_status(event.type, event.data)
        if normalised:
            current = str(row.get("status", "unknown"))
            current_ts = (
                row.get("status_updated_at")
                if isinstance(row.get("status_updated_at"), str)
                else None
            )
            if _status_sort_key(normalised, timestamp) >= _status_sort_key(
                current, current_ts
            ):
                row["status"] = normalised
                row["status_updated_at"] = timestamp


# ------------------------------------------------------------------
# History cache I/O
# ------------------------------------------------------------------


def save_history_cache(
    cache: dict[str, Any],
    cache_file: Any,  # pathlib.Path
) -> None:
    """Persist in-memory history cache to disk."""
    rows = cache.get("issue_rows")
    if rows is None:
        return
    serialisable_rows: dict[str, Any] = {}
    for k, v in rows.items():
        entry = dict(v)
        # Convert sets to lists for JSON serialisation.
        entry["session_ids"] = sorted(entry.get("session_ids") or [])
        serialisable_rows[str(k)] = entry
    payload = {
        "event_count": cache.get("event_count", -1),
        "telemetry_mtime": cache.get("telemetry_mtime", 0.0),
        "issue_rows": serialisable_rows,
        "pr_to_issue": {str(k): v for k, v in (cache.get("pr_to_issue") or {}).items()},
        "enriched_issues": sorted(cache.get("enriched_issues") or []),
    }
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(cache_file)
    except OSError:
        logger.debug("Could not persist history cache", exc_info=True)


def load_history_cache(
    cache: dict[str, Any],
    cache_ts: list[float],
    cache_file: Any,  # pathlib.Path
) -> None:
    """Load persisted history cache from disk into memory."""
    if not cache_file.is_file():
        return
    try:
        raw = json.loads(cache_file.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        logger.debug("Corrupt history cache, ignoring", exc_info=True)
        return
    if not isinstance(raw, dict) or "issue_rows" not in raw:
        return
    rows: dict[int, dict[str, Any]] = {}
    for k, v in raw.get("issue_rows", {}).items():
        if not isinstance(v, dict):
            continue
        entry = dict(v)
        # Restore session_ids to a set.
        entry["session_ids"] = set(entry.get("session_ids") or [])
        # JSON keys are always strings — restore int keys for sub-dicts
        # so enrichment lookups (which use int keys) don't create dupes.
        if isinstance(entry.get("prs"), dict):
            entry["prs"] = {int(pk): pv for pk, pv in entry["prs"].items()}
        if isinstance(entry.get("linked_issues"), dict):
            entry["linked_issues"] = {
                int(lk): lv for lk, lv in entry["linked_issues"].items()
            }
        rows[int(k)] = entry
    cache["issue_rows"] = rows
    cache["pr_to_issue"] = {
        int(k): int(v) for k, v in raw.get("pr_to_issue", {}).items()
    }
    cache["event_count"] = raw.get("event_count", -1)
    cache["telemetry_mtime"] = raw.get("telemetry_mtime", 0.0)
    cache["enriched_issues"] = set(raw.get("enriched_issues") or [])
    # Set timestamp so TTL check works (treat as "just loaded").
    cache_ts[0] = time.monotonic()


# ------------------------------------------------------------------
# Router factory
# ------------------------------------------------------------------


def create_history_router(deps: RouterDeps) -> APIRouter:
    """Create an APIRouter with issue history and outcome endpoints."""
    router = APIRouter()
    config = deps.config
    state = deps.state
    event_bus = deps.event_bus
    pr_manager = deps.pr_manager

    _history_cache_file = config.data_path("metrics", "history_cache.json")

    _history_cache: dict[str, Any] = {
        "event_count": -1,
        "telemetry_mtime": 0.0,
        "issue_rows": None,
        "pr_to_issue": None,
        "enriched_issues": set(),
    }
    _history_cache_ts: list[float] = [0.0]

    def _save() -> None:
        save_history_cache(_history_cache, _history_cache_file)

    def _load() -> None:
        load_history_cache(_history_cache, _history_cache_ts, _history_cache_file)

    # Warm the in-memory cache from disk on startup.
    try:
        _load()
    except Exception:
        logger.warning("History cache warm-up failed", exc_info=True)

    # ------------------------------------------------------------------
    # Enrichment helpers
    # ------------------------------------------------------------------

    async def _enrich_issue_history_with_github(
        entries: dict[int, dict[str, Any]], limit: int = 150
    ) -> None:
        """Concurrently fetch GitHub metadata and apply it to history entries."""
        if not entries:
            return

        fetcher = IssueFetcher(config)
        issue_numbers = sorted(entries.keys(), reverse=True)[:limit]
        sem = asyncio.Semaphore(6)

        async def _fetch_and_apply(issue_number: int) -> None:
            async with sem:
                issue = await fetcher.fetch_issue_by_number(issue_number)
            if issue is None:
                return
            row = entries.get(issue_number)
            if row is None:
                return
            row["title"] = issue.title or row.get("title") or f"Issue #{issue_number}"
            row["issue_url"] = issue.url or row.get("issue_url", "")
            labels = [str(lbl).strip() for lbl in issue.labels if str(lbl).strip()]
            if not row.get("epic"):
                epic = next(
                    (
                        lbl
                        for lbl in labels
                        if "epic" in lbl.lower()
                        and lbl.lower() not in _EPIC_INTERNAL_LABELS
                    ),
                    "",
                )
                row["epic"] = epic
            ms_num = _coerce_int(getattr(issue, "milestone_number", None))
            if ms_num > 0 and not row.get("crate_number"):
                row["crate_number"] = ms_num
            for link in parse_task_links(issue.body or ""):
                tid = int(link.target_id)
                row["linked_issues"][tid] = {
                    "target_id": tid,
                    "kind": str(link.kind),
                    "target_url": link.target_url or None,
                }

        await asyncio.gather(*(_fetch_and_apply(num) for num in issue_numbers))

    def _filter_rows_to_items(
        issue_rows: dict[int, dict[str, Any]],
        requested_status: str,
        query_text: str,
    ) -> list[IssueHistoryEntry]:
        """Filter *issue_rows* and convert to ``IssueHistoryEntry`` objects."""
        items: list[IssueHistoryEntry] = []
        for row in issue_rows.values():
            row_status = str(row.get("status", "unknown")).lower()
            if requested_status and row_status != requested_status:
                continue

            issue_number = int(row["issue_number"])
            title = str(row.get("title", f"Issue #{issue_number}"))
            if (
                query_text
                and query_text not in title.lower()
                and query_text not in str(issue_number)
            ):
                continue

            items.append(
                _build_issue_history_entry(row, state.get_outcome(issue_number))
            )
        return items

    async def _apply_enrichment_and_crate_titles(
        items: list[IssueHistoryEntry],
        issue_rows: dict[int, dict[str, Any]],
        requested_status: str,
        query_text: str,
        use_unfiltered: bool,
    ) -> list[IssueHistoryEntry]:
        """Enrich items via GitHub and backfill crate titles from milestones."""
        already_enriched: set[int] = _history_cache.get("enriched_issues", set())
        issue_lookup = {
            item.issue_number: issue_rows[item.issue_number] for item in items
        }
        enrich_candidates = [
            item.issue_number
            for item in items
            if item.issue_number not in already_enriched
            and (
                not item.issue_url
                or item.title.startswith("Issue #")
                or (not item.epic and not item.linked_issues)
            )
        ][:40]
        if enrich_candidates:
            await _enrich_issue_history_with_github(
                {k: issue_lookup[k] for k in enrich_candidates}
            )
            already_enriched.update(enrich_candidates)
            _history_cache["enriched_issues"] = already_enriched
            if use_unfiltered and _history_cache["issue_rows"] is not None:
                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _save()
            # Rebuild items from enriched rows.
            items = _filter_rows_to_items(issue_rows, requested_status, query_text)

        # Sort before crate-title backfill so milestone fetches are done
        # after ordering.
        items.sort(
            key=lambda item: (
                item.last_seen or "",
                item.inference.get("total_tokens", 0),
                item.issue_number,
            ),
            reverse=True,
        )

        # Populate crate titles from milestones for items that have a
        # crate_number but no title yet.
        needs_title = any(i.crate_number and not i.crate_title for i in items)
        if needs_title:
            try:
                milestones = await pr_manager.list_milestones(state="all")
                title_map = {m.number: m.title for m in milestones}
                items = [
                    i.model_copy(
                        update={"crate_title": title_map.get(i.crate_number, "")}
                    )
                    if i.crate_number and not i.crate_title
                    else i
                    for i in items
                ]
                # Also backfill into the raw rows so the cache carries titles.
                backfilled = False
                for i in items:
                    if i.crate_number and i.crate_title:
                        raw = issue_rows.get(i.issue_number)
                        if raw is not None and raw.get("crate_title") != i.crate_title:
                            raw["crate_title"] = i.crate_title
                            backfilled = True
                if (
                    backfilled
                    and use_unfiltered
                    and _history_cache.get("issue_rows") is not None
                ):
                    _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                    _save()
            except Exception:
                logger.warning(
                    "Failed to fetch milestones for crate titles", exc_info=True
                )

        # Backfill epic field from state's epic tracking when not already set.
        epic_states = state.get_all_epic_states()
        if epic_states:
            child_to_epic: dict[int, str] = {}
            for es in epic_states.values():
                title = es.title or f"Epic #{es.epic_number}"
                for child in es.child_issues:
                    child_to_epic[child] = title
            if child_to_epic:
                items = [
                    i.model_copy(update={"epic": child_to_epic[i.issue_number]})
                    if not i.epic and i.issue_number in child_to_epic
                    else i
                    for i in items
                ]

        # Derive outcome for issues that completed the pipeline (have a
        # merged PR) but were never given an explicit record_outcome() call.
        items = [
            i.model_copy(
                update={
                    "outcome": IssueOutcome(
                        outcome=IssueOutcomeType.MERGED,
                        reason="Derived from merged PR",
                        closed_at=i.last_seen or "",
                        pr_number=next((p.number for p in i.prs if p.merged), None),
                        phase="review",
                    )
                }
            )
            if not i.outcome and any(p.merged for p in i.prs)
            else i
            for i in items
        ]

        return items

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    @router.get("/api/issues/outcomes")
    async def get_issue_outcomes() -> JSONResponse:
        """Return all recorded issue outcomes."""
        outcomes = state.get_all_outcomes()
        return JSONResponse({k: v.model_dump() for k, v in outcomes.items()})

    @router.get("/api/issues/history")
    async def get_issue_history(
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 300,
    ) -> JSONResponse:
        """Return issue lifecycle history with inference rollups."""
        since_dt = _parse_iso_or_none(since)
        until_dt = _parse_iso_or_none(until)
        requested_status = (status or "").strip().lower()
        query_text = (query or "").strip().lower()
        clamped_limit = max(1, min(limit, 1000))
        repo_slug = config.repo or ""

        telemetry = PromptTelemetry(config)
        all_events = event_bus.get_history()

        # Check if we can reuse cached aggregation for the unfiltered case.
        use_unfiltered = since_dt is None and until_dt is None
        event_count = len(all_events)
        telem_mtime = telemetry.get_mtime()
        now = time.monotonic()
        cache_hit = (
            use_unfiltered
            and _history_cache["issue_rows"] is not None
            and _history_cache["event_count"] == event_count
            and _history_cache["telemetry_mtime"] == telem_mtime
            and (now - _history_cache_ts[0]) < _HISTORY_CACHE_TTL
        )

        if cache_hit:
            issue_rows: dict[int, dict[str, Any]] = copy.deepcopy(
                _history_cache["issue_rows"]
            )
            pr_to_issue: dict[int, int] = dict(_history_cache["pr_to_issue"])
        else:
            issue_rows = {}
            pr_to_issue = {}

            # Build PR->issue mapping from all in-memory events first so merge
            # events in the selected range still resolve.
            for event in all_events:
                if event.type != EventType.PR_CREATED:
                    continue
                mapped_issue = _event_issue_number(event.data)
                mapped_pr = _coerce_int(event.data.get("pr"))
                if mapped_issue is not None and mapped_issue > 0 and mapped_pr > 0:
                    pr_to_issue[mapped_pr] = mapped_issue

        use_issue_rollups = (
            since_dt is None
            and until_dt is None
            and not query_text
            and not requested_status
        )
        if cache_hit:
            pass  # aggregation already done
        elif use_issue_rollups:
            for issue_number, counters in telemetry.get_issue_totals().items():
                row = issue_rows.setdefault(
                    issue_number,
                    _new_issue_history_entry(issue_number, repo_slug),
                )
                for key in _INFERENCE_COUNTER_KEYS:
                    row["inference"][key] = _coerce_int(counters.get(key, 0))
            # Keep metadata (sessions/model/source/pr links) from recent rows
            # without re-summing counters that already came from rollups.
            for record in telemetry.load_inferences(limit=5000):
                issue_number = _coerce_int(record.get("issue_number"))
                if issue_number <= 0:
                    continue
                row = issue_rows.get(issue_number)
                if row is None:
                    continue
                _aggregate_telemetry_record(
                    row, record, pr_to_issue, sum_counters=False
                )
        else:
            inference_rows = telemetry.load_inferences(limit=50000)
            for record in inference_rows:
                timestamp = record.get("timestamp")
                if not _is_timestamp_in_range(
                    timestamp if isinstance(timestamp, str) else None,
                    since_dt,
                    until_dt,
                ):
                    continue
                issue_number = _coerce_int(record.get("issue_number"))
                if issue_number <= 0:
                    continue
                row = issue_rows.setdefault(
                    issue_number,
                    _new_issue_history_entry(issue_number, repo_slug),
                )
                _aggregate_telemetry_record(row, record, pr_to_issue, sum_counters=True)

        if not cache_hit:
            _process_events_into_rows(
                all_events, issue_rows, pr_to_issue, since_dt, until_dt, repo_slug
            )

            # Store in cache if this was an unfiltered aggregation.
            if use_unfiltered:
                _history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                _history_cache["pr_to_issue"] = dict(pr_to_issue)
                _history_cache["event_count"] = event_count
                _history_cache["telemetry_mtime"] = telem_mtime
                _history_cache_ts[0] = now
                _save()

        items = _filter_rows_to_items(issue_rows, requested_status, query_text)

        # Enrich via GitHub, backfill crate titles, sort.
        items = await _apply_enrichment_and_crate_titles(
            items, issue_rows, requested_status, query_text, use_unfiltered
        )
        items = items[:clamped_limit]

        totals = {
            "issues": len(items),
            "inference_calls": sum(
                i.inference.get("inference_calls", 0) for i in items
            ),
            "total_tokens": sum(i.inference.get("total_tokens", 0) for i in items),
        }

        return JSONResponse(
            IssueHistoryResponse(
                items=items,
                totals=totals,
                since=since_dt.isoformat() if since_dt else None,
                until=until_dt.isoformat() if until_dt else None,
            ).model_dump()
        )

    return router
