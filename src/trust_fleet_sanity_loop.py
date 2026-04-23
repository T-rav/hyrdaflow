"""TrustFleetSanityLoop — meta-observability for the trust loop fleet (spec §12.1).

Watches the nine §4.1–§4.9 trust loops. On any of five anomaly
conditions (thresholds config-driven, operator-tunable), files a
``hitl-escalation`` issue with label ``trust-loop-anomaly``. One-attempt
escalation — the anomaly IS the escalation, not a repair attempt.

Dead-man-switch: ``HealthMonitorLoop`` watches *this* loop's
heartbeat; when the sanity loop itself stops ticking, HealthMonitor
files ``sanity-loop-stalled``. Recursion bounded at one meta-layer
(spec §12.1 "Bounds of meta-observability").

Kill-switch: ``LoopDeps.enabled_cb("trust_fleet_sanity")`` — **no
``trust_fleet_sanity_enabled`` config field** (spec §12.2).

Read-side surface is `/api/trust/fleet?range=7d|30d` — schema
documented in :data:`FLEET_ENDPOINT_SCHEMA` below. Route impl is owned
by Plan 6b (§4.11 factory-cost work).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult
from trust_fleet_anomaly_detectors import TRUST_LOOP_WORKERS

if TYPE_CHECKING:
    from bg_worker_manager import BGWorkerManager
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from events import EventBus
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.trust_fleet_sanity_loop")


FLEET_ENDPOINT_SCHEMA: str = """
/api/trust/fleet response schema (spec §12.1; owned by Plan 6b).

Request: GET /api/trust/fleet?range=7d|30d

Response JSON:

{
  "range": "7d" | "30d",
  "generated_at": "<iso8601 UTC>",
  "loops": [
    {
      "worker_name": "<string>",         # e.g. "ci_monitor", "rc_budget"
      "enabled": <bool>,                  # from BGWorkerManager.is_enabled
      "interval_s": <int>,                # effective interval (dynamic or default)
      "last_tick_at": "<iso8601>" | null, # from worker_heartbeats
      "ticks_total": <int>,               # window-scoped count from event log
      "ticks_errored": <int>,             # status=="error" in the window
      "issues_filed_total": <int>,        # sum of details.filed over the window
      "issues_closed_total": <int>,       # sum from `EventType.ISSUE_CLOSED` events (best-effort; 0 if absent)
      "issues_open_escalated": <int>,     # currently-open issues the loop filed with hitl-escalation label
      "repair_attempts_total": <int>,     # sum of details.repaired + details.failed
      "repair_successes_total": <int>,    # sum of details.repaired
      "repair_failures_total": <int>,     # sum of details.failed
      "loop_specific": {                  # optional per-loop metrics; see §12.1 examples
        "reverts_merged": <int>,          # staging_bisect
        "cases_added": <int>,             # corpus_learning
        "cassettes_refreshed": <int>,     # contract_refresh
        "principles_regressions": <int>,  # principles_audit
        ...
      }
    },
    ...
  ],
  "anomalies_recent": [
    {
      "kind": "issues_per_hour" | "repair_ratio" | "tick_error_ratio"
            | "staleness" | "cost_spike",
      "worker": "<string>",
      "filed_at": "<iso8601>",
      "issue_number": <int>,
      "details": {<detector-specific>}
    }
  ]
}

Implementation notes for Plan 6b:
- Read `ticks_total`/`ticks_errored`/`issues_filed_total` by calling
  `event_bus.load_events_since(now - range)` and tallying
  `EventType.BACKGROUND_WORKER_STATUS` entries where `data.worker`
  matches each loop.
- Read `last_tick_at`/`enabled`/`interval_s` from
  `state.get_worker_heartbeats()` + `bg_workers.worker_enabled` +
  `bg_workers.get_interval`.
- `anomalies_recent` is populated from the last-24h `hitl-escalation`+
  `trust-loop-anomaly` issues authored by the bot (via `gh issue list`).
- Loop-specific metrics are loop-maintained counter fields TBD by each
  sibling loop; default `0` when unreported.
"""

_MAX_ATTEMPTS = 1  # spec §12.1 — the anomaly IS the escalation.
_HOUR_SECONDS = 3600
_DAY_SECONDS = 86_400
_ANOMALY_KINDS: tuple[str, ...] = (
    "issues_per_hour",
    "repair_ratio",
    "tick_error_ratio",
    "staleness",
    "cost_spike",
)

_TITLE_RE = re.compile(
    r"HITL: trust-loop anomaly — (?P<worker>[\w_]+) (?P<kind>[\w_]+)$",
)


def _parse_iso(value: str | None) -> datetime | None:
    """Tolerant ISO-8601 parser — returns None on anything unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _empty_metrics_bucket() -> dict[str, Any]:
    return {
        "ticks_total": 0,
        "ticks_errored": 0,
        "issues_filed_day": 0,
        "issues_filed_hour": 0,
        "repaired_day": 0,
        "failed_day": 0,
        "last_seen_iso": None,
    }


