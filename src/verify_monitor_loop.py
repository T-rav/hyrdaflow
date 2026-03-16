"""Background worker loop — verification issue lifecycle completion.

Polls pending verification issues (labeled ``hydraflow-verify``) and
transitions the original issue outcome to ``MERGED`` once the verify
issue is closed by a human.  Also reconciles any stale ``VERIFY_PENDING``
or ``VERIFY_RESOLVED`` outcomes left over from earlier behaviour.
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
                        "Verify issue #%d for original #%d not found — treating as merged",
                        verify_issue,
                        original_issue,
                    )
                    self._state.record_outcome(
                        original_issue,
                        IssueOutcomeType.MERGED,
                        reason=f"Verification issue #{verify_issue} not found — auto-resolved to merged",
                        phase="verify",
                        verification_issue_number=verify_issue,
                    )
                    self._state.clear_verification_issue(original_issue)
                    resolved += 1
                    continue
                if issue.state == "closed":
                    self._state.record_outcome(
                        original_issue,
                        IssueOutcomeType.MERGED,
                        reason=f"Verification issue #{verify_issue} closed — promoted to merged",
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

        # Reconcile orphaned VERIFY_PENDING outcomes that have no verification_issues entry.
        # This must run even when pending is empty so stale outcomes are resolved.
        reconciled = self._reconcile_orphaned_outcomes(pending)

        if not pending and not reconciled:
            return None

        return {
            "checked": checked,
            "resolved": resolved,
            "reconciled": reconciled,
            "pending": len(pending) - resolved,
        }

    def _reconcile_orphaned_outcomes(self, pending: dict[int, int]) -> int:
        """Promote stale verify outcomes to MERGED.

        Handles two cases:
        1. VERIFY_PENDING with no matching verification_issues entry (orphaned).
        2. VERIFY_RESOLVED that was never promoted to MERGED.
        """
        all_outcomes = self._state.get_all_outcomes()
        pending_keys = {str(k) for k in pending}
        reconciled = 0
        stale_types = {
            IssueOutcomeType.VERIFY_PENDING,
            IssueOutcomeType.VERIFY_RESOLVED,
        }
        for key, outcome in all_outcomes.items():
            if outcome.outcome not in stale_types:
                continue
            # VERIFY_PENDING with an active verification entry is not stale
            if (
                outcome.outcome == IssueOutcomeType.VERIFY_PENDING
                and key in pending_keys
            ):
                continue
            issue_number = int(key)
            reason = (
                "Stale verify_resolved — promoted to merged"
                if outcome.outcome == IssueOutcomeType.VERIFY_RESOLVED
                else "Orphaned verify_pending — verification issue missing, promoted to merged"
            )
            try:
                self._state.record_outcome(
                    issue_number,
                    IssueOutcomeType.MERGED,
                    reason=reason,
                    phase="verify",
                )
                logger.info(
                    "Reconciled %s for issue #%d → merged",
                    outcome.outcome.value,
                    issue_number,
                )
                reconciled += 1
            except Exception:
                logger.exception(
                    "Error reconciling %s for issue #%d — skipping",
                    outcome.outcome.value,
                    issue_number,
                )
        return reconciled
