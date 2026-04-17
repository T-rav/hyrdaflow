"""Background worker loop — auto-close stale issues with no recent activity."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.stale_issue_loop")


class StaleIssueLoop(BaseBackgroundLoop):
    """Polls for stale issues and auto-closes them after configurable inactivity period."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="stale_issue", config=config, deps=deps)
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.stale_issue_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Scan for stale issues and close them."""
        settings = self._state.get_stale_issue_settings()
        already_closed = self._state.get_stale_issue_closed()

        stats: dict[str, int] = {"scanned": 0, "closed": 0, "skipped": 0}

        # Fetch open issues that don't have HydraFlow lifecycle labels
        exclude_labels = [
            *self._config.planner_label,
            *self._config.ready_label,
            *self._config.review_label,
            *self._config.hitl_label,
            *settings.excluded_labels,
        ]

        try:
            raw = await self._prs._run_gh(
                "gh",
                "issue",
                "list",
                "--repo",
                self._prs._repo,
                "--state",
                "open",
                "--limit",
                "100",
                "--json",
                "number,title,updatedAt,labels",
            )
            issues = json.loads(raw) if raw else []
        except Exception:
            logger.warning("Failed to fetch issues for stale check", exc_info=True)
            return stats

        cutoff = datetime.now(UTC) - timedelta(days=settings.staleness_days)

        for issue in issues:
            number = issue.get("number", 0)
            if number in already_closed:
                stats["skipped"] += 1
                continue

            # Skip issues with excluded labels
            issue_labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
            if any(el in issue_labels for el in exclude_labels):
                stats["skipped"] += 1
                continue

            stats["scanned"] += 1

            # Check last activity
            updated = issue.get("updatedAt", "")
            try:
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if updated_dt.tzinfo is None:
                    updated_dt = updated_dt.replace(tzinfo=UTC)
            except (ValueError, AttributeError):
                continue

            if updated_dt > cutoff:
                continue  # Not stale yet

            # Stale — close it
            if settings.dry_run:
                logger.info(
                    "[dry-run] Would close stale issue #%d: %s",
                    number,
                    issue.get("title", ""),
                )
                stats["closed"] += 1
                continue

            try:
                await self._prs.post_comment(
                    number,
                    "## Auto-closed: Stale Issue\n\n"
                    "This issue has been automatically closed due to inactivity "
                    f"(no updates for {settings.staleness_days} days). "
                    "If this is still relevant, please reopen it.\n\n"
                    "*Closed by HydraFlow Stale Issue Cleanup.*",
                )
                await self._prs._run_gh(
                    "gh",
                    "issue",
                    "close",
                    "--repo",
                    self._prs._repo,
                    str(number),
                )
                self._state.add_stale_issue_closed(number)
                stats["closed"] += 1
                logger.info(
                    "Closed stale issue #%d: %s", number, issue.get("title", "")
                )
            except Exception:
                logger.warning("Failed to close stale issue #%d", number, exc_info=True)

        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="stale_issue.cycle",
                message=f"Scanned {stats['scanned']} issues, closed {stats['closed']}",
                level="info",
                data=stats,
            )
        except ImportError:
            pass

        return stats
