"""Trust-fleet dashboard routes (spec §12.1).

Reads the schema documented at
``src/trust_fleet_sanity_loop.py:FLEET_ENDPOINT_SCHEMA`` and implements
it via three data sources:

1. ``EventBus.load_events_since`` → ``BACKGROUND_WORKER_STATUS`` events
   tallied by worker name for ``ticks_total``/``ticks_errored``/
   ``issues_filed_total``/etc. This is the pattern Plan 5b-3's
   ``TrustFleetSanityLoop._collect_counts`` documented.
2. ``state.get_worker_heartbeats()`` + ``bg_workers.worker_enabled`` +
   ``bg_workers.get_interval`` → ``last_tick_at`` / ``enabled`` /
   ``interval_s``.
3. ``gh issue list --label hitl-escalation --label trust-loop-anomaly
   --limit 200`` filtered to last 24h for ``anomalies_recent``. Cached
   at 60-second TTL because the fleet endpoint is UI-facing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess  # noqa: S404 — wrapped calls are trusted `gh` invocations
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from config import HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.dashboard.trust")

_ALLOWED_RANGES: dict[str, timedelta] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

_TITLE_RE = re.compile(
    r"HITL: trust-loop anomaly — (?P<worker>[\w_]+) (?P<kind>[\w_]+)$",
)


def _parse_range_for_trust(value: str | None) -> timedelta:
    """Parse the ``range`` query arg; only ``7d`` and ``30d`` are allowed per §12.1."""
    if not value:
        return _ALLOWED_RANGES["7d"]
    if value not in _ALLOWED_RANGES:
        msg = f"unsupported range: {value!r}"
        raise ValueError(msg)
    return _ALLOWED_RANGES[value]


_ANOMALY_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_ANOMALY_CACHE_TTL = 60


def _build_anomaly_reader(
    repo: str | None,
) -> Callable[[str], list[dict[str, Any]]]:
    """Return a callable that runs ``gh issue list`` for anomaly rows.

    Split out so tests can replace the subprocess call with a stub. The
    return value is a list of dicts matching the ``anomalies_recent``
    entry shape in ``FLEET_ENDPOINT_SCHEMA``.
    """

    def _read(_repo: str) -> list[dict[str, Any]]:
        try:
            out = subprocess.run(  # noqa: S603 — trusted ``gh`` invocation
                [
                    "gh",
                    "issue",
                    "list",
                    "--state",
                    "all",
                    "--label",
                    "hitl-escalation",
                    "--label",
                    "trust-loop-anomaly",
                    "--limit",
                    "200",
                    "--json",
                    "number,title,createdAt",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            raw = json.loads(out.stdout or "[]")
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
            FileNotFoundError,
        ):
            logger.warning("fleet anomaly reader: gh issue list failed", exc_info=True)
            return []
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        rows: list[dict[str, Any]] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", ""))
            m = _TITLE_RE.search(title)
            if m is None:
                continue
            created_s = str(item.get("createdAt", ""))
            try:
                created = datetime.fromisoformat(created_s.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created < cutoff:
                continue
            rows.append(
                {
                    "kind": m.group("kind"),
                    "worker": m.group("worker"),
                    "filed_at": created_s,
                    "issue_number": int(item.get("number", 0) or 0),
                    "details": {},
                }
            )
        return rows

    return _read


def _cached_anomalies(
    config: HydraFlowConfig,
    reader: Callable[[str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    key = config.repo or "_local_"
    now = time.time()
    cached = _ANOMALY_CACHE.get(key)
    if cached is not None and now - cached[0] < _ANOMALY_CACHE_TTL:
        return cached[1]
    rows = reader(key)
    _ANOMALY_CACHE[key] = (now, rows)
    return rows


def _tally_events(events: list[Any]) -> dict[str, dict[str, Any]]:
    """Tally ``BACKGROUND_WORKER_STATUS`` events by worker name."""
    out: dict[str, dict[str, Any]] = {}
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
        row = out.setdefault(
            worker,
            {
                "ticks_total": 0,
                "ticks_errored": 0,
                "issues_filed_total": 0,
                "issues_closed_total": 0,
                "issues_open_escalated": 0,
                "repair_attempts_total": 0,
                "repair_successes_total": 0,
                "repair_failures_total": 0,
                "loop_specific": {},
            },
        )
        row["ticks_total"] += 1
        if str(data.get("status", "")).lower() == "error":
            row["ticks_errored"] += 1
        details = data.get("details") or {}
        if isinstance(details, dict):
            row["issues_filed_total"] += int(details.get("filed", 0) or 0)
            row["issues_closed_total"] += int(details.get("closed", 0) or 0)
            row["issues_open_escalated"] += int(details.get("escalated", 0) or 0)
            row["repair_successes_total"] += int(details.get("repaired", 0) or 0)
            row["repair_failures_total"] += int(details.get("failed", 0) or 0)
            row["repair_attempts_total"] = (
                row["repair_successes_total"] + row["repair_failures_total"]
            )
            # Pass-through loop-specific keys per §12.1 examples.
            for k in (
                "reverts_merged",
                "cases_added",
                "cassettes_refreshed",
                "principles_regressions",
            ):
                if k in details:
                    row["loop_specific"][k] = int(details.get(k, 0) or 0)
    return out


def _empty_loop_row() -> dict[str, Any]:
    return {
        "ticks_total": 0,
        "ticks_errored": 0,
        "issues_filed_total": 0,
        "issues_closed_total": 0,
        "issues_open_escalated": 0,
        "repair_attempts_total": 0,
        "repair_successes_total": 0,
        "repair_failures_total": 0,
        "loop_specific": {},
    }


async def _read_fleet(
    config: HydraFlowConfig,
    *,
    event_bus: EventBus,
    bg_workers: BGWorkerManager,
    state: Any,
    range_td: timedelta,
    anomaly_reader: Callable[[str], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Compose the /api/trust/fleet payload (matches ``FLEET_ENDPOINT_SCHEMA``)."""
    now = datetime.now(UTC)
    since = now - range_td
    try:
        events = await event_bus.load_events_since(since) or []
    except Exception:  # noqa: BLE001
        logger.debug("load_events_since failed", exc_info=True)
        events = []
    tallies = _tally_events(events)
    try:
        heartbeats = state.get_worker_heartbeats() or {}
    except Exception:  # noqa: BLE001
        heartbeats = {}

    loops: list[dict[str, Any]] = []
    for worker in sorted(set(tallies.keys()) | set(heartbeats.keys())):
        row = tallies.get(worker) or _empty_loop_row()
        # Prefer ``is_enabled(name)`` (BGWorkerManager's public method); fall
        # back to ``worker_enabled`` — the dict property used during startup
        # recovery — so tests that supply a MagicMock on either attribute
        # still get a boolean. Spec §12.1 phrased this as
        # ``bg_workers.worker_enabled`` but the production method is
        # ``is_enabled``.
        try:
            is_enabled = getattr(bg_workers, "is_enabled", None)
            if callable(is_enabled):
                enabled = bool(is_enabled(worker))
            else:
                we = getattr(bg_workers, "worker_enabled", None)
                enabled = (
                    bool(we(worker))
                    if callable(we)
                    else bool((we or {}).get(worker, False))
                )
        except Exception:  # noqa: BLE001
            enabled = False
        try:
            interval_s = int(bg_workers.get_interval(worker))
        except Exception:  # noqa: BLE001
            interval_s = 0
        loops.append(
            {
                "worker_name": worker,
                "enabled": enabled,
                "interval_s": interval_s,
                "last_tick_at": heartbeats.get(worker) or None,
                **row,
            }
        )

    anomalies = _cached_anomalies(config, anomaly_reader)
    range_label = "30d" if range_td.days >= 30 else "7d"
    return {
        "range": range_label,
        "generated_at": now.isoformat(),
        "loops": loops,
        "anomalies_recent": anomalies,
    }


def build_trust_router(
    config: HydraFlowConfig,
    *,
    deps_factory: Callable[[], Any],
) -> APIRouter:
    """Build the ``/api/trust`` router.

    ``deps_factory`` returns an object with three attributes: ``event_bus``,
    ``bg_workers``, ``state``. Split so tests can inject mocks without
    standing up the full ServiceRegistry.
    """
    router = APIRouter(prefix="/api/trust", tags=["trust"])

    @router.get("/fleet")
    def fleet(range: str = Query("7d")) -> dict[str, Any]:
        try:
            window = _parse_range_for_trust(range)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        deps = deps_factory()
        reader = _build_anomaly_reader(config.repo)
        return asyncio.run(
            _read_fleet(
                config,
                event_bus=deps.event_bus,
                bg_workers=deps.bg_workers,
                state=deps.state,
                range_td=window,
                anomaly_reader=reader,
            )
        )

    return router
