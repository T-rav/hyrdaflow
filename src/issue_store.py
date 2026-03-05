"""Centralized GitHub issue store with in-memory work queues."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from models import PipelineIssueStatus, PipelineSnapshotEntry, QueueStats, Task
from subprocess_util import AuthenticationError
from task_source import TaskFetcher

if TYPE_CHECKING:
    from crate_manager import CrateManager

logger = logging.getLogger("hydraflow.issue_store")


class IssueStoreStage(StrEnum):
    """Internal routing stage names for the issue store queues."""

    FIND = "find"
    PLAN = "plan"
    READY = "ready"
    REVIEW = "review"
    HITL = "hitl"


# Backward-compatible module-level aliases
STAGE_FIND = IssueStoreStage.FIND
STAGE_PLAN = IssueStoreStage.PLAN
STAGE_READY = IssueStoreStage.READY
STAGE_REVIEW = IssueStoreStage.REVIEW
STAGE_HITL = IssueStoreStage.HITL

# Priority order — higher index = further along in the pipeline.
# When an issue has multiple HydraFlow labels, it is routed to the
# most advanced stage (highest priority).
_STAGE_PRIORITY = {
    IssueStoreStage.FIND: 0,
    IssueStoreStage.PLAN: 1,
    IssueStoreStage.READY: 2,
    IssueStoreStage.REVIEW: 3,
    IssueStoreStage.HITL: 4,
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
        fetcher: TaskFetcher,
        event_bus: EventBus,
    ) -> None:
        self._config = config
        self._fetcher = fetcher
        self._bus = event_bus

        # Per-stage queues (FIFO)
        self._queues: dict[IssueStoreStage, deque[Task]] = {
            STAGE_FIND: deque(),
            STAGE_PLAN: deque(),
            STAGE_READY: deque(),
            STAGE_REVIEW: deque(),
        }
        # Companion sets for O(1) membership checks (task ids in each queue)
        self._queue_members: dict[IssueStoreStage, set[int]] = {
            STAGE_FIND: set(),
            STAGE_PLAN: set(),
            STAGE_READY: set(),
            STAGE_REVIEW: set(),
        }
        # HITL issues are tracked as a set (display only, not consumed)
        self._hitl_numbers: set[int] = set()

        # Task cache: retains title/url for tasks seen during routing
        self._issue_cache: dict[int, Task] = {}

        # Active issue tracking: issue_number → stage
        self._active: dict[int, str] = {}

        # In-flight protection: items between _take_from_queue and mark_active.
        # Prevents refresh() from re-queuing or evicting items that a phase
        # has dequeued but hasn't yet marked active (semaphore wait gap).
        # Maps task_id → stage so snapshots can include them.
        self._in_flight: dict[int, str] = {}

        # Eager transition protection: items placed by enqueue_transition
        # before GitHub labels have caught up.  Keyed by target stage so
        # _route_incoming_tasks can detect when labels match or exceed the
        # target and clear protection automatically.
        self._eagerly_transitioned: dict[int, IssueStoreStage] = {}

        # Session throughput counters
        self._processed_count: dict[str, int] = {
            STAGE_FIND: 0,
            STAGE_PLAN: 0,
            STAGE_READY: 0,
            STAGE_REVIEW: 0,
            STAGE_HITL: 0,
        }
        # Dedup diagnostics counters (cumulative for current process lifetime)
        self._dedup_stats: dict[str, int] = {
            "incoming_tasks": 0,
            "queued_entries": 0,
            "snapshot_entries": 0,
        }

        self._last_poll_ts: str | None = None
        self._lock = asyncio.Lock()
        self._crate_manager: CrateManager | None = None

    def set_crate_manager(self, cm: CrateManager) -> None:
        """Inject the crate manager after construction (avoids circular init)."""
        self._crate_manager = cm

    def get_uncrated_issues(self) -> list[Task]:
        """Return queued tasks that have no ``milestone_number`` in metadata."""
        uncrated: list[Task] = []
        for q in self._queues.values():
            for task in q:
                if task.metadata.get("milestone_number") is None:
                    uncrated.append(task)
        return uncrated

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
        """Fetch all HydraFlow-labeled tasks and re-route into queues."""
        try:
            issues = await self._fetcher.fetch_all()
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

    def _compute_stage_map(
        self, tasks: list[Task]
    ) -> dict[int, tuple[IssueStoreStage, Task]]:
        """Return {task_id: (best_stage, task)} for all incoming tasks."""
        label_to_stage = self._build_label_map()
        unique_tasks = self._dedupe_tasks(tasks)
        incoming: dict[int, tuple[IssueStoreStage, Task]] = {}
        for task in unique_tasks:
            self._issue_cache[task.id] = task
            best_stage: IssueStoreStage | None = None
            best_priority = -1
            for tag in task.tags:
                stage = label_to_stage.get(tag)
                if stage is not None:
                    prio = _STAGE_PRIORITY.get(stage, -1)
                    if prio > best_priority:
                        best_priority = prio
                        best_stage = stage
            if best_stage is not None:
                incoming[task.id] = (best_stage, task)
        return incoming

    def _dedupe_tasks(self, tasks: list[Task]) -> list[Task]:
        """Return tasks deduplicated by issue id, preserving first-seen order."""
        seen: set[int] = set()
        unique: list[Task] = []
        duplicate_count = 0
        for task in tasks:
            if task.id in seen:
                duplicate_count += 1
                continue
            seen.add(task.id)
            unique.append(task)
        if duplicate_count:
            self._dedup_stats["incoming_tasks"] += duplicate_count
            logger.warning(
                "IssueStore dropped %d duplicate incoming task(s) in refresh",
                duplicate_count,
            )
        return unique

    def _evict_stale_tasks(self, incoming_ids: set[int]) -> None:
        """Remove tasks no longer present in the pipeline from all queues.

        Items that are in-flight (taken from queue, not yet marked active)
        or eagerly transitioned (label swap pending) are protected from
        eviction.
        """
        protected = (
            set(self._active.keys())
            | set(self._in_flight)
            | set(self._eagerly_transitioned)
        )
        for stage, q in self._queues.items():
            members = self._queue_members[stage]
            stale = members - incoming_ids - protected
            if stale:
                self._queues[stage] = deque(t for t in q if t.id not in stale)
                members -= stale
        self._hitl_numbers &= incoming_ids | protected

    def _route_incoming_tasks(
        self, stage_map: dict[int, tuple[IssueStoreStage, Task]]
    ) -> None:
        """Move each task to its target queue if it isn't already there.

        Items that are in-flight or eagerly transitioned are protected:
        - In-flight items are never re-routed.
        - Eagerly-transitioned items have their protection cleared once
          incoming labels match or exceed the target stage (labels caught up).
          Until then, stale labels are ignored to prevent backward movement.
        """
        for task_id, (stage, task) in stage_map.items():
            if task_id in self._active or task_id in self._in_flight:
                continue

            # Handle eagerly-transitioned items
            eager_stage = self._eagerly_transitioned.get(task_id)
            if eager_stage is not None:
                if _STAGE_PRIORITY.get(stage, -1) >= _STAGE_PRIORITY.get(
                    eager_stage, -1
                ):
                    del self._eagerly_transitioned[task_id]  # labels caught up
                else:
                    continue  # stale labels, skip

            if stage == STAGE_HITL:
                self._hitl_numbers.add(task_id)
                self._remove_from_all_queues(task_id)
                continue
            current_stage = self._find_queue_stage(task_id)
            if current_stage == stage:
                continue
            if current_stage is not None:
                self._remove_from_queue(current_stage, task_id)
            self._hitl_numbers.discard(task_id)
            self._queues[stage].append(task)
            self._queue_members[stage].add(task_id)

    def _route_issues(self, tasks: list[Task]) -> None:
        """Route fetched tasks into the correct queues.

        - Each task goes to the most advanced stage matching its tags.
        - Tasks already active are not re-queued.
        - Tasks that changed tags are moved between queues.
        - Tasks no longer returned by the fetcher are removed from queues.
        """
        stage_map = self._compute_stage_map(tasks)
        incoming_ids = set(stage_map.keys())
        self._evict_stale_tasks(incoming_ids)
        self._route_incoming_tasks(stage_map)

        # Prune eagerly-transitioned entries for issues that vanished
        # entirely (e.g. closed issues no longer returned by the fetcher).
        vanished = (
            set(self._eagerly_transitioned)
            - incoming_ids
            - set(self._active.keys())
            - set(self._in_flight)
        )
        for tid in vanished:
            del self._eagerly_transitioned[tid]

    def _build_label_map(self) -> dict[str, IssueStoreStage]:
        """Build a mapping from label name → pipeline stage."""
        m: dict[str, IssueStoreStage] = {}
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

    def _find_queue_stage(self, issue_number: int) -> IssueStoreStage | None:
        """Return the stage name if the issue is in any queue, else None."""
        for stage, members in self._queue_members.items():
            if issue_number in members:
                return stage
        return None

    def _remove_from_queue(self, stage: IssueStoreStage, issue_number: int) -> None:
        """Remove a task from a specific queue."""
        if issue_number in self._queue_members[stage]:
            self._queues[stage] = deque(
                t for t in self._queues[stage] if t.id != issue_number
            )
            self._queue_members[stage].discard(issue_number)

    def _remove_from_all_queues(self, issue_number: int) -> None:
        """Remove an issue from all regular queues."""
        for stage in self._queues:
            self._remove_from_queue(stage, issue_number)

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        """Immediately route *task* into *next_stage* in-memory.

        This provides an eager handoff between phases so downstream workers
        can pick up transitioned issues without waiting for the next GitHub
        polling cycle.  The item is protected from ``refresh()`` eviction /
        re-routing until GitHub labels catch up to the target stage.
        """
        stage_alias: dict[str, IssueStoreStage] = {
            "find": STAGE_FIND,
            "plan": STAGE_PLAN,
            "ready": STAGE_READY,
            "review": STAGE_REVIEW,
            "hitl": STAGE_HITL,
        }
        stage = stage_alias.get(next_stage)
        if stage is None:
            return

        self._in_flight.pop(task.id, None)
        self._issue_cache[task.id] = task
        self._remove_from_all_queues(task.id)
        self._hitl_numbers.discard(task.id)

        if stage == STAGE_HITL:
            self._hitl_numbers.add(task.id)
            self._eagerly_transitioned[task.id] = stage
            self._publish_queue_update_nowait()
            return

        if task.id in self._queue_members[stage]:
            self._dedup_stats["queued_entries"] += 1
            self._eagerly_transitioned[task.id] = stage
            self._publish_queue_update_nowait()
            return
        self._queues[stage].append(task)
        self._queue_members[stage].add(task.id)
        self._eagerly_transitioned[task.id] = stage
        self._publish_queue_update_nowait()

    # ------------------------------------------------------------------
    # Queue accessors (non-blocking, return available issues)
    # ------------------------------------------------------------------

    def get_triageable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the find queue."""
        return self._take_from_queue(STAGE_FIND, max_count)

    def get_plannable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the plan queue."""
        return self._take_from_queue(STAGE_PLAN, max_count)

    def get_implementable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the ready queue."""
        return self._take_from_queue(STAGE_READY, max_count)

    def get_reviewable(self, max_count: int) -> list[Task]:
        """Return up to *max_count* issues from the review queue."""
        return self._take_from_queue(STAGE_REVIEW, max_count)

    def get_hitl_issues(self) -> set[int]:
        """Return the set of HITL issue numbers."""
        return set(self._hitl_numbers)

    def _take_from_queue(self, stage: IssueStoreStage, max_count: int) -> list[Task]:
        """Pop up to *max_count* tasks from *stage* queue, skipping active.

        Safety note: This method is synchronous with no ``await`` points, so
        the GIL guarantees it cannot be interleaved with ``_route_issues``
        (which runs under ``self._lock`` inside ``refresh()``).  A concurrent
        ``refresh()`` will block on the lock until its own ``_route_issues``
        call completes atomically, and this synchronous method runs to
        completion within a single event-loop tick.
        """
        result: list[Task] = []
        skipped: list[Task] = []
        q = self._queues[stage]

        while q and len(result) < max_count:
            task = q.popleft()
            self._queue_members[stage].discard(task.id)
            if task.id in self._active or (
                stage != STAGE_FIND
                and self._crate_manager is not None
                and self._crate_manager.active_crate_number is not None
                and not self._crate_manager.is_in_active_crate(task)
            ):
                skipped.append(task)
            else:
                result.append(task)

        # Put skipped tasks back at the front
        for task in reversed(skipped):
            q.appendleft(task)
            self._queue_members[stage].add(task.id)

        if result:
            for t in result:
                self._in_flight[t.id] = stage
            self._publish_queue_update_nowait()
        return result

    # ------------------------------------------------------------------
    # Active issue tracking
    # ------------------------------------------------------------------

    def mark_active(self, task_id: int, stage: str) -> None:
        """Mark a task as actively being processed in *stage*."""
        self._in_flight.pop(task_id, None)
        self._active[task_id] = stage
        self._publish_queue_update_nowait()

    def mark_complete(self, task_id: int) -> None:
        """Mark a task as done processing; increment throughput counter."""
        self._in_flight.pop(task_id, None)
        stage = self._active.pop(task_id, None)
        if stage and stage in self._processed_count:
            self._processed_count[stage] += 1
        self._publish_queue_update_nowait()

    def is_active(self, task_id: int) -> bool:
        """Return True if the task is currently being processed."""
        return task_id in self._active

    def is_in_pipeline(self, issue_number: int) -> bool:
        """Return True if the issue is queued, in-flight, or active."""
        if issue_number in self._active or issue_number in self._in_flight:
            return True
        return any(any(t.id == issue_number for t in q) for q in self._queues.values())

    def get_active_issues(self) -> dict[int, str]:
        """Return a copy of the active issue tracking dict."""
        return dict(self._active)

    def release_in_flight(self, task_ids: set[int]) -> None:
        """Remove *task_ids* from the in-flight protection set.

        Called after a batch completes (in a ``finally`` block) to ensure
        no orphaned in-flight entries survive if a worker exits without
        reaching ``mark_active`` or ``mark_complete``.
        """
        for tid in task_ids:
            self._in_flight.pop(tid, None)

    def clear_active(self) -> None:
        """Clear all active issue tracking (used during reset)."""
        self._active.clear()
        self._in_flight.clear()
        self._eagerly_transitioned.clear()
        self._publish_queue_update_nowait()

    def _publish_queue_update_nowait(self) -> None:
        """Publish a queue update event without requiring an async caller."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        stats = self.get_queue_stats()
        loop.create_task(
            self._bus.publish(
                HydraFlowEvent(
                    type=EventType.QUEUE_UPDATE,
                    data=stats.model_dump(),
                )
            )
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _epic_metadata(self, task: Task) -> dict[str, int | bool]:
        """Return epic metadata fields for a pipeline snapshot entry."""
        epic_child_labels = {lbl.lower() for lbl in self._config.epic_child_label}
        task_labels = {t.lower() for t in task.tags}
        if not (epic_child_labels & task_labels):
            return {}
        result: dict[str, int | bool] = {"is_epic_child": True}
        epic_num = task.metadata.get("epic_number")
        if epic_num:
            result["epic_number"] = int(epic_num)
        else:
            match = re.search(r"[Pp]arent\s+[Ee]pic[:\s#]*(\d+)", task.body)
            if match:
                result["epic_number"] = int(match.group(1))
        return result

    def _snapshot_queued(self) -> dict[str, list[PipelineSnapshotEntry]]:
        """Return queued tasks grouped by stage."""
        snapshot: dict[str, list[PipelineSnapshotEntry]] = {}
        for stage, q in self._queues.items():
            stage_seen: set[int] = set()
            entries: list[PipelineSnapshotEntry] = []
            duplicate_count = 0
            for task in q:
                if task.id in stage_seen:
                    duplicate_count += 1
                    continue
                stage_seen.add(task.id)
                entry = PipelineSnapshotEntry(
                    issue_number=task.id,
                    title=task.title,
                    url=task.source_url,
                    status="queued",
                )
                epic_meta = self._epic_metadata(task)
                if epic_meta:
                    entry.update(epic_meta)  # type: ignore[typeddict-item]
                entries.append(entry)
            if duplicate_count:
                self._dedup_stats["snapshot_entries"] += duplicate_count
                logger.warning(
                    "IssueStore snapshot dropped %d duplicate queued %s for stage %s",
                    duplicate_count,
                    "entry" if duplicate_count == 1 else "entries",
                    stage,
                )
            snapshot[stage] = entries
        return snapshot

    def _snapshot_active(self) -> dict[str, list[PipelineSnapshotEntry]]:
        """Return active tasks grouped by stage."""
        active_by_stage: dict[str, list[PipelineSnapshotEntry]] = {}
        for issue_number, stage in self._active.items():
            cached = self._issue_cache.get(issue_number)
            entry = PipelineSnapshotEntry(
                issue_number=issue_number,
                title=cached.title if cached else f"Issue #{issue_number}",
                url=cached.source_url if cached else "",
                status="active",
            )
            if cached:
                epic_meta = self._epic_metadata(cached)
                if epic_meta:
                    entry.update(epic_meta)  # type: ignore[typeddict-item]
            active_by_stage.setdefault(stage, []).append(entry)
        return active_by_stage

    def _snapshot_hitl(self) -> list[PipelineSnapshotEntry]:
        """Return HITL tasks as a flat list."""
        hitl_list: list[PipelineSnapshotEntry] = []
        for issue_number in self._hitl_numbers:
            cached = self._issue_cache.get(issue_number)
            entry = PipelineSnapshotEntry(
                issue_number=issue_number,
                title=cached.title if cached else f"Issue #{issue_number}",
                url=cached.source_url if cached else "",
                status="hitl",
            )
            if cached:
                epic_meta = self._epic_metadata(cached)
                if epic_meta:
                    entry.update(epic_meta)  # type: ignore[typeddict-item]
            hitl_list.append(entry)
        return hitl_list

    def _snapshot_in_flight(self) -> dict[str, list[PipelineSnapshotEntry]]:
        """Return in-flight tasks grouped by their origin stage.

        In-flight items have been dequeued but not yet marked active.
        Including them in the snapshot prevents them from vanishing
        in the dashboard during the dequeue-to-mark_active window.
        """
        by_stage: dict[str, list[PipelineSnapshotEntry]] = {}
        for task_id, stage in self._in_flight.items():
            cached = self._issue_cache.get(task_id)
            entry = PipelineSnapshotEntry(
                issue_number=task_id,
                title=cached.title if cached else f"Issue #{task_id}",
                url=cached.source_url if cached else "",
                status=PipelineIssueStatus.PROCESSING,
            )
            if cached:
                epic_meta = self._epic_metadata(cached)
                if epic_meta:
                    entry.update(epic_meta)  # type: ignore[typeddict-item]
            by_stage.setdefault(stage, []).append(entry)
        return by_stage

    def get_pipeline_snapshot(self) -> dict[str, list[PipelineSnapshotEntry]]:
        """Return a snapshot of all pipeline stages with their issues.

        Each stage maps to a list of dicts with keys:
        ``issue_number``, ``title``, ``url``, ``status``.
        """
        snapshot = self._snapshot_queued()
        for stage, entries in self._snapshot_in_flight().items():
            snapshot.setdefault(stage, []).extend(entries)
        for stage, entries in self._snapshot_active().items():
            snapshot.setdefault(stage, []).extend(entries)
        snapshot[STAGE_HITL] = self._snapshot_hitl()
        return snapshot

    def get_queue_stats(self) -> QueueStats:
        """Return a snapshot of queue depths, active counts, and throughput."""
        queue_depth: dict[str, int] = {}
        for stage, q in self._queues.items():
            queue_depth[stage] = len({task.id for task in q})
        queue_depth[STAGE_HITL] = len(self._hitl_numbers)

        active_count: dict[str, int] = {}
        for stage in [STAGE_FIND, STAGE_PLAN, STAGE_READY, STAGE_REVIEW, STAGE_HITL]:
            active_count[stage] = sum(1 for s in self._active.values() if s == stage)

        return QueueStats(
            queue_depth=queue_depth,
            active_count=active_count,
            total_processed=dict(self._processed_count),
            last_poll_timestamp=self._last_poll_ts,
            dedup_stats=dict(self._dedup_stats),
            in_flight_count=len(self._in_flight),
        )
