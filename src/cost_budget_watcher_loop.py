"""CostBudgetWatcherLoop — daily cost-cap kill-switch.

Polls the rolling-24h spend total. When it exceeds
``config.daily_cost_budget_usd``, disables a curated set of caretaker
loops via ``BGWorkerManager.set_enabled``. When the rolling-24h total
drops back below the cap (e.g. at UTC midnight), re-enables only the
loops the watcher itself killed — operator-disabled loops are preserved.

Default behavior: ``daily_cost_budget_usd = None`` → no-op every tick.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the design at docs/superpowers/specs/2026-04-26-psh-onboarding-and-cost-cap-design.md.

Kill switch: HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER=1.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import WorkCycleResult


def build_rolling_24h(config: HydraFlowConfig) -> dict[str, Any]:
    """Lazy wrapper around dashboard_routes._cost_rollups.build_rolling_24h.

    Importing dashboard_routes at module load time triggers a circular
    import (matches the pattern at src/report_issue_loop.py:43-60).
    The wrapper is the patch target for tests.
    """
    from dashboard_routes._cost_rollups import (  # noqa: PLC0415
        build_rolling_24h as _impl,
    )

    return _impl(config)


logger = logging.getLogger(__name__)

_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER"
_ISSUE_TITLE = "[cost-budget] daily cap exceeded"
# Curated list of loops the watcher gates. The watcher itself is NOT in
# this set — it must keep running to detect recovery. Pipeline loops
# (triage/plan/implement/review) are also out — their gating is via
# their own kill-switch convention; the cost cap is for caretaker fan-out.
_TARGET_WORKERS = (
    "dependabot_merge",
    "security_patch",
    "ci_monitor",
    "stale_issue",
    "stale_issue_gc",
    "pr_unsticker",
    "epic_monitor",
    "epic_sweeper",
    "principles_audit",
    "repo_wiki",
    "wiki_rot_detector",
    "diagram_loop",
    "pricing_refresh",
    "auto_agent_preflight",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    "flake_tracker",
    "trust_fleet_sanity",
    "contract_refresh",
    "corpus_learning",
    "code_grooming",
    "retrospective",
)


class CostBudgetWatcherLoop(BaseBackgroundLoop):
    """Daily cost-cap kill-switch for caretaker loops."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager: Any,  # PRPort
        state: Any,  # StateTracker
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="cost_budget_watcher",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._state = state
        self._bg_workers: Any = None  # injected post-construction

    def set_bg_workers(self, bg_workers: Any) -> None:
        """Inject BGWorkerManager post-construction.

        Chicken-and-egg: BGWorkerManager takes the loop registry as a
        constructor input, so loops that need bg_workers get it injected
        after both are built. Mirrors HealthMonitorLoop / TrustFleetSanityLoop.
        """
        self._bg_workers = bg_workers

    def _get_default_interval(self) -> int:
        # 5 minutes; configurable via HydraFlowConfig.
        return 300

    async def _do_work(self) -> WorkCycleResult:
        if not self._config.cost_budget_watcher_loop_enabled:
            return {"status": "config_disabled"}
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return {"skipped": "kill_switch"}

        cap = self._config.daily_cost_budget_usd
        if cap is None:
            # Unlimited mode — nothing to watch.
            return {"action": "unlimited"}

        try:
            rolling = await asyncio.to_thread(build_rolling_24h, self._config)
        except Exception:  # noqa: BLE001 — telemetry shouldn't kill the gate
            logger.warning(
                "CostBudgetWatcher: rolling-24h compute failed", exc_info=True
            )
            # On unknown cost state, do NOT take action — neither kill nor recover.
            return {"action": "unknown"}

        total = float(rolling.get("total", {}).get("cost_usd", 0.0))
        previously_killed: set[str] = set(
            self._state.get_cost_budget_killed_workers() or set()
        )

        if total > cap:
            killed = await self._kill_caretakers(previously_killed)
            await self._file_issue(cap=cap, total=total)
            return {
                "action": "killed",
                "cap": cap,
                "total": total,
                "killed_count": len(killed),
            }

        if previously_killed:
            await self._reenable_caretakers(previously_killed)
            return {
                "action": "recovered",
                "cap": cap,
                "total": total,
                "reenabled_count": len(previously_killed),
            }

        return {"action": "ok", "cap": cap, "total": total}

    async def _kill_caretakers(self, previously_killed: set[str]) -> set[str]:
        """Disable every _TARGET_WORKERS member; persist the set we touched."""
        newly_killed: set[str] = set()
        for name in _TARGET_WORKERS:
            try:
                if self._bg_workers.is_enabled(name):
                    self._bg_workers.set_enabled(name, False)
                    newly_killed.add(name)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "CostBudgetWatcher: failed to disable %s", name, exc_info=True
                )
        # Union with previously_killed so manual re-enables don't escape recovery.
        full = previously_killed | newly_killed
        self._state.set_cost_budget_killed_workers(full)
        return newly_killed

    async def _reenable_caretakers(self, killed: set[str]) -> None:
        """Re-enable only the loops we previously killed.

        Operator-override safety is handled at KILL time, not here:
        ``_kill_caretakers`` only adds a worker to ``cost_budget_killed_workers``
        if it was enabled before our kill (`bg_workers.is_enabled` returned
        True). Workers the operator had already disabled never enter our
        killed-set, so we never claim authorship of them and never
        re-enable them on recovery.

        **Known gotcha:** if the operator manually disables a worker
        AFTER we killed it (i.e., during the kill window), recovery will
        still re-enable it. There's no clean way to detect that without
        an event log of (name, source, timestamp) for every set_enabled
        call. Documented in dark-factory.md as the cost-watcher
        operator-override gotcha.
        """
        for name in killed:
            try:
                self._bg_workers.set_enabled(name, True)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "CostBudgetWatcher: failed to re-enable %s", name, exc_info=True
                )
        self._state.set_cost_budget_killed_workers(set())

    async def _file_issue(self, *, cap: float, total: float) -> None:
        existing = await self._pr_manager.find_existing_issue(_ISSUE_TITLE)
        if existing:
            return
        body = (
            f"HydraFlow's daily LLM spend exceeded the configured cap.\n\n"
            f"- **Cap:** ${cap:.2f}\n"
            f"- **Rolling-24h spend:** ${total:.2f}\n\n"
            f"All caretaker loops are disabled until the rolling-24h figure "
            f"drops below the cap (typically at UTC midnight). The watcher will "
            f"automatically re-enable them and add a comment when that happens.\n\n"
            f"To raise or remove the cap, set "
            f"`HYDRAFLOW_DAILY_COST_BUDGET_USD` to a higher value (or unset for unlimited)."
        )
        await self._pr_manager.create_issue(
            title=_ISSUE_TITLE,
            body=body,
            labels=["hydraflow-find", "cost-budget"],
        )
