"""RCBudgetLoop — 4h RC CI wall-clock regression detector (spec §4.8).

Reads the last 30 days of ``rc-promotion-scenario.yml`` runs via ``gh
run list``, extracts per-run wall-clock duration, and emits a
``hydraflow-find`` + ``rc-duration-regression`` issue when the newest
run trips either:

- *Gradual bloat*: ``current_s >= rc_budget_threshold_ratio *
  rolling_median`` (default ratio ``1.5``).
- *Sudden spike*: ``current_s >= rc_budget_spike_ratio * max(recent-5,
  excluding current)`` (default ratio ``2.0``).

Signals are independent; both may fire on the same tick (two distinct
dedup keys). After 3 unresolved attempts per signal the loop files a
``hitl-escalation`` + ``rc-duration-stuck`` issue. Dedup keys clear on
escalation-close per spec §3.2.

Kill-switch: ``LoopDeps.enabled_cb("rc_budget")`` — **no
``rc_budget_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.rc_budget_loop")

_MAX_ATTEMPTS = 3
_WINDOW_DAYS = 30
_HISTORY_CAP = 60
_RECENT_N = 5
_MIN_HISTORY = 5
_WORKFLOW = "rc-promotion-scenario.yml"


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (allowing trailing ``Z``); return None on err."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RCBudgetLoop(BaseBackgroundLoop):
    """Detects RC wall-clock bloat via median + spike signals (spec §4.8)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="rc_budget",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.rc_budget_interval

    async def _do_work(self) -> WorkCycleResult:
        """Skeleton — Task 5 replaces with the full tick."""
        await self._reconcile_closed_escalations()
        runs = await self._fetch_recent_runs()
        if len(runs) < _MIN_HISTORY:
            return {"status": "warmup", "runs_seen": len(runs)}
        return {"status": "noop", "runs_seen": len(runs)}

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Fetch last 30 days of completed RC runs with per-run wall-clock."""
        cmd = [
            "gh",
            "run",
            "list",
            "--repo",
            self._config.repo,
            "--workflow",
            _WORKFLOW,
            "--limit",
            "100",
            "--status",
            "completed",
            "--json",
            "databaseId,url,conclusion,createdAt,updatedAt,startedAt",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "gh run list exit=%d: %s",
                proc.returncode,
                stderr.decode(errors="replace")[:400],
            )
            return []
        try:
            raw = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return []
        cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
        out: list[dict[str, Any]] = []
        for run in raw:
            created = _parse_iso(run.get("createdAt"))
            started = _parse_iso(run.get("startedAt") or run.get("createdAt"))
            updated = _parse_iso(run.get("updatedAt"))
            if not created or not started or not updated or created < cutoff:
                continue
            out.append(
                {
                    **run,
                    "duration_s": max(0, int((updated - started).total_seconds())),
                }
            )
        out.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        return out[:_HISTORY_CAP]

    def _compute_baselines(
        self, runs: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Return ``(current, {rolling_median, recent_max})`` excluding current."""
        current = max(runs, key=lambda r: r.get("createdAt", ""))
        others = [r for r in runs if r.get("databaseId") != current.get("databaseId")]
        others.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        durations = [int(r["duration_s"]) for r in others]
        recent = durations[:_RECENT_N]
        return current, {
            "rolling_median": (int(statistics.median(durations)) if durations else 0),
            "recent_max": max(recent) if recent else 0,
        }

    async def _reconcile_closed_escalations(self) -> None:
        """Task 5."""
        return None
