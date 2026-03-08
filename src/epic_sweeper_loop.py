"""Background worker loop — periodic sweep to auto-close completed epics.

Complements the EpicMonitorLoop (stale detection) by checking whether all
sub-issues of each open epic are resolved, regardless of how the sub-issues
were registered (formal EpicState children or checkbox-style body refs).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from epic import check_all_checkboxes, parse_epic_sub_issues
from events import EventBus
from models import StatusCallback

if TYPE_CHECKING:
    from issue_fetcher import IssueFetcher
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.epic_sweeper_loop")


class EpicSweeperLoop(BaseBackgroundLoop):
    """Periodically sweep open epics and auto-close those with all sub-issues resolved."""

    def __init__(
        self,
        config: HydraFlowConfig,
        fetcher: IssueFetcher,
        prs: PRManager,
        state: StateTracker,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(
            worker_name="epic_sweeper",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._fetcher = fetcher
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.epic_sweep_interval

    async def _do_work(self) -> dict[str, Any] | None:
        epics = await self._fetcher.fetch_issues_by_labels(
            self._config.epic_label, limit=50
        )
        if len(epics) == 50:
            logger.warning(
                "Epic sweeper fetched exactly 50 epics — result may be truncated;"
                " some epics may not be swept this cycle"
            )
        swept = 0
        checked = 0
        for epic in epics:
            try:
                sub_issues = self._collect_sub_issues(epic.number, epic.body)
                if not sub_issues:
                    continue
                checked += 1
                closed = await self._try_sweep_epic(epic.number, epic.body, sub_issues)
                if closed:
                    swept += 1
            except Exception:
                logger.exception("Error sweeping epic #%d — skipping", epic.number)
        return {"checked": checked, "swept": swept, "total_open_epics": len(epics)}

    def _collect_sub_issues(self, epic_number: int, body: str) -> list[int]:
        """Merge sub-issue refs from EpicState children and body checkboxes."""
        refs: set[int] = set()

        # Formal EpicState children
        epic_state = self._state.get_epic_state(epic_number)
        if epic_state is not None:
            refs.update(epic_state.child_issues)

        # Checkbox-style refs from body
        refs.update(parse_epic_sub_issues(body))

        return sorted(refs)

    async def _try_sweep_epic(
        self, epic_number: int, epic_body: str, sub_issues: list[int]
    ) -> bool:
        """Close the epic if every sub-issue is closed/merged.

        Returns True if the epic was closed.
        """
        fixed_label = self._config.fixed_label[0] if self._config.fixed_label else ""

        for issue_num in sub_issues:
            issue = await self._fetcher.fetch_issue_by_number(issue_num)
            if issue is None:
                logger.warning(
                    "Sub-issue #%d not found for epic #%d — skipping epic"
                    " (remove stale ref from body to allow auto-close)",
                    issue_num,
                    epic_number,
                )
                return False
            if issue.state != "closed":
                return False

        # All sub-issues are closed — update checkboxes, post comment, close
        logger.info(
            "All %d sub-issues closed for epic #%d — auto-closing",
            len(sub_issues),
            epic_number,
        )

        updated_body = check_all_checkboxes(epic_body)
        if updated_body != epic_body:
            await self._prs.update_issue_body(epic_number, updated_body)

        if fixed_label:
            await self._prs.add_labels(epic_number, [fixed_label])

        comment = f"All {len(sub_issues)} sub-issues completed. Auto-closing epic."
        await self._prs.post_comment(epic_number, comment)
        await self._prs.close_issue(epic_number)
        return True
