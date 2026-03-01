"""Epic lifecycle management — tracking, progress, stale detection, and auto-close."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from models import EpicChildInfo, EpicDetail, EpicProgress, EpicState
from pr_manager import PRManager
from state import StateTracker

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


class EpicManager:
    """Centralized epic lifecycle management.

    Handles registration, progress tracking, stale detection, and
    auto-close of epics. Wraps ``EpicCompletionChecker`` for the
    actual close logic and adds state persistence + event publishing.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        prs: PRManager,
        fetcher: IssueFetcher,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._state = state
        self._prs = prs
        self._fetcher = fetcher
        self._bus = event_bus
        self._checker = EpicCompletionChecker(config, prs, fetcher)

    async def register_epic(
        self,
        epic_number: int,
        title: str,
        children: list[int],
        *,
        auto_decomposed: bool = False,
    ) -> None:
        """Register a new epic for lifecycle tracking."""
        now = datetime.now(UTC).isoformat()
        epic_state = EpicState(
            epic_number=epic_number,
            title=title,
            child_issues=list(children),
            created_at=now,
            last_activity=now,
            auto_decomposed=auto_decomposed,
        )
        self._state.upsert_epic_state(epic_state)
        await self._publish_update(epic_number, "registered")
        logger.info(
            "Registered epic #%d with %d children (auto_decomposed=%s)",
            epic_number,
            len(children),
            auto_decomposed,
        )

    async def on_child_planned(self, epic_number: int, child_number: int) -> None:
        """Update last_activity when a child issue completes planning."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        epic.last_activity = datetime.now(UTC).isoformat()
        self._state.upsert_epic_state(epic)
        logger.debug(
            "Epic #%d child #%d planned — updated last_activity",
            epic_number,
            child_number,
        )

    async def on_child_completed(self, epic_number: int, child_number: int) -> None:
        """Record child completion and attempt auto-close."""
        self._state.mark_epic_child_complete(epic_number, child_number)
        await self._publish_update(epic_number, "child_completed")
        logger.info(
            "Epic #%d child #%d completed",
            epic_number,
            child_number,
        )
        await self._try_auto_close(epic_number)

    async def on_child_failed(self, epic_number: int, child_number: int) -> None:
        """Record a child failure."""
        self._state.mark_epic_child_failed(epic_number, child_number)
        await self._publish_update(epic_number, "child_failed")
        logger.info(
            "Epic #%d child #%d failed",
            epic_number,
            child_number,
        )

    def get_progress(self, epic_number: int) -> EpicProgress | None:
        """Compute progress from persisted state."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return None

        total = len(epic.child_issues)
        completed = len(epic.completed_children)
        failed = len(epic.failed_children)
        in_progress = total - completed - failed

        if epic.closed:
            status = "completed"
        elif failed > 0 and in_progress == 0:
            status = "blocked"
        elif self._is_stale(epic):
            status = "stale"
        else:
            status = "active"

        pct = (completed / total * 100) if total > 0 else 0.0

        return EpicProgress(
            epic_number=epic.epic_number,
            title=epic.title,
            total_children=total,
            completed=completed,
            failed=failed,
            in_progress=max(in_progress, 0),
            status=status,
            percent_complete=round(pct, 1),
            last_activity=epic.last_activity,
            auto_decomposed=epic.auto_decomposed,
            child_issues=list(epic.child_issues),
        )

    def get_all_progress(self) -> list[EpicProgress]:
        """Return progress for all tracked epics (for dashboard API)."""
        results: list[EpicProgress] = []
        for epic in self._state.get_all_epic_states().values():
            progress = self.get_progress(epic.epic_number)
            if progress is not None:
                results.append(progress)
        return results

    async def get_detail(self, epic_number: int) -> EpicDetail | None:
        """Fetch full epic detail including child issue info from GitHub."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return None

        progress = self.get_progress(epic_number)
        if progress is None:
            return None

        repo = self._config.repo
        children: list[EpicChildInfo] = []
        for child_num in epic.child_issues:
            child_info = EpicChildInfo(
                issue_number=child_num,
                url=f"https://github.com/{repo}/issues/{child_num}",
                is_completed=child_num in epic.completed_children,
                is_failed=child_num in epic.failed_children,
            )
            # Try to fetch live title from GitHub
            try:
                gh_issue = await self._fetcher.fetch_issue_by_number(child_num)
                if gh_issue is not None:
                    child_info.title = gh_issue.title
                    fixed = (
                        self._config.fixed_label[0] if self._config.fixed_label else ""
                    )
                    if fixed and fixed in gh_issue.labels:
                        child_info.state = "closed"
            except Exception:  # noqa: BLE001
                logger.debug("Could not fetch child #%d for epic detail", child_num)
            children.append(child_info)

        return EpicDetail(
            epic_number=epic.epic_number,
            title=epic.title,
            url=f"https://github.com/{repo}/issues/{epic_number}",
            total_children=progress.total_children,
            completed=progress.completed,
            failed=progress.failed,
            in_progress=progress.in_progress,
            status=progress.status,
            percent_complete=progress.percent_complete,
            last_activity=epic.last_activity,
            created_at=epic.created_at,
            auto_decomposed=epic.auto_decomposed,
            children=children,
        )

    async def check_stale_epics(self) -> list[int]:
        """Find epics with no recent activity and post a warning comment."""
        stale: list[int] = []
        for epic in self._state.get_all_epic_states().values():
            if epic.closed:
                continue
            if not self._is_stale(epic):
                continue
            stale.append(epic.epic_number)
            try:
                await self._prs.post_comment(
                    epic.epic_number,
                    f"**Stale epic warning:** No activity on this epic for "
                    f"{self._config.epic_stale_days} days. "
                    f"Consider reviewing the status of child issues.\n\n"
                    f"---\n*HydraFlow Epic Monitor*",
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to post stale warning for epic #%d",
                    epic.epic_number,
                    exc_info=True,
                )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "message": f"Epic #{epic.epic_number} is stale "
                        f"(no activity for {self._config.epic_stale_days} days)",
                        "source": "epic_monitor",
                        "epic_number": epic.epic_number,
                    },
                )
            )
        return stale

    async def _try_auto_close(self, epic_number: int) -> None:
        """Attempt to auto-close an epic if all children are completed."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None or epic.closed:
            return

        completed = set(epic.completed_children)
        all_children = set(epic.child_issues)
        if not all_children or not all_children.issubset(completed):
            return

        # Delegate to the existing EpicCompletionChecker for GitHub operations
        # (checkbox update, label add, close). If that fails, try a direct close.
        try:
            await self._checker.check_and_close_epics(epic.completed_children[-1])
        except Exception:  # noqa: BLE001
            logger.warning(
                "EpicCompletionChecker failed for #%d — attempting direct close",
                epic_number,
                exc_info=True,
            )
            try:
                await self._prs.post_comment(
                    epic_number,
                    "All child issues completed — closing epic automatically.",
                )
                await self._prs.close_issue(epic_number)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Direct close also failed for epic #%d",
                    epic_number,
                    exc_info=True,
                )
                return

        self._state.close_epic(epic_number)
        await self._publish_update(epic_number, "closed")
        logger.info("Epic #%d auto-closed — all children completed", epic_number)

    def _is_stale(self, epic: EpicState) -> bool:
        """Return True if the epic has had no activity within the stale threshold."""
        try:
            last = datetime.fromisoformat(epic.last_activity)
            cutoff = datetime.now(UTC) - timedelta(days=self._config.epic_stale_days)
            return last < cutoff
        except (ValueError, TypeError):
            return False

    async def _publish_update(self, epic_number: int, action: str) -> None:
        """Publish an EPIC_UPDATE event with current progress."""
        progress = self.get_progress(epic_number)
        data: dict[str, object] = {
            "epic_number": epic_number,
            "action": action,
        }
        if progress is not None:
            data["progress"] = progress.model_dump()
        await self._bus.publish(HydraFlowEvent(type=EventType.EPIC_UPDATE, data=data))
