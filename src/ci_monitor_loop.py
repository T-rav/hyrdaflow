"""Background worker loop — monitor CI health on the main branch."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from ports import PRPort

logger = logging.getLogger("hydraflow.ci_monitor")


class CIMonitorLoop(BaseBackgroundLoop):
    """Watches CI status on the main branch and files issues when CI is red.

    Auto-closes the issue when CI recovers to green. Prevents duplicate
    issue creation by tracking the open CI-failure issue number.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="ci_monitor",
            config=config,
            deps=deps,
        )
        self._prs = pr_manager
        self._open_issue: int | None = None
        self._startup_check_done = False

    def _get_default_interval(self) -> int:
        return self._config.ci_monitor_interval

    async def _rehydrate_open_issue(self) -> None:
        """On first cycle, check if an open CI failure issue already exists."""
        if self._startup_check_done:
            return
        self._startup_check_done = True
        try:
            issues = await self._prs.list_issues_by_label("hydraflow-ci-failure")
            if issues:
                self._open_issue = issues[0].get("number")
                logger.info(
                    "CI monitor: rehydrated open issue #%s from previous run",
                    self._open_issue,
                )
        except Exception:
            logger.debug("CI monitor: could not rehydrate open issue", exc_info=True)

    async def _do_work(self) -> dict[str, Any] | None:
        """Check CI status and create/close issues as needed."""
        if self._config.dry_run:
            return None

        await self._rehydrate_open_issue()

        try:
            conclusion, run_url = await self._prs.get_latest_ci_status()
        except Exception:
            logger.warning("CI monitor: could not fetch CI status", exc_info=True)
            return {"error": True}

        # Empty conclusion = no runs or in-progress; treat same as green (no action)
        is_green = conclusion in ("success", "")

        if is_green:
            # CI is green — close any open failure issue
            if self._open_issue is not None:
                try:
                    await self._prs.post_comment(
                        self._open_issue,
                        "CI has recovered — auto-closing this issue.",
                    )
                    await self._prs.close_issue(self._open_issue)
                    logger.info(
                        "CI monitor: CI recovered, closed issue #%d",
                        self._open_issue,
                    )
                    self._open_issue = None
                except Exception:
                    logger.warning(
                        "CI monitor: failed to close recovery issue #%d — will retry",
                        self._open_issue,
                        exc_info=True,
                    )
            return {"status": "green"}

        # CI is red
        if self._open_issue is not None:
            # Already tracking this failure
            return {"status": "red"}

        # File a new issue
        try:
            title = f"[CI] Main branch CI is failing ({conclusion})"
            body = (
                f"## CI Failure Detected\n\n"
                f"The latest CI run on `{self._config.main_branch}` "
                f"completed with status: **{conclusion}**.\n\n"
            )
            if run_url:
                body += f"Run: {run_url}\n\n"
            body += (
                "This issue was auto-created by the CI health monitor. "
                "It will be auto-closed when CI recovers."
            )
            issue_number = await self._prs.create_issue(
                title, body, labels=["hydraflow-ci-failure"]
            )
            self._open_issue = issue_number
            logger.info(
                "CI monitor: filed issue #%d for CI failure (%s)",
                issue_number,
                conclusion,
            )
            return {"status": "red", "issue_created": issue_number}
        except Exception:
            logger.warning(
                "CI monitor: failed to create CI failure issue", exc_info=True
            )
            return {"status": "red", "error": True}
