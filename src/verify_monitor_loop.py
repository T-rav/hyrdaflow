"""Background worker loop — verification issue lifecycle completion.

Polls pending verification issues (labeled ``hydraflow-verify``) and
transitions the original issue outcome from ``VERIFY_PENDING`` to
``VERIFY_RESOLVED`` once the verify issue is closed by a human.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import IssueOutcomeType

if TYPE_CHECKING:
    from issue_fetcher import IssueFetcher
    from state import StateTracker

logger = logging.getLogger("hydraflow.verify_monitor_loop")


class VerifyMonitorLoop(BaseBackgroundLoop):
    """Watches pending verification issues and resolves them when closed."""

    def __init__(
        self,
        config: HydraFlowConfig,
        fetcher: IssueFetcher,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="verify_monitor", config=config, deps=deps)
        self._fetcher = fetcher
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.verify_monitor_interval

    async def _do_work(self) -> dict[str, Any] | None:
        pending = self._state.get_all_verification_issues()

        resolved = 0
        checked = 0
        for original_issue, verify_issue in list(pending.items()):
            try:
                issue = await self._fetcher.fetch_issue_by_number(verify_issue)
                checked += 1
                if issue is None:
                    logger.warning(
                        "Verify issue #%d for original #%d not found — treating as resolved",
                        verify_issue,
                        original_issue,
                    )
                    self._state.record_outcome(
                        original_issue,
                        IssueOutcomeType.VERIFY_RESOLVED,
                        reason=f"Verification issue #{verify_issue} not found (deleted/inaccessible)",
                        phase="verify",
                        verification_issue_number=verify_issue,
                    )
                    self._state.clear_verification_issue(original_issue)
                    resolved += 1
                    continue
                if issue.state == "closed":
                    self._state.record_outcome(
                        original_issue,
                        IssueOutcomeType.VERIFY_RESOLVED,
                        reason=f"Verification issue #{verify_issue} closed",
                        phase="verify",
                        verification_issue_number=verify_issue,
                    )
                    self._state.clear_verification_issue(original_issue)
                    logger.info(
                        "Resolved verify issue #%d for original issue #%d",
                        verify_issue,
                        original_issue,
                    )
                    resolved += 1
            except Exception:
                logger.exception(
                    "Error checking verify issue #%d for original #%d — skipping",
                    verify_issue,
                    original_issue,
                )

        # Bug B reconciliation: scan outcomes for orphaned VERIFY_PENDING entries
        # whose verification_issues mapping was cleared (e.g. manual state edit).
        orphaned = self._reconcile_orphaned_pending(pending)
        resolved += orphaned

        if not pending and resolved == 0:
            return None

        return {"checked": checked, "resolved": resolved, "pending": len(pending)}

    def _reconcile_orphaned_pending(self, active_verification: dict[int, int]) -> int:
        """Transition orphaned VERIFY_PENDING outcomes that have no verification_issues entry."""
        all_outcomes = self._state.get_all_outcomes()
        reconciled = 0
        for key, outcome in all_outcomes.items():
            if outcome.outcome != IssueOutcomeType.VERIFY_PENDING:
                continue
            issue_number = int(key)
            if issue_number in active_verification:
                continue
            # Orphaned: outcome is VERIFY_PENDING but no verification_issues entry exists
            self._state.record_outcome(
                issue_number,
                IssueOutcomeType.VERIFY_RESOLVED,
                reason="Orphaned verify_pending — no active verification issue found",
                phase="verify",
                verification_issue_number=outcome.verification_issue_number,
            )
            logger.info(
                "Reconciled orphaned verify_pending for issue #%d",
                issue_number,
            )
            reconciled += 1
        return reconciled
