"""Epic auto-close: detect when all sub-issues are completed and close the epic."""

from __future__ import annotations

import logging
import re

from config import HydraFlowConfig
from issue_fetcher import IssueFetcher
from pr_manager import PRManager

logger = logging.getLogger("hydraflow.epic")

# Matches checkbox lines like "- [ ] #123 — title" or "- [x] #456 — title"
_CHECKBOX_PATTERN = re.compile(r"- \[[ x]\] #(\d+)")


def parse_epic_sub_issues(body: str) -> list[int]:
    """Extract issue numbers from checkbox lines in an epic body."""
    return [int(m) for m in _CHECKBOX_PATTERN.findall(body)]


def check_all_checkboxes(body: str) -> str:
    """Replace all unchecked checkboxes with checked ones for issue references."""
    return re.sub(r"- \[ \] (#\d+)", r"- [x] \1", body)


class EpicCompletionChecker:
    """Checks whether parent epics should be auto-closed after sub-issue completion."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        fetcher: IssueFetcher,
    ) -> None:
        self._config = config
        self._prs = prs
        self._fetcher = fetcher

    async def check_and_close_epics(self, completed_issue_number: int) -> None:
        """Check all open epics and close any whose sub-issues are all completed."""
        if not self._config.epic_label:
            return

        try:
            epics = await self._fetcher.fetch_issues_by_labels(
                self._config.epic_label, limit=50
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to fetch epic issues for completion check",
                exc_info=True,
            )
            return

        for epic in epics:
            sub_issues = parse_epic_sub_issues(epic.body)
            if not sub_issues:
                continue
            if completed_issue_number not in sub_issues:
                continue

            try:
                await self._try_close_epic(epic.number, epic.body, sub_issues)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Epic completion check failed for epic #%d",
                    epic.number,
                    exc_info=True,
                )

    async def _try_close_epic(
        self, epic_number: int, epic_body: str, sub_issues: list[int]
    ) -> None:
        """Close the epic if all sub-issues are completed."""
        fixed_label = self._config.fixed_label[0] if self._config.fixed_label else ""

        for issue_num in sub_issues:
            issue = await self._fetcher.fetch_issue_by_number(issue_num)
            if issue is None:
                # Can't confirm completion — treat as incomplete
                logger.warning(
                    "Sub-issue #%d not found while checking epic #%d — skipping",
                    issue_num,
                    epic_number,
                )
                return
            if fixed_label and fixed_label in issue.labels:
                continue
            # Not completed
            return

        # All sub-issues are completed — close the epic
        logger.info("All sub-issues completed for epic #%d — closing", epic_number)

        updated_body = check_all_checkboxes(epic_body)
        await self._prs.update_issue_body(epic_number, updated_body)
        await self._prs.add_labels(epic_number, [fixed_label])
        await self._prs.post_comment(
            epic_number,
            "All sub-issues completed — closing epic automatically.",
        )
        await self._prs.close_issue(epic_number)
