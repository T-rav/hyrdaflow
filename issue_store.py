"""Centralized GitHub issue store with in-memory work queues."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from models import GitHubIssue, QueueStats
from subprocess_util import AuthenticationError

logger = logging.getLogger("hydraflow.issue_store")

# Pipeline stage names used as queue keys
STAGE_FIND = "find"
STAGE_PLAN = "plan"
STAGE_READY = "ready"
STAGE_REVIEW = "review"
STAGE_HITL = "hitl"

# Priority order — higher index = further along in the pipeline.
# When an issue has multiple HydraFlow labels, it is routed to the
# most advanced stage (highest priority).
_STAGE_PRIORITY = {
    STAGE_FIND: 0,
    STAGE_PLAN: 1,
    STAGE_READY: 2,
    STAGE_REVIEW: 3,
    STAGE_HITL: 4,
}


class IssueStore:
    """Central data layer for GitHub issue fetching and work queue management.

    A single background polling loop fetches all HydraFlow-labeled issues from
    GitHub and routes them into per-stage queues.  Orchestrator loops consume
    issues from these queues instead of independently polling GitHub.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        fetcher: IssueFetcher,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._fetcher = fetcher
        self._bus = event_bus

        # Per-stage queues (FIFO)
        self._queues: dict[str, deque[GitHubIssue]] = {
            STAGE_FIND: deque(),
            STAGE_PLAN: deque(),
            STAGE_READY: deque(),
            STAGE_REVIEW: deque(),
        }
        # Companion sets for O(1) membership checks (issue numbers in each queue)
        self._queue_members: dict[str, set[int]] = {
            STAGE_FIND: set(),
            STAGE_PLAN: set(),
            STAGE_READY: set(),
            STAGE_REVIEW: set(),
        }
        # HITL issues are tracked as a set (display only, not consumed)
        self._hitl_numbers: set[int] = set()

        # Issue cache: retains title/url for issues seen during routing
        self._issue_cache: dict[int, GitHubIssue] = {}

        # Active issue tracking: issue_number → stage
        self._active: dict[int, str] = {}

        # Session throughput counters
        self._processed_count: dict[str, int] = {
            STAGE_FIND: 0,
            STAGE_PLAN: 0,
            STAGE_READY: 0,
            STAGE_REVIEW: 0,
            STAGE_HITL: 0,
        }

        self._last_poll_ts: str | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, stop_event: asyncio.Event) -> None:
        """Run the background polling loop until *stop_event* is set.

        Performs an initial refresh before entering the polling loop so
        queues are populated before the orchestrator loops start consuming.
        """
        await self.refresh()
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._config.data_poll_interval,
                )
                break  # stop_event was set
            except TimeoutError:
                pass
            await self.refresh()

    # ------------------------------------------------------------------
    # Polling / refresh
    # ------------------------------------------------------------------

    async def refresh(self) -> None:
        """Fetch all HydraFlow-labeled issues and re-route into queues."""
        try:
            issues = await self._fetcher.fetch_all_hydraflow_issues()
        except AuthenticationError:
            raise
        except Exception:
            logger.exception("IssueStore refresh failed — will retry next cycle")
            return

        async with self._lock:
            self._route_issues(issues)

        self._last_poll_ts = datetime.now(UTC).isoformat()

        # Publish queue update event
        stats = self.get_queue_stats()
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.QUEUE_UPDATE,
                data=stats.model_dump(),
            )
        )

    def _route_issues(self, issues: list[GitHubIssue]) -> None:
        """Route fetched issues into the correct queues.

        - Each issue goes to the most advanced stage matching its labels.
        - Issues already active are not re-queued.
        - Issues that changed labels are moved between queues.
        - Issues no longer returned by GitHub are removed from queues.
        """
        # Build a mapping of issue_number → (best_stage, issue)
        label_to_stage = self._build_label_map()
        incoming: dict[int, tuple[str, GitHubIssue]] = {}

        for issue in issues:
            # Cache every issue for pipeline snapshot lookups
            self._issue_cache[issue.number] = issue

            best_stage: str | None = None
            best_priority = -1
            for label in issue.labels:
                stage = label_to_stage.get(label)
                if stage is not None:
                    prio = _STAGE_PRIORITY.get(stage, -1)
                    if prio > best_priority:
                        best_priority = prio
                        best_stage = stage
            if best_stage is not None:
                incoming[issue.number] = (best_stage, issue)

        # Determine which issue numbers are still present
        incoming_numbers = set(incoming.keys())

        # Remove stale issues (no longer returned by GitHub)
        for stage, q in self._queues.items():
            members = self._queue_members[stage]
            stale = members - incoming_numbers - set(self._active.keys())
            if stale:
                self._queues[stage] = deque(i for i in q if i.number not in stale)
                members -= stale

        # Remove stale HITL issues
        self._hitl_numbers &= incoming_numbers | set(self._active.keys())

        # Route incoming issues
        for issue_num, (stage, issue) in incoming.items():
            # Skip issues currently being processed
            if issue_num in self._active:
                continue

            if stage == STAGE_HITL:
                self._hitl_numbers.add(issue_num)
                # Remove from any regular queue if it was there before
                self._remove_from_all_queues(issue_num)
                continue

            # Check if issue is already in the correct queue
            current_stage = self._find_queue_stage(issue_num)
            if current_stage == stage:
                continue  # Already in the right queue

            # Remove from old queue if it moved stages
            if current_stage is not None:
                self._remove_from_queue(current_stage, issue_num)

            # Also remove from HITL if it was there
            self._hitl_numbers.discard(issue_num)

            # Add to the target queue
            self._queues[stage].append(issue)
            self._queue_members[stage].add(issue_num)

    def _build_label_map(self) -> dict[str, str]:
        """Build a mapping from label name → pipeline stage."""
        m: dict[str, str] = {}
        for lbl in self._config.find_label:
            m[lbl] = STAGE_FIND
        for lbl in self._config.planner_label:
            m[lbl] = STAGE_PLAN
        for lbl in self._config.ready_label:
            m[lbl] = STAGE_READY
        for lbl in self._config.review_label:
            m[lbl] = STAGE_REVIEW
        for lbl in self._config.hitl_label:
            m[lbl] = STAGE_HITL
        for lbl in self._config.hitl_active_label:
            m[lbl] = STAGE_HITL
        return m

    def _find_queue_stage(self, issue_number: int) -> str | None:
        """Return the stage name if the issue is in any queue, else None."""
        for stage, members in self._queue_members.items():
            if issue_number in members:
                return stage
        return None

    def _remove_from_queue(self, stage: str, issue_number: int) -> None:
        """Remove an issue from a specific queue."""
        if issue_number in self._queue_members[stage]:
            self._queues[stage] = deque(
                i for i in self._queues[stage] if i.number != issue_number
            )
            self._queue_members[stage].discard(issue_number)

    def _remove_from_all_queues(self, issue_number: int) -> None:
        """Remove an issue from all regular queues."""
        for stage in self._queues:
            self._remove_from_queue(stage, issue_number)

    # ------------------------------------------------------------------
    # Queue accessors (non-blocking, return available issues)
    # ------------------------------------------------------------------

    def get_triageable(self, max_count: int) -> list[GitHubIssue]:
        """Return up to *max_count* issues from the find queue."""
        return self._take_from_queue(STAGE_FIND, max_count)

    def get_plannable(self, max_count: int) -> list[GitHubIssue]:
        """Return up to *max_count* issues from the plan queue."""
        return self._take_from_queue(STAGE_PLAN, max_count)

    def get_implementable(self, max_count: int) -> list[GitHubIssue]:
        """Return up to *max_count* issues from the ready queue."""
        return self._take_from_queue(STAGE_READY, max_count)

    def get_reviewable(self, max_count: int) -> list[GitHubIssue]:
        """Return up to *max_count* issues from the review queue."""
        return self._take_from_queue(STAGE_REVIEW, max_count)

    def get_hitl_issues(self) -> set[int]:
        """Return the set of HITL issue numbers."""
        return set(self._hitl_numbers)

    def _take_from_queue(self, stage: str, max_count: int) -> list[GitHubIssue]:
        """Pop up to *max_count* issues from *stage* queue, skipping active."""
        result: list[GitHubIssue] = []
        skipped: list[GitHubIssue] = []
        q = self._queues[stage]

        while q and len(result) < max_count:
            issue = q.popleft()
            self._queue_members[stage].discard(issue.number)
            if issue.number in self._active:
                skipped.append(issue)
            else:
                result.append(issue)

        # Put skipped issues back at the front
        for issue in reversed(skipped):
            q.appendleft(issue)
            self._queue_members[stage].add(issue.number)

        return result

    # ------------------------------------------------------------------
    # Active issue tracking
    # ------------------------------------------------------------------

    def mark_active(self, issue_number: int, stage: str) -> None:
        """Mark an issue as actively being processed in *stage*."""
        self._active[issue_number] = stage

    def mark_complete(self, issue_number: int) -> None:
        """Mark an issue as done processing; increment throughput counter."""
        stage = self._active.pop(issue_number, None)
        if stage and stage in self._processed_count:
            self._processed_count[stage] += 1

    def is_active(self, issue_number: int) -> bool:
        """Return True if the issue is currently being processed."""
        return issue_number in self._active

    def get_active_issues(self) -> dict[int, str]:
        """Return a copy of the active issue tracking dict."""
        return dict(self._active)

    def clear_active(self) -> None:
        """Clear all active issue tracking (used during reset)."""
        self._active.clear()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_pipeline_snapshot(self) -> dict[str, list[dict[str, object]]]:
        """Return a snapshot of all pipeline stages with their issues.

        Each stage maps to a list of dicts with keys:
        ``issue_number``, ``title``, ``url``, ``status``.
        """
        snapshot: dict[str, list[dict[str, object]]] = {}

        # Queued issues from stage queues
        for stage, q in self._queues.items():
            stage_issues: list[dict[str, object]] = []
            for issue in q:
                stage_issues.append(
                    {
                        "issue_number": issue.number,
                        "title": issue.title,
                        "url": issue.url,
                        "status": "queued",
                    }
                )
            snapshot[stage] = stage_issues

        # Active issues (look up details from cache)
        for issue_number, stage in self._active.items():
            cached = self._issue_cache.get(issue_number)
            entry: dict[str, object] = {
                "issue_number": issue_number,
                "title": cached.title if cached else f"Issue #{issue_number}",
                "url": cached.url if cached else "",
                "status": "active",
            }
            if stage in snapshot:
                snapshot[stage].append(entry)
            else:
                snapshot[stage] = [entry]

        # HITL issues
        hitl_list: list[dict[str, object]] = []
        for issue_number in self._hitl_numbers:
            cached = self._issue_cache.get(issue_number)
            hitl_list.append(
                {
                    "issue_number": issue_number,
                    "title": cached.title if cached else f"Issue #{issue_number}",
                    "url": cached.url if cached else "",
                    "status": "hitl",
                }
            )
        snapshot[STAGE_HITL] = hitl_list

        return snapshot

    def get_queue_stats(self) -> QueueStats:
        """Return a snapshot of queue depths, active counts, and throughput."""
        queue_depth: dict[str, int] = {}
        for stage, q in self._queues.items():
            queue_depth[stage] = len(q)
        queue_depth[STAGE_HITL] = len(self._hitl_numbers)

        active_count: dict[str, int] = {}
        for stage in [STAGE_FIND, STAGE_PLAN, STAGE_READY, STAGE_REVIEW, STAGE_HITL]:
            active_count[stage] = sum(1 for s in self._active.values() if s == stage)

        return QueueStats(
            queue_depth=queue_depth,
            active_count=active_count,
            total_processed=dict(self._processed_count),
            last_poll_timestamp=self._last_poll_ts,
        )