class TrustFleetSanityLoop(BaseBackgroundLoop):
    """Meta-observability loop — watches the nine trust loops (spec §12.1)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        bg_workers: BGWorkerManager,
        pr_manager: PRManager,
        dedup: DedupStore,
        event_bus: EventBus,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="trust_fleet_sanity",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._bg_workers = bg_workers
        self._pr = pr_manager
        self._dedup = dedup
        self._source_bus = event_bus  # separate handle for load_events_since

    def _get_default_interval(self) -> int:
        return self._config.trust_fleet_sanity_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — Task 5 replaces with the full tick."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        await self._reconcile_closed_escalations()
        # Skeleton returns without running detectors (Task 5 fills this in).
        return {"status": "ok", "anomalies": 0}

    async def _reconcile_closed_escalations(self) -> None:
        """Task 5."""
        return None

    # ------------------------------------------------------------------
    # Task 4 — metrics readers
    # ------------------------------------------------------------------

    async def _collect_window_metrics(self) -> dict[str, dict[str, Any]]:
        """Walk the event log's last 24h and tally per-worker counters.

        Returns a dict keyed by worker_name → metric dict with:
        ``ticks_total``, ``ticks_errored``, ``issues_filed_day``,
        ``issues_filed_hour``, ``repaired_day``, ``failed_day``,
        ``last_seen_iso``.

        The dict is pre-seeded with :data:`TRUST_LOOP_WORKERS` so every
        known trust loop has a zero-valued bucket even when no events
        have been emitted yet (Task 5 detectors rely on the presence of
        every known worker). Workers outside the registry but present
        in the event stream are still accumulated — the dashboard
        (Plan 6b) surfaces them too.
        """
        now = datetime.now(UTC)
        day_cutoff = now - timedelta(seconds=_DAY_SECONDS)
        hour_cutoff = now - timedelta(seconds=_HOUR_SECONDS)

        events = await self._load_events_since(day_cutoff)

        out: dict[str, dict[str, Any]] = {
            w: _empty_metrics_bucket() for w in TRUST_LOOP_WORKERS
        }
        # Local import to match the event-type enum without a module-level
        # cycle (events.py imports ripple through several subsystems).
        from events import EventType  # noqa: PLC0415

        for ev in events:
            if getattr(ev, "type", None) != EventType.BACKGROUND_WORKER_STATUS:
                continue
            data = getattr(ev, "data", {}) or {}
            if not isinstance(data, dict):
                continue
            worker = data.get("worker")
            if not isinstance(worker, str) or not worker:
                continue
            ts_raw = getattr(ev, "timestamp", None)
            ts = _parse_iso(ts_raw) if isinstance(ts_raw, str) else None
            if ts is None or ts < day_cutoff:
                continue
            bucket = out.setdefault(worker, _empty_metrics_bucket())
            bucket["ticks_total"] += 1
            if data.get("status") == "error":
                bucket["ticks_errored"] += 1
            details = data.get("details") or {}
            if not isinstance(details, dict):
                details = {}
            filed = int(details.get("filed", 0) or 0)
            bucket["issues_filed_day"] += filed
            if ts >= hour_cutoff:
                bucket["issues_filed_hour"] += filed
            bucket["repaired_day"] += int(details.get("repaired", 0) or 0)
            bucket["failed_day"] += int(details.get("failed", 0) or 0)
            seen = bucket["last_seen_iso"]
            if seen is None or (isinstance(ts_raw, str) and ts_raw > seen):
                bucket["last_seen_iso"] = ts_raw
        return out

    async def _load_events_since(self, since: datetime) -> list[Any]:
        """Wrap ``EventBus.load_events_since`` with robust defaults.

        Returns ``[]`` when the bus has no ``event_log`` attached (tests
        often pass a vanilla ``EventBus()``) or when the call raises.
        """
        try:
            loaded = await self._source_bus.load_events_since(since)
        except Exception:  # noqa: BLE001
            logger.debug("load_events_since failed", exc_info=True)
            return []
        return loaded or []

    def _load_cost_reader(self) -> Any | None:
        """Lazy-import the §4.11 cost reader.

        Returns the module object (which must expose
        ``get_loop_cost_today(worker) -> float`` and
        ``get_loop_cost_30d_median(worker) -> float``) or ``None`` if
        absent. Absence is not an error — Plan 6b lands the module.
        """
        try:
            import trust_fleet_cost_reader as module  # noqa: PLC0415
        except ImportError:
            logger.info(
                "trust_fleet_cost_reader unavailable — cost-spike detector disabled"
            )
            return None
        if module is None:
            return None
        return module
