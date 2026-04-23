"""Staging-red attribution bisect loop (spec §4.3).

Polls ``StateTracker.last_rc_red_sha`` every ``staging_bisect_interval``
seconds. When the red SHA changes, the loop:

1. Flake-filters the red (Task 10).
2. Bisects between ``last_green_rc_sha`` and ``current_red_rc_sha``
   (Task 12).
3. Attributes the first-bad commit to its originating PR (Task 14).
4. Enforces the second-revert-in-cycle guardrail (Task 16).
5. Files an auto-revert PR (Task 17) and a retry issue (Task 19).
6. Watchdogs the next RC cycle for outcome verification (Task 20).

Trigger mechanism: state-tracker poll (not an event bus). Matches
HydraFlow's existing cadence-style loops; no new event infra.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_bisect")


class StagingBisectLoop(BaseBackgroundLoop):
    """Watchdog that reacts to RC-red state transitions. See ADR-0042 §4.3."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker,
    ) -> None:
        super().__init__(worker_name="staging_bisect", config=config, deps=deps)
        self._prs = prs
        self._state = state
        # In-memory high-water mark of RC-red SHAs that have already been
        # processed (or skipped as flakes, or escalated). Persisted via
        # DedupStore in Task 9 so a crash-restart does not re-process.
        self._last_processed_rc_red_sha: str = ""

    def _get_default_interval(self) -> int:
        return self._config.staging_bisect_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        red_sha = self._state.get_last_rc_red_sha()
        if not red_sha:
            return {"status": "no_red"}

        if red_sha == self._last_processed_rc_red_sha:
            return {"status": "already_processed", "sha": red_sha}

        # Real work lands in Tasks 10–22. Skeleton just marks-as-seen so
        # the skeleton tests pass.
        logger.info("StagingBisectLoop: red SHA %s — skeleton no-op", red_sha)
        self._last_processed_rc_red_sha = red_sha
        return {"status": "seen", "sha": red_sha}
