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

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult
from trust_fleet_anomaly_detectors import (
    TRUST_LOOP_WORKERS,
    detect_cost_spike,
    detect_issues_per_hour,
    detect_repair_ratio,
    detect_staleness,
    detect_tick_error_ratio,
)

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
  ],
  "escape_closure": {                       # spec §12.4 success metric
    "opened": <int>,                          # escape issues opened in window
    "closed_within_7d": <int>,                # closed within 7 days of open
    "ratio": <float>,                         # closed_within_7d / opened
    "target": 0.95                            # spec §12.4 target ratio
  }
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
        pr_manager: PRManager,
        dedup: DedupStore,
        event_bus: EventBus,
        deps: LoopDeps,
        bg_workers: BGWorkerManager | None = None,
    ) -> None:
        super().__init__(
            worker_name="trust_fleet_sanity",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        # BGWorkerManager is constructed *after* loops in the orchestrator
        # (it takes the loop registry). Accept None at construction time
        # and inject post-hoc via ``set_bg_workers``.
        self._bg_workers: BGWorkerManager | None = bg_workers
        self._pr = pr_manager
        self._dedup = dedup
        self._source_bus = event_bus  # separate handle for load_events_since

    def set_bg_workers(self, bg_workers: BGWorkerManager) -> None:
        """Late-binding for the post-ctor BGWorkerManager wiring."""
        self._bg_workers = bg_workers

    def _get_default_interval(self) -> int:
        return self._config.trust_fleet_sanity_interval

    async def _do_work(self) -> WorkCycleResult:
        """Task 6: scan trust loops, file one-attempt escalations on breaches."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        now = datetime.now(UTC)
        window_metrics = await self._collect_window_metrics()
        heartbeats = self._state.get_worker_heartbeats() or {}
        enabled_map = dict(getattr(self._bg_workers, "worker_enabled", {}) or {})
        cost_reader = self._load_cost_reader()

        dedup = set(self._dedup.get() or set())
        filed = 0
        anomalies: list[dict[str, Any]] = []

        cfg = self._config
        # Scan the union of known trust loops + any workers seen in
        # event metrics or heartbeats — a loop with events but not in
        # the hardcoded tuple (e.g. ci_monitor while rolling out) is
        # still worth flagging. Iteration order is stable for tests.
        seen_workers: list[str] = []
        seen_set: set[str] = set()
        for name in (
            *TRUST_LOOP_WORKERS,
            *sorted(window_metrics.keys()),
            *sorted(heartbeats.keys()),
        ):
            if name in seen_set:
                continue
            seen_set.add(name)
            seen_workers.append(name)

        for worker in seen_workers:
            metrics = window_metrics.get(worker, _empty_metrics_bucket())
            per_worker_breaches: list[tuple[str, dict[str, Any]]] = []

            breached, details = detect_issues_per_hour(
                worker,
                metrics,
                threshold=cfg.loop_anomaly_issues_per_hour,
            )
            if breached:
                per_worker_breaches.append(("issues_per_hour", details))

            breached, details = detect_repair_ratio(
                worker,
                metrics,
                threshold=cfg.loop_anomaly_repair_ratio,
            )
            if breached:
                per_worker_breaches.append(("repair_ratio", details))

            breached, details = detect_tick_error_ratio(
                worker,
                metrics,
                threshold=cfg.loop_anomaly_tick_error_ratio,
            )
            if breached:
                per_worker_breaches.append(("tick_error_ratio", details))

            hb = heartbeats.get(worker) or {}
            last_run_iso = hb.get("last_run") if isinstance(hb, dict) else None
            bg = self._bg_workers
            interval_s = (
                int(bg.get_interval(worker))
                if bg is not None and hasattr(bg, "get_interval")
                else 86400
            )
            is_enabled = bool(enabled_map.get(worker, True))
            breached, details = detect_staleness(
                worker,
                last_run_iso=last_run_iso,
                interval_s=interval_s,
                multiplier=cfg.loop_anomaly_staleness_multiplier,
                is_enabled=is_enabled,
                now=now,
            )
            if breached:
                per_worker_breaches.append(("staleness", details))

            breached, details = detect_cost_spike(
                worker,
                reader=cost_reader,
                threshold=cfg.loop_anomaly_cost_spike_ratio,
            )
            if breached:
                per_worker_breaches.append(("cost_spike", details))

            for kind, det in per_worker_breaches:
                key = f"trust_fleet_sanity:{kind}:{worker}"
                if key in dedup:
                    continue
                attempts = self._state.inc_trust_fleet_sanity_attempts(
                    f"{kind}:{worker}",
                )
                if attempts >= _MAX_ATTEMPTS:
                    issue_no = await self._file_anomaly(worker, kind, det)
                    anomalies.append(
                        {
                            "worker": worker,
                            "kind": kind,
                            "issue_number": issue_no,
                            "details": det,
                        }
                    )
                    filed += 1
                    # Only add to dedup AFTER the escalation fires — otherwise
                    # raising ``_MAX_ATTEMPTS`` breaks the retry window because
                    # every breach is added to dedup on first detection and
                    # ``inc_trust_fleet_sanity_attempts`` never increments again
                    # until reconcile-on-close clears the key.
                    dedup.add(key)
                    self._dedup.set_all(dedup)

        self._state.set_trust_fleet_sanity_last_run(now.isoformat())
        self._emit_trace(t0, anomalies=len(anomalies))
        return {
            "status": "ok",
            "anomalies": len(anomalies),
            "workers_scanned": len(seen_workers),
            "filed": filed,
        }

    async def _file_anomaly(
        self,
        worker: str,
        kind: str,
        details: dict[str, Any],
    ) -> int:
        title = f"HITL: trust-loop anomaly — {worker} {kind}"
        detail_lines = "\n".join(
            f"- `{k}`: `{v}`" for k, v in sorted(details.items()) if k not in {"worker"}
        )
        body = (
            f"## Trust-loop anomaly (`{kind}`) — `{worker}`\n\n"
            f"`TrustFleetSanityLoop` detected `{kind}` threshold breach for "
            f"the `{worker}` loop. Per spec §12.1 the anomaly is the "
            f"escalation — one-attempt, no retry budget.\n\n"
            f"### Detector output\n{detail_lines}\n\n"
            f"### Operator playbook\n"
            f"1. Flip `{worker}`'s kill-switch in the **System** tab if the "
            f"loop is actively misbehaving (spec §12.2).\n"
            f"2. Investigate via the **Diagnostics → Trust Fleet** sub-tab "
            f"(spec §12.3) — click the loop for recent runs + job breakdowns.\n"
            f"3. Close this issue once resolved. Closing clears "
            f"`trust_fleet_sanity:{kind}:{worker}` from the dedup set so the "
            f"detector is free to re-fire on the next drift (spec §3.2).\n\n"
            f"_Auto-filed by HydraFlow `trust_fleet_sanity` (spec §12.1)._"
        )
        return await self._pr.create_issue(
            title,
            body,
            ["hitl-escalation", "trust-loop-anomaly"],
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys for escalations whose HITL issue is now closed.

        Polls ``gh issue list`` for closed ``hitl-escalation`` +
        ``trust-loop-anomaly`` issues authored by the bot; for each
        match in the current dedup set, drop the key and zero the
        per-anomaly attempt counter so the detector is free to re-fire
        on the next drift (spec §3.2).
        """
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
            "--label",
            "hitl-escalation",
            "--label",
            "trust-loop-anomaly",
            "--author",
            "@me",
            "--limit",
            "200",
            "--json",
            "title",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
        except Exception:  # noqa: BLE001
            logger.debug("gh issue list failed", exc_info=True)
            return
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get() or set()
        keep = set(current)
        any_change = False
        for issue in closed:
            title = str(issue.get("title", ""))
            m = _TITLE_RE.search(title)
            if not m:
                continue
            worker = m.group("worker")
            kind = m.group("kind")
            key = f"trust_fleet_sanity:{kind}:{worker}"
            if key in keep:
                keep.discard(key)
                self._state.clear_trust_fleet_sanity_attempts(f"{kind}:{worker}")
                any_change = True
        if any_change:
            self._dedup.set_all(keep)

    def _emit_trace(self, t0: float, *, anomalies: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        try:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            emit_loop_subprocess_trace(
                loop=self._worker_name,
                command=["trust_fleet_sanity", "tick"],
                exit_code=0,
                duration_ms=duration_ms,
                stderr_excerpt=f"anomalies={anomalies}",
            )
        except Exception:  # noqa: BLE001
            logger.debug("trace emission failed", exc_info=True)

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
                "trust_fleet_cost_reader unavailable — cost-spike detector disabled",
            )
            return None
        if module is None:
            return None
        return module
