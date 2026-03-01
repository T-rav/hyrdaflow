"""Epic lifecycle management — tracking, progress, stale detection, and auto-close."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime, timedelta

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from models import (
    EpicChildInfo,
    EpicDetail,
    EpicProgress,
    EpicReadiness,
    EpicState,
    Release,
)
from pr_manager import PRManager
from state import StateTracker

logger = logging.getLogger("hydraflow.epic")


def _stage_from_labels(labels: list[str], config: HydraFlowConfig) -> str:
    """Derive pipeline stage name from issue labels."""
    label_set = set(labels)
    if label_set & set(config.review_label):
        return "review"
    if label_set & set(config.ready_label):
        return "implement"
    if label_set & set(config.planner_label):
        return "plan"
    if label_set & set(config.find_label):
        return "triage"
    if label_set & set(config.fixed_label):
        return "merged"
    return ""


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
        # Background cache: keyed by epic_number → EpicDetail
        self._detail_cache: dict[int, EpicDetail] = {}
        self._cache_timestamps: dict[int, float] = {}  # per-entry TTL
        self._cache_ttl_seconds: float = 60.0
        self._release_jobs: dict[int, str] = {}  # epic_number → job_id
        self._release_locks: dict[int, asyncio.Lock] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

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

    def _invalidate_cache(self, epic_number: int) -> None:
        """Remove cached detail for *epic_number* so the next read fetches fresh data."""
        self._detail_cache.pop(epic_number, None)
        self._cache_timestamps.pop(epic_number, None)

    async def on_child_planned(self, epic_number: int, child_number: int) -> None:
        """Update last_activity when a child issue completes planning."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return
        epic.last_activity = datetime.now(UTC).isoformat()
        self._state.upsert_epic_state(epic)
        self._invalidate_cache(epic_number)
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
        self._invalidate_cache(epic_number)
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
        self._invalidate_cache(epic_number)
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
        self._invalidate_cache(epic_number)
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

    async def get_all_detail(self) -> list[EpicDetail]:
        """Return enriched detail for all tracked epics (for /api/epics)."""
        results: list[EpicDetail] = []
        for epic in self._state.get_all_epic_states().values():
            detail = await self.get_detail(epic.epic_number)
            if detail is not None:
                results.append(detail)
        return results

    def get_cached_detail(self, epic_number: int) -> EpicDetail | None:
        """Return cached detail if still fresh, else None."""
        ts = self._cache_timestamps.get(epic_number, 0.0)
        if time.monotonic() - ts > self._cache_ttl_seconds:
            return None
        return self._detail_cache.get(epic_number)

    async def get_detail(self, epic_number: int) -> EpicDetail | None:
        """Fetch full epic detail including child issue info from GitHub.

        Uses background cache when available to avoid N GitHub API calls.
        """
        cached = self.get_cached_detail(epic_number)
        if cached is not None:
            return cached
        return await self._build_detail(epic_number)

    async def _build_detail(self, epic_number: int) -> EpicDetail | None:
        """Build full epic detail by fetching live data from GitHub."""
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return None

        progress = self.get_progress(epic_number)
        if progress is None:
            return None

        repo = self._config.repo
        fixed_label = self._config.fixed_label[0] if self._config.fixed_label else ""
        children: list[EpicChildInfo] = []
        merged_count = 0
        active_count = 0
        queued_count = 0

        for child_num in epic.child_issues:
            child_info = await self._build_child_info(
                child_num, epic, repo, fixed_label
            )
            # Count by status (failed is tracked via progress.failed; exclude here)
            if child_info.status == "done":
                merged_count += 1
            elif child_info.status == "running":
                active_count += 1
            elif child_info.status != "failed":
                queued_count += 1
            children.append(child_info)

        readiness = self._compute_readiness(children, epic)
        release_data = self._get_release_data(epic_number)

        detail = EpicDetail(
            epic_number=epic.epic_number,
            title=epic.title,
            url=f"https://github.com/{repo}/issues/{epic_number}",
            total_children=progress.total_children,
            completed=progress.completed,
            failed=progress.failed,
            in_progress=progress.in_progress,
            merged_children=merged_count,
            active_children=active_count,
            queued_children=queued_count,
            approved=progress.approved,
            ready_to_merge=progress.ready_to_merge,
            status=progress.status,
            percent_complete=progress.percent_complete,
            last_activity=epic.last_activity,
            created_at=epic.created_at,
            auto_decomposed=epic.auto_decomposed,
            merge_strategy=progress.merge_strategy,
            children=children,
            readiness=readiness,
            release=release_data,
        )
        self._detail_cache[epic_number] = detail
        self._cache_timestamps[epic_number] = time.monotonic()
        return detail

    async def _build_child_info(
        self,
        child_num: int,
        epic: EpicState,
        repo: str,
        fixed_label: str,
    ) -> EpicChildInfo:
        """Build enriched child info for a single sub-issue."""
        is_completed = child_num in epic.completed_children
        is_failed = child_num in epic.failed_children
        is_approved = child_num in epic.approved_children
        child_info = EpicChildInfo(
            issue_number=child_num,
            url=f"https://github.com/{repo}/issues/{child_num}",
            is_completed=is_completed,
            is_failed=is_failed,
            is_approved=is_approved,
        )

        # Determine stage/status from completion state
        if is_completed:
            child_info.current_stage = "merged"
            child_info.stage = "merged"
            child_info.status = "done"
            child_info.state = "closed"
        elif is_failed:
            child_info.status = "failed"

        # Fetch live data from GitHub
        try:
            gh_issue = await self._fetcher.fetch_issue_by_number(child_num)
            if gh_issue is not None:
                child_info.title = gh_issue.title
                if fixed_label and fixed_label in gh_issue.labels:
                    child_info.state = "closed"
                # Derive stage from labels if not already set
                if not child_info.current_stage:
                    stage = _stage_from_labels(gh_issue.labels, self._config)
                    child_info.stage = stage
                    child_info.current_stage = stage
                    if stage in ("implement", "review"):
                        child_info.status = "running"
                    elif stage == "merged":
                        child_info.status = "done"
                    elif stage:
                        child_info.status = "queued"
        except Exception:  # noqa: BLE001
            logger.debug("Could not fetch child #%d for epic detail", child_num)

        # Enrich with branch/PR data from state
        branch = self._state.get_branch(child_num)
        if branch:
            child_info.branch = branch
            try:
                pr_info = await self._prs.find_open_pr_for_branch(
                    branch, issue_number=child_num
                )
                if pr_info is not None:
                    child_info.pr_number = pr_info.number
                    child_info.pr_url = pr_info.url
                    child_info.pr_state = "draft" if pr_info.draft else "open"
                    # Fetch CI and review status
                    await self._enrich_pr_status(child_info, pr_info.number)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Could not fetch PR info for child #%d branch %s",
                    child_num,
                    branch,
                )

        return child_info

    async def _enrich_pr_status(
        self, child_info: EpicChildInfo, pr_number: int
    ) -> None:
        """Fetch CI checks and review status for a PR."""
        try:
            checks = await self._prs.get_pr_checks(pr_number)
            if checks:
                states = {c.get("state", "") for c in checks}
                if all(s == "success" for s in states):
                    child_info.ci_status = "passing"
                elif "failure" in states or "error" in states:
                    child_info.ci_status = "failing"
                else:
                    child_info.ci_status = "pending"
        except Exception:  # noqa: BLE001
            logger.debug("Could not fetch CI checks for PR #%d", pr_number)

        try:
            reviews = await self._prs.get_pr_reviews(pr_number)
            if reviews:
                review_states = [r.get("state", "") for r in reviews]
                if "APPROVED" in review_states:
                    child_info.review_status = "approved"
                elif "CHANGES_REQUESTED" in review_states:
                    child_info.review_status = "changes_requested"
                else:
                    child_info.review_status = "pending"
        except Exception:  # noqa: BLE001
            logger.debug("Could not fetch reviews for PR #%d", pr_number)

        try:
            child_info.mergeable = await self._prs.get_pr_mergeable(pr_number)
        except Exception:  # noqa: BLE001
            logger.debug("Could not fetch mergeable status for PR #%d", pr_number)

    def _compute_readiness(
        self, children: list[EpicChildInfo], epic: EpicState
    ) -> EpicReadiness:
        """Compute epic readiness from child status data."""
        if not children:
            return EpicReadiness()

        all_implemented = all(
            c.status == "done" or c.pr_number is not None for c in children
        )
        all_approved = all(
            c.review_status == "approved" for c in children if c.pr_number
        )
        all_ci_passing = all(c.ci_status == "passing" for c in children if c.pr_number)
        no_conflicts = all(c.mergeable is not False for c in children if c.pr_number)

        version = extract_version_from_title(epic.title)
        changelog_ready = bool(version)

        return EpicReadiness(
            all_implemented=all_implemented,
            all_approved=all_approved,
            all_ci_passing=all_ci_passing,
            no_conflicts=no_conflicts,
            changelog_ready=changelog_ready,
            version=version or None,
        )

    def _get_release_data(self, epic_number: int) -> dict | None:
        """Return release info dict if a release exists for this epic."""
        release = self._state.get_release(epic_number)
        if release is None:
            return None
        return {
            "version": release.version,
            "tag": release.tag,
            "released_at": release.released_at,
            "status": release.status,
        }

    async def refresh_cache(self) -> None:
        """Refresh the background cache for all tracked epics.

        Called periodically to avoid N GitHub API calls per dashboard request.
        """
        for epic in self._state.get_all_epic_states().values():
            if epic.closed:
                continue
            try:
                detail = await self._build_detail(epic.epic_number)
                if detail is not None:
                    # Publish progress event
                    await self._bus.publish(
                        HydraFlowEvent(
                            type=EventType.EPIC_PROGRESS,
                            data={
                                "epic_number": epic.epic_number,
                                "progress": detail.model_dump(),
                            },
                        )
                    )
                    # Check and publish readiness (skip already-released epics).
                    # Re-fetch live state to avoid stale snapshot from get_all_epic_states.
                    live_epic = self._state.get_epic_state(epic.epic_number)
                    if (
                        live_epic is not None
                        and not live_epic.released
                        and detail.readiness.all_implemented
                        and detail.readiness.all_approved
                        and detail.readiness.all_ci_passing
                        and detail.readiness.no_conflicts
                    ):
                        await self._bus.publish(
                            HydraFlowEvent(
                                type=EventType.EPIC_READY,
                                data={
                                    "epic_number": epic.epic_number,
                                    "readiness": detail.readiness.model_dump(),
                                },
                            )
                        )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to refresh cache for epic #%d",
                    epic.epic_number,
                    exc_info=True,
                )

    async def trigger_release(self, epic_number: int) -> dict[str, object]:
        """Trigger async merge sequence and release creation for a bundled epic.

        Returns a dict with job_id and status. Completion is signalled via the
        EPIC_RELEASED WebSocket event (not a polling endpoint).
        """
        epic = self._state.get_epic_state(epic_number)
        if epic is None:
            return {"error": "epic not found", "status": "failed"}

        if epic.closed:
            return {"error": "epic already closed", "status": "failed"}

        if epic.released:
            return {"error": "epic already released", "status": "failed"}

        # Check if a release job is already running
        if epic_number in self._release_jobs:
            return {
                "job_id": self._release_jobs[epic_number],
                "status": "in_progress",
            }

        job_id = f"release-{epic_number}-{int(time.time())}"
        self._release_jobs[epic_number] = job_id

        # Launch background task — store reference to prevent premature GC
        task: asyncio.Task[None] = asyncio.create_task(
            self._execute_release(epic_number, job_id)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return {"job_id": job_id, "status": "started"}

    async def _execute_release(self, epic_number: int, job_id: str) -> None:
        """Background task to merge all child PRs and create a release."""
        try:
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.EPIC_RELEASING,
                    data={"epic_number": epic_number, "job_id": job_id},
                )
            )

            result = await self.release_epic(epic_number)
            if "error" in result:
                raise RuntimeError(result["error"])

            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.EPIC_RELEASED,
                    data={
                        "epic_number": epic_number,
                        "job_id": job_id,
                        "status": "completed",
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Release execution failed for epic #%d",
                epic_number,
                exc_info=True,
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.EPIC_RELEASED,
                    data={
                        "epic_number": epic_number,
                        "job_id": job_id,
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            )
        finally:
            self._release_jobs.pop(epic_number, None)

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
        self._invalidate_cache(epic_number)

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
