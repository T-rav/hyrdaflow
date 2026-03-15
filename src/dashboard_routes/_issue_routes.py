"""Issue history and outcomes route handlers for the HydraFlow dashboard."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard_routes._helpers import (
    _EPIC_INTERNAL_LABELS,
    _INFERENCE_COUNTER_KEYS,
    _aggregate_telemetry_record,
    _build_issue_history_entry,
    _coerce_int,
    _event_issue_number,
    _is_timestamp_in_range,
    _normalise_event_status,
    _parse_iso_or_none,
    _status_sort_key,
    _touch_issue_timestamps,
)
from events import EventType
from issue_fetcher import IssueFetcher
from models import (
    IssueHistoryResponse,
    IssueOutcome,
    IssueOutcomeType,
    parse_task_links,
)
from prompt_telemetry import PromptTelemetry

if TYPE_CHECKING:
    from datetime import datetime

    from dashboard_routes._context import RouterContext

logger = logging.getLogger("hydraflow.dashboard")


# ------------------------------------------------------------------
# Module-level helper functions (formerly closures, now take ctx)
# ------------------------------------------------------------------


def _process_events_into_rows(
    ctx: RouterContext,
    events: list[Any],
    issue_rows: dict[int, dict[str, Any]],
    pr_to_issue: dict[int, int],
    since_dt: datetime | None,
    until_dt: datetime | None,
) -> None:
    """Walk event history and populate issue_rows and pr_to_issue maps."""
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
            issue_number, ctx.new_issue_history_entry(issue_number)
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
                    pr_number, {"number": pr_number, "url": "", "merged": False}
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
                    pr_number, {"number": pr_number, "url": "", "merged": False}
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


def _filter_rows_to_items(
    ctx: RouterContext,
    issue_rows: dict[int, dict[str, Any]],
    requested_status: str,
    query_text: str,
) -> list[Any]:
    """Filter and convert raw aggregation rows to IssueHistoryEntry models."""
    items = []
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
            _build_issue_history_entry(row, ctx.state.get_outcome(issue_number))
        )
    return items


async def _enrich_issue_history_with_github(
    ctx: RouterContext,
    entries: dict[int, dict[str, Any]],
    limit: int = 150,
) -> None:
    """Fetch issue metadata from GitHub and backfill into history rows."""
    if not entries:
        return
    fetcher = IssueFetcher(ctx.config)
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
            try:
                tid = int(link.target_id)
            except (ValueError, TypeError):
                continue
            row["linked_issues"][tid] = {
                "target_id": tid,
                "kind": str(link.kind),
                "target_url": link.target_url or None,
            }

    results = await asyncio.gather(
        *(_fetch_and_apply(num) for num in issue_numbers), return_exceptions=True
    )
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Issue enrichment fetch failed: %s", result)


async def _apply_enrichment_and_crate_titles(
    ctx: RouterContext,
    items: list[Any],
    issue_rows: dict[int, dict[str, Any]],
    requested_status: str,
    query_text: str,
    use_unfiltered: bool,
) -> list[Any]:
    """Enrich items with GitHub data and crate/milestone titles."""
    already_enriched = ctx.history_cache.get("enriched_issues", set())
    issue_lookup = {item.issue_number: issue_rows[item.issue_number] for item in items}
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
            ctx, {k: issue_lookup[k] for k in enrich_candidates}
        )
        already_enriched.update(enrich_candidates)
        ctx.history_cache["enriched_issues"] = already_enriched
        if use_unfiltered and ctx.history_cache["issue_rows"] is not None:
            ctx.history_cache["issue_rows"] = copy.deepcopy(issue_rows)
            ctx.save_history_cache()
        items = _filter_rows_to_items(ctx, issue_rows, requested_status, query_text)
    items.sort(
        key=lambda item: (
            item.last_seen or "",
            item.inference.get("total_tokens", 0),
            item.issue_number,
        ),
        reverse=True,
    )

    # Backfill crate/milestone titles
    needs_title = any(i.crate_number and not i.crate_title for i in items)
    if needs_title:
        try:
            milestones = await ctx.pr_manager.list_milestones(state="all")
            title_map = {m.number: m.title for m in milestones}
            items = [
                i.model_copy(update={"crate_title": title_map.get(i.crate_number, "")})
                if i.crate_number and not i.crate_title
                else i
                for i in items
            ]
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
                and ctx.history_cache.get("issue_rows") is not None
            ):
                ctx.history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                ctx.save_history_cache()
        except Exception:
            logger.warning("Failed to fetch milestones for crate titles", exc_info=True)

    # Backfill epic names from epic state
    epic_states = ctx.state.get_all_epic_states()
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

    # Derive merged outcome from PR data
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
# Route registration
# ------------------------------------------------------------------


def register_issue_routes(router: APIRouter, ctx: RouterContext) -> None:
    """Register issue history and outcomes routes on *router*."""

    @router.get("/api/issues/outcomes")
    async def get_issue_outcomes() -> JSONResponse:
        outcomes = ctx.state.get_all_outcomes()
        return JSONResponse({k: v.model_dump() for k, v in outcomes.items()})

    @router.get("/api/issues/history")
    async def get_issue_history(
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 300,
    ) -> JSONResponse:
        since_dt = _parse_iso_or_none(since)
        until_dt = _parse_iso_or_none(until)
        requested_status = (status or "").strip().lower()
        query_text = (query or "").strip().lower()
        clamped_limit = max(1, min(limit, 1000))

        telemetry = PromptTelemetry(ctx.config)
        all_events = ctx.event_bus.get_history()

        use_unfiltered = since_dt is None and until_dt is None
        event_count = len(all_events)
        telem_mtime = telemetry.get_mtime()
        now = time.monotonic()
        cache_hit = (
            use_unfiltered
            and ctx.history_cache["issue_rows"] is not None
            and ctx.history_cache["event_count"] == event_count
            and ctx.history_cache["telemetry_mtime"] == telem_mtime
            and (now - ctx.history_cache_ts[0]) < ctx.HISTORY_CACHE_TTL
        )

        if cache_hit:
            issue_rows = copy.deepcopy(ctx.history_cache["issue_rows"])
            pr_to_issue = dict(ctx.history_cache["pr_to_issue"])
        else:
            issue_rows: dict[int, dict[str, Any]] = {}
            pr_to_issue: dict[int, int] = {}
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
            pass
        elif use_issue_rollups:
            for issue_number, counters in telemetry.get_issue_totals().items():
                row = issue_rows.setdefault(
                    issue_number, ctx.new_issue_history_entry(issue_number)
                )
                for key in _INFERENCE_COUNTER_KEYS:
                    row["inference"][key] = _coerce_int(counters.get(key, 0))
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
                    issue_number, ctx.new_issue_history_entry(issue_number)
                )
                _aggregate_telemetry_record(row, record, pr_to_issue, sum_counters=True)

        if not cache_hit:
            _process_events_into_rows(
                ctx, all_events, issue_rows, pr_to_issue, since_dt, until_dt
            )
            if use_unfiltered:
                ctx.history_cache["issue_rows"] = copy.deepcopy(issue_rows)
                ctx.history_cache["pr_to_issue"] = dict(pr_to_issue)
                ctx.history_cache["event_count"] = event_count
                ctx.history_cache["telemetry_mtime"] = telem_mtime
                ctx.history_cache_ts[0] = now
                ctx.save_history_cache()

        items = _filter_rows_to_items(ctx, issue_rows, requested_status, query_text)
        items = await _apply_enrichment_and_crate_titles(
            ctx, items, issue_rows, requested_status, query_text, use_unfiltered
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
