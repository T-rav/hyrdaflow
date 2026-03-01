"""Epic lifecycle management — tracking, progress, stale detection, and auto-close."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from models import EpicChildInfo, EpicDetail, EpicProgress, EpicState, Release
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


# Matches version strings requiring either a "v" prefix (v1, v1.2, v1.2.3)
# or multi-part notation (1.2, 1.2.3) to avoid matching bare integers like
# "Phase 3" or "Sprint 5".
_VERSION_PATTERN = re.compile(r"v(\d+(?:\.\d+)*)|\b(\d+\.\d+(?:\.\d+)*)\b")


def extract_version_from_title(title: str) -> str:
    """Extract a semantic version string from an epic title.

    Looks for patterns like "v1.2.0", "1.0", "v2" in the title.
    Requires either a 'v' prefix or multi-part notation to avoid matching
    bare integers (e.g. "Phase 3" would not extract "3").
    Returns the matched version (without 'v' prefix) or empty string.
    """
    match = _VERSION_PATTERN.search(title)
    return (match.group(1) or match.group(2)) if match else ""


def generate_changelog(sub_issue_titles: list[str]) -> str:
    """Generate a changelog body from sub-issue titles.

    Returns a markdown-formatted list of changes.
    """
    if not sub_issue_titles:
        return ""
    lines = [f"- {title}" for title in sub_issue_titles]
    return "## What's Changed\n\n" + "\n".join(lines) + "\n"


class EpicCompletionChecker:
    """Checks whether parent epics should be auto-closed after sub-issue completion."""

    def __init__(
        self,
        config: HydraFlowConfig,
        prs: PRManager,
        fetcher: IssueFetcher,
        state: StateTracker | None = None,
    ) -> None:
        self._config = config
        self._prs = prs
        self._fetcher = fetcher
        self._state = state

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
                await self._try_close_epic(
                    epic.number, epic.title, epic.body, sub_issues
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Epic completion check failed for epic #%d",
                    epic.number,
                    exc_info=True,
                )

    async def _try_close_epic(
        self, epic_number: int, epic_title: str, epic_body: str, sub_issues: list[int]
    ) -> None:
        """Close the epic if all sub-issues are completed."""
        fixed_label = self._config.fixed_label[0] if self._config.fixed_label else ""

        sub_issue_titles: list[str] = []
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
                sub_issue_titles.append(issue.title)
                continue
            # Not completed
            return

        # All sub-issues are completed — close the epic
        logger.info("All sub-issues completed for epic #%d — closing", epic_number)

        updated_body = check_all_checkboxes(epic_body)
        await self._prs.update_issue_body(epic_number, updated_body)
        await self._prs.add_labels(epic_number, [fixed_label])

        # Create release if feature is enabled
        release_url = ""
        if self._config.release_on_epic_close:
            release_url = await self._create_release_for_epic(
                epic_number, epic_title, sub_issues, sub_issue_titles
            )

        close_comment = "All sub-issues completed — closing epic automatically."
        if release_url:
            close_comment += f"\n\n**Release:** {release_url}"
        await self._prs.post_comment(epic_number, close_comment)
        await self._prs.close_issue(epic_number)

    async def _create_release_for_epic(
        self,
        epic_number: int,
        epic_title: str,
        sub_issues: list[int],
        sub_issue_titles: list[str],
    ) -> str:
        """Create a git tag and GitHub Release for a completed epic.

        Returns the release URL on success, empty string on failure.
        """
        if self._config.release_version_source != "epic_title":
            logger.warning(
                "release_version_source=%r is not yet implemented — falling back to 'epic_title'",
                self._config.release_version_source,
            )

        version = extract_version_from_title(epic_title)
        if not version:
            logger.info(
                "No version found in epic #%d title %r — skipping release",
                epic_number,
                epic_title,
            )
            return ""

        tag = f"{self._config.release_tag_prefix}{version}"
        changelog = generate_changelog(sub_issue_titles)
        release_title = f"Release {tag}"

        # Create the git tag
        tag_ok = await self._prs.create_tag(tag)
        if not tag_ok:
            logger.warning("Tag creation failed for %s — skipping release", tag)
            return ""

        # Create the GitHub Release
        release_ok = await self._prs.create_release(tag, release_title, changelog)
        if not release_ok:
            logger.warning("GitHub Release creation failed for %s", tag)
            return ""

        release_url = f"https://github.com/{self._config.repo}/releases/tag/{tag}"

        # Persist release state if a state tracker is available
        release = Release(
            version=version,
            epic_number=epic_number,
            sub_issues=list(sub_issues),
            status="released",
            released_at=datetime.now(UTC).isoformat(),
            changelog=changelog,
            tag=tag,
        )
        if self._state is not None:
            self._state.upsert_release(release)

        logger.info(
            "Created release %s for epic #%d with %d sub-issues",
            tag,
            epic_number,
            len(sub_issues),
        )
        return release_url


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
        self._checker = EpicCompletionChecker(config, prs, fetcher, state=state)
        self._release_locks: dict[int, asyncio.Lock] = {}

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
            merge_strategy=self._config.epic_merge_strategy,
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

    async def on_child_approved(self, epic_number: int, child_number: int) -> None:
        """Record that a child's PR was approved (not yet merged).

        For bundled strategies, this is the trigger to check if all siblings
        are approved and optionally auto-merge or escalate for human review.
        """
        self._state.mark_epic_child_approved(epic_number, child_number)
        await self._publish_update(epic_number, "child_approved")
        logger.info("Epic #%d child #%d approved", epic_number, child_number)

        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return

        if epic.released:
            return

        strategy = epic.merge_strategy
        if strategy == "independent":
            return

        # Check if all siblings are approved or already merged
        progress = self.get_progress(epic_number)
        if progress is None or not progress.ready_to_merge:
            return

        if strategy == "bundled":
            await self._handle_bundled_ready(epic_number)
        elif strategy == "bundled_hitl":
            await self._handle_bundled_hitl_ready(epic_number)
        elif strategy == "ordered":
            await self._handle_ordered_ready(epic_number)

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
        approved = len(epic.approved_children)
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

        # Ready to merge when all children are approved or already merged,
        # the strategy is not independent, and the epic has not yet been released.
        ready_to_merge = (
            total > 0
            and failed == 0
            and not epic.released
            and epic.merge_strategy != "independent"
            and all(
                c in epic.approved_children or c in epic.completed_children
                for c in epic.child_issues
            )
        )

        return EpicProgress(
            epic_number=epic.epic_number,
            title=epic.title,
            total_children=total,
            completed=completed,
            failed=failed,
            in_progress=max(in_progress, 0),
            approved=approved,
            ready_to_merge=ready_to_merge,
            merge_strategy=epic.merge_strategy,
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
                is_approved=child_num in epic.approved_children,
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
            approved=progress.approved,
            ready_to_merge=progress.ready_to_merge,
            merge_strategy=progress.merge_strategy,
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

    def _get_merge_order(self, epic: EpicState) -> list[int]:
        """Return child issues that still need merging, in their registered order.

        Returns children that are not yet completed, preserving the order they
        were registered in ``child_issues``.

        Note: BLOCKS/BLOCKED_BY dependency ordering is not yet implemented.
        For the "ordered" strategy, ensure children are registered in the
        correct dependency order at registration time.
        """
        return [c for c in epic.child_issues if c not in epic.completed_children]

    async def _handle_bundled_ready(self, epic_number: int) -> None:
        """All siblings approved — merge all in sequence automatically."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        merge_order = self._get_merge_order(epic)
        logger.info(
            "Epic #%d: all children approved — auto-merging %d PRs (bundled)",
            epic_number,
            len(merge_order),
        )
        await self._publish_ready_event(epic_number, "bundled")
        await self._prs.post_comment(
            epic_number,
            "## Epic Bundle Ready\n\n"
            "All sub-issues are approved and CI is passing. "
            "Merging all PRs automatically (bundled strategy).\n\n"
            "---\n*HydraFlow Epic Coordinator*",
        )
        result = await self.release_epic(epic_number)
        if "error" in result:
            logger.warning(
                "Epic #%d bundled release failed: %s", epic_number, result["error"]
            )
            await self._prs.post_comment(
                epic_number,
                f"## Epic Bundle Release Failed\n\n"
                f"Auto-merge encountered an error: {result['error']}\n\n"
                f"Please resolve any merge conflicts and retry via the dashboard "
                f"or `POST /api/epics/{epic_number}/release`.\n\n"
                "---\n*HydraFlow Epic Coordinator*",
            )

    async def _handle_bundled_hitl_ready(self, epic_number: int) -> None:
        """All siblings approved — pause and notify for human review."""
        logger.info(
            "Epic #%d: all children approved — awaiting human release (bundled_hitl)",
            epic_number,
        )
        await self._publish_ready_event(epic_number, "bundled_hitl")
        await self._prs.post_comment(
            epic_number,
            "## Epic Bundle Ready for Release\n\n"
            "All sub-issues are approved and CI is passing. "
            "Awaiting human confirmation to merge.\n\n"
            "Use the dashboard **Merge & Release** button or "
            f"`POST /api/epics/{epic_number}/release` to trigger the merge.\n\n"
            "---\n*HydraFlow Epic Coordinator*",
        )

    async def _handle_ordered_ready(self, epic_number: int) -> None:
        """All siblings approved — merge in dependency order."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        merge_order = self._get_merge_order(epic)
        logger.info(
            "Epic #%d: all children approved — merging in dependency order (%d PRs)",
            epic_number,
            len(merge_order),
        )
        await self._publish_ready_event(epic_number, "ordered")
        await self._prs.post_comment(
            epic_number,
            "## Epic Bundle Ready (Ordered)\n\n"
            "All sub-issues are approved and CI is passing. "
            "Merging PRs in dependency order.\n\n"
            "---\n*HydraFlow Epic Coordinator*",
        )
        result = await self.release_epic(epic_number)
        if "error" in result:
            logger.warning(
                "Epic #%d ordered release failed: %s", epic_number, result["error"]
            )
            await self._prs.post_comment(
                epic_number,
                f"## Epic Bundle Release Failed (Ordered)\n\n"
                f"Auto-merge encountered an error: {result['error']}\n\n"
                f"Please resolve any merge conflicts and retry via the dashboard "
                f"or `POST /api/epics/{epic_number}/release`.\n\n"
                "---\n*HydraFlow Epic Coordinator*",
            )

    async def release_epic(self, epic_number: int) -> dict[str, object]:
        """Trigger sequential merge for a bundled epic (called from API).

        Returns a summary dict with merge results.  Idempotent: a second
        call after a successful release returns an error instead of
        attempting duplicate merges.  A per-epic asyncio.Lock prevents
        concurrent invocations from both passing the ``released`` guard.
        """
        if epic_number not in self._release_locks:
            self._release_locks[epic_number] = asyncio.Lock()
        async with self._release_locks[epic_number]:
            return await self._do_release_epic(epic_number)

    async def _do_release_epic(self, epic_number: int) -> dict[str, object]:
        """Inner (lock-protected) implementation of release_epic."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return {"error": "epic not found"}

        if epic.released:
            return {"error": "epic has already been released"}

        progress = self.get_progress(epic_number)
        if progress is None or not progress.ready_to_merge:
            return {"error": "epic is not ready to merge"}

        merge_order = self._get_merge_order(epic)
        results: list[dict[str, object]] = []
        for child_num in merge_order:
            halt_msg: str | None = None
            try:
                pr_number = await self._prs.find_pr_for_issue(child_num)
                if not pr_number:
                    # Halt on missing PR — bundle guarantee requires all PRs to merge
                    results.append({"issue": child_num, "status": "no_pr"})
                    halt_msg = f"no PR found for child #{child_num}; bundle halted"
                else:
                    merged = await self._prs.merge_pr(pr_number)
                    if merged:
                        self._state.mark_epic_child_complete(epic_number, child_num)
                        results.append(
                            {"issue": child_num, "pr": pr_number, "status": "merged"}
                        )
                    else:
                        results.append(
                            {"issue": child_num, "pr": pr_number, "status": "failed"}
                        )
                        halt_msg = f"merge failed for child #{child_num} (PR #{pr_number}); bundle halted"
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to merge child #%d of epic #%d",
                    child_num,
                    epic_number,
                    exc_info=True,
                )
                results.append({"issue": child_num, "status": "error"})
                halt_msg = f"exception merging child #{child_num}; bundle halted"
            if halt_msg:
                await self._publish_update(epic_number, "release_failed")
                return {
                    "epic_number": epic_number,
                    "merges": results,
                    "error": halt_msg,
                }

        # Mark epic as released to prevent duplicate release attempts
        epic = self._state.get_epic_state(epic_number)
        if epic is not None:
            epic.released = True
            self._state.upsert_epic_state(epic)

        await self._publish_update(epic_number, "released")
        return {"epic_number": epic_number, "merges": results}

    async def _publish_ready_event(self, epic_number: int, strategy: str) -> None:
        """Publish an EPIC_READY event when all children are approved."""
        progress = self.get_progress(epic_number)
        data: dict[str, object] = {
            "epic_number": epic_number,
            "strategy": strategy,
        }
        if progress is not None:
            data["progress"] = progress.model_dump()
        await self._bus.publish(HydraFlowEvent(type=EventType.EPIC_READY, data=data))

    def find_parent_epics(self, child_number: int) -> list[int]:
        """Return epic numbers that include *child_number* as a child."""
        parents: list[int] = []
        for epic in self._state.get_all_epic_states().values():
            if child_number in epic.child_issues:
                parents.append(epic.epic_number)
        return parents

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
