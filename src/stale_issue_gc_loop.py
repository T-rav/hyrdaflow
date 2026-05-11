"""Background worker loop — auto-close stale HITL escalation issues.

Scope: open issues carrying ``self._config.hitl_label`` (i.e. unresolved
human-in-the-loop escalations). Posts a farewell comment, then closes;
caps at 10 closes/cycle to avoid GitHub rate-limiting. The complement —
stale *general* issues with no HF lifecycle label — is owned by
``stale_issue_loop``, which has its own per-tag thresholds and state
tracking. The two loops share only the ``BaseBackgroundLoop`` framework;
zero business-logic overlap.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.stale_issue_gc")

# Maximum issues to close per cycle to avoid rate-limiting.
_MAX_CLOSE_PER_CYCLE = 10


class StaleIssueGCLoop(BaseBackgroundLoop):
    """Periodically closes HITL issues with no activity beyond a threshold.

    Queries GitHub for open issues with the HITL label, checks their
    ``updated_at`` timestamp, and auto-closes those that have been
    inactive for longer than ``stale_issue_threshold_days``.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="stale_issue_gc",
            config=config,
            deps=deps,
        )
        self._prs = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.stale_issue_gc_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Run one GC cycle: find and close stale HITL issues."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        if self._config.dry_run:
            return None

        threshold = timedelta(days=self._config.stale_issue_threshold_days)
        cutoff = datetime.now(UTC) - threshold
        hitl_labels = self._config.hitl_label

        closed = 0
        skipped = 0
        errors = 0

        for label in hitl_labels:
            if self._stop_event.is_set():
                break
            try:
                issues = await self._prs.list_issues_by_label(label)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "Stale GC: failed to list issues for label %s",
                    label,
                    exc_info=True,
                )
                errors += 1
                continue

            for issue in issues:
                if self._stop_event.is_set() or closed >= _MAX_CLOSE_PER_CYCLE:
                    break

                issue_number = issue.get("number", 0)
                if not issue_number:
                    continue

                try:
                    updated_at_str = await self._prs.get_issue_updated_at(issue_number)
                    if not updated_at_str:
                        skipped += 1
                        continue
                    updated_at = datetime.fromisoformat(updated_at_str)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=UTC)

                    if updated_at < cutoff:
                        comment = (
                            "This issue has been auto-closed due to no activity "
                            f"for {self._config.stale_issue_threshold_days} days. "
                            "If the issue is still relevant, please reopen it "
                            "with additional context."
                        )
                        await self._prs.post_comment(issue_number, comment)
                        await self._prs.close_issue(issue_number)
                        closed += 1
                        logger.info(
                            "Stale GC: auto-closed issue #%d (last activity: %s)",
                            issue_number,
                            updated_at_str,
                        )
                    else:
                        skipped += 1
                except Exception as exc:
                    reraise_on_credit_or_bug(exc)
                    logger.warning(
                        "Stale GC: error processing issue #%d — skipping",
                        issue_number,
                        exc_info=True,
                    )
                    errors += 1

        return {"closed": closed, "skipped": skipped, "errors": errors}
