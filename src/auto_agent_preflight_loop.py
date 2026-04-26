"""AutoAgentPreflightLoop — intercepts hitl-escalation issues for auto-resolution.

Spec §1–§11. Polls hitl-escalation items, runs PreflightAgent in attempt
sequence, applies PreflightDecision to the result, records audit + spend.

Layered kill-switch (ADR-0049): in-body enabled_cb gate at top of _do_work.
Sequential single-issue-per-tick. Daily-budget gate. Sub-label deny-list.

Pipeline (poll → context → agent → decision → audit) lands in Task 11.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.auto_agent_preflight")


class AutoAgentPreflightLoop(BaseBackgroundLoop):
    """Intercepts hitl-escalation issues for auto-agent pre-flight."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: Any,  # StateTracker
        pr_manager: Any,  # PRPort
        wiki_store: Any | None,
        audit_store: Any,  # PreflightAuditStore
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="auto_agent_preflight",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._prs = pr_manager
        self._wiki_store = wiki_store
        self._audit_store = audit_store

    def _get_default_interval(self) -> int:
        return self._config.auto_agent_preflight_interval

    async def _do_work(self) -> dict[str, Any] | None:
        # ADR-0049 in-body kill-switch gate (universal mandate).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Daily-budget gate (None = unlimited).
        cap = self._config.auto_agent_daily_budget_usd
        if cap is not None:
            today = datetime.now(UTC).date().isoformat()
            spend = self._state.get_auto_agent_daily_spend(today)
            if spend >= cap:
                return {"status": "budget_exceeded", "spend_usd": spend, "cap_usd": cap}

        # Pipeline lands in Task 11.
        return {"status": "ok", "issues_processed": 0}
