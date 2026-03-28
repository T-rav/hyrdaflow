"""Background worker loop — monitor CI health on the main branch."""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from pr_manager import PRManager

logger = logging.getLogger("hydraflow.ci_monitor")


class CIMonitorLoop(BaseBackgroundLoop):
    """Watches CI status on the main branch and files issues when CI is red.

    Auto-closes the issue when CI recovers to green. Prevents duplicate
    issue creation by tracking the open CI-failure issue number.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="ci_monitor",
            config=config,
            deps=deps,
        )
        self._prs = pr_manager
        self._open_issue: int | None = None  # Track open CI-failure issue

    def _get_default_interval(self) -> int:
        return self._config.ci_monitor_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Check CI status and create/close issues as needed."""
        if self._config.dry_run:
            return None

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
            issue_number = await self._prs.create_issue(title, body)
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
