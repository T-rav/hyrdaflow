"""LabelDriftWatcherLoop — periodic detect-and-reconcile of cross-entity
issue/PR label drift.

Per ADR-0056. The loop scans for drift via :meth:`PRPort.find_label_drift`
and reconciles each pair by per-entity ``swap_pipeline_labels`` calls
(mirroring the Phase D split-call pattern: issue gets one label, PR gets
``hydraflow-review``).

Pattern reference: ``src/memory_backlog_loop.py`` (canonical caretaker
loop). Same shape: tick logic in ``_do_work``, kwargs-only constructor,
ADR-0049 in-body kill-switch gate via ``self._enabled_cb``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import LabelDrift, WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from ports import PRPort

logger = logging.getLogger("hydraflow.label_drift_watcher_loop")


class LabelDriftWatcherLoop(BaseBackgroundLoop):
    """Periodic scan for cross-entity label drift; reconcile via two
    ``swap_pipeline_labels`` calls (issue target may differ from PR target
    across stages).
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="label_drift_watcher",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.label_drift_watcher_interval

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.label_drift_watcher_loop_enabled:
            return {"status": "config_disabled"}

        drift = await self._prs.find_label_drift()
        reconciled = 0
        for d in drift:
            try:
                await self._reconcile(d)
                reconciled += 1
            except Exception:
                logger.warning(
                    "label_drift_watcher: reconcile failed for issue #%d / PR #%d",
                    d.issue,
                    d.pr,
                    exc_info=True,
                )
        return {"detected": len(drift), "reconciled": reconciled}

    async def _reconcile(self, d: LabelDrift) -> None:
        """Apply per-stage labels mirroring Phase D's split-call pattern.

        - ``pr_ahead_of_issue``: issue lags at ready/plan; pull it forward
          to ``hydraflow-review`` to match the PR's stage. PR label stays.
        - ``pr_at_pre_pr_stage``: PR has commits but a pre-PR label
          (ready/plan/find); push the PR forward to ``hydraflow-review``.
          Issue label stays.
        """
        if d.kind == "pr_ahead_of_issue":
            await self._prs.swap_pipeline_labels(d.issue, "hydraflow-review")
            moved_clause = (
                f"Issue #{d.issue} moved from `{d.issue_label}` to "
                f"`hydraflow-review` to match PR #{d.pr} (which was already "
                f"at `{d.pr_label}`)."
            )
        else:  # pr_at_pre_pr_stage
            await self._prs.swap_pipeline_labels(d.pr, "hydraflow-review")
            moved_clause = (
                f"PR #{d.pr} moved from `{d.pr_label}` to `hydraflow-review` "
                f"to match issue #{d.issue} (which was already at "
                f"`{d.issue_label}`)."
            )

        await self._prs.post_comment(
            d.issue,
            (
                f"**LabelDriftWatcher** reconciled label drift "
                f"(kind=`{d.kind}`). {moved_clause}\n\n"
                "---\n*Automated by HydraFlow Label Drift Watcher (ADR-0056)*"
            ),
        )
        logger.info(
            "label_drift_watcher: reconciled issue #%d / PR #%d (kind=%s)",
            d.issue,
            d.pr,
            d.kind,
        )
