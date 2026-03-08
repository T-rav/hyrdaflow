"""Dolt-backed event bus for broadcasting state changes to the dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class _Counter:
    """Monotonic event ID generator that can be advanced forward.

    After loading persisted history, :meth:`advance` ensures new IDs
    always exceed historical IDs so the frontend's deduplication logic
    never silently drops live events.
    """

    def __init__(self) -> None:
        self._it = itertools.count()

    def __next__(self) -> int:
        return next(self._it)

    def advance(self, minimum: int) -> None:
        """Advance so the next ID is >= *minimum*."""
        self._it = itertools.count(minimum)


_event_counter = _Counter()

logger = logging.getLogger("hydraflow.events")


class EventType(StrEnum):
    """Categories of events published by the orchestrator."""

    PHASE_CHANGE = "phase_change"
    WORKER_UPDATE = "worker_update"
    TRANSCRIPT_LINE = "transcript_line"
    PR_CREATED = "pr_created"
    REVIEW_UPDATE = "review_update"
    TRIAGE_UPDATE = "triage_update"
    PLANNER_UPDATE = "planner_update"
    MERGE_UPDATE = "merge_update"
    CI_CHECK = "ci_check"
    HITL_ESCALATION = "hitl_escalation"
    ISSUE_CREATED = "issue_created"
    HITL_UPDATE = "hitl_update"
    ORCHESTRATOR_STATUS = "orchestrator_status"
    ERROR = "error"
    MEMORY_SYNC = "memory_sync"
    METRICS_UPDATE = "metrics_update"
    BACKGROUND_WORKER_STATUS = "background_worker_status"
    QUEUE_UPDATE = "queue_update"
    SYSTEM_ALERT = "system_alert"
    VERIFICATION_JUDGE = "verification_judge"
    TRANSCRIPT_SUMMARY = "transcript_summary"
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    EPIC_UPDATE = "epic_update"
    EPIC_PROGRESS = "epic_progress"
    EPIC_READY = "epic_ready"
    EPIC_RELEASING = "epic_releasing"
    EPIC_RELEASED = "epic_released"
    PIPELINE_STATS = "pipeline_stats"
    VISUAL_GATE = "visual_gate"
    BASELINE_UPDATE = "baseline_update"
    CRATE_ACTIVATED = "crate_activated"
    CRATE_COMPLETED = "crate_completed"
    REVIEW_INSIGHT_RECORDED = "review_insight_recorded"
    HARNESS_FAILURE_RECORDED = "harness_failure_recorded"
    RETROSPECTIVE_RECORDED = "retrospective_recorded"
    METRICS_SNAPSHOT_RECORDED = "metrics_snapshot_recorded"


class HydraFlowEvent(BaseModel):
    """A single event published on the bus."""

    id: int = Field(default_factory=lambda: next(_event_counter))
    type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class EventBus:
    """Async pub/sub bus with history replay.

    Subscribers receive an ``asyncio.Queue`` that yields
    :class:`HydraFlowEvent` objects as they are published.
    """

    def __init__(
        self,
        max_history: int = 5000,
        state: Any | None = None,
    ) -> None:
        self._subscribers: list[asyncio.Queue[HydraFlowEvent]] = []
        self._history: list[HydraFlowEvent] = []
        self._max_history = max_history
        self._active_session_id: str | None = None
        self._active_repo: str = ""
        self._state = state

    def set_session_id(self, session_id: str | None) -> None:
        """Set the active session ID to auto-inject into published events."""
        self._active_session_id = session_id

    def set_repo(self, repo: str) -> None:
        """Set the active repo slug to auto-inject into published event data."""
        self._active_repo = repo

    @property
    def current_session_id(self) -> str | None:
        """Return the active session ID, if any."""
        return self._active_session_id

    async def publish(self, event: HydraFlowEvent) -> None:
        """Publish *event* to all subscribers and append to history."""
        if event.session_id is None and getattr(self, "_active_session_id", None):
            event.session_id = self._active_session_id
        if (
            self._active_repo
            and isinstance(event.data, dict)
            and "repo" not in event.data
        ):
            event.data["repo"] = self._active_repo
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest if subscriber is slow
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                queue.put_nowait(event)

        # Write to Dolt
        if self._state and hasattr(self._state, "append_event"):
            try:
                self._state.append_event(event.model_dump())
            except Exception:  # noqa: BLE001
                logger.debug("Dolt event write failed", exc_info=True)

    async def load_history_from_dolt(self) -> None:
        """Populate in-memory history from Dolt events table."""
        if not self._state or not hasattr(self._state, "load_recent_events"):
            return
        try:
            events_data = self._state.load_recent_events(self._max_history)
            self._history = []
            for row in events_data:
                try:
                    self._history.append(HydraFlowEvent.model_validate(row))
                except ValidationError:
                    logger.debug("Skipping invalid event from Dolt")
            if self._history:
                max_id = max(e.id for e in self._history)
                _event_counter.advance(max_id + 1)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load event history from Dolt", exc_info=True)

    async def load_events_since_dolt(self, since: datetime) -> list[HydraFlowEvent] | None:
        """Load events from Dolt since the given timestamp."""
        if not self._state or not hasattr(self._state, "load_events_since"):
            return None
        try:
            rows = self._state.load_events_since(since.isoformat())
            return [HydraFlowEvent.model_validate(r) for r in rows]
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load events from Dolt", exc_info=True)
            return None

    def subscribe(self, max_queue: int = 500) -> asyncio.Queue[HydraFlowEvent]:
        """Return a new queue that will receive future events."""
        queue: asyncio.Queue[HydraFlowEvent] = asyncio.Queue(maxsize=max_queue)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[HydraFlowEvent]) -> None:
        """Remove *queue* from the subscriber list."""
        with contextlib.suppress(ValueError):
            self._subscribers.remove(queue)

    @contextlib.asynccontextmanager
    async def subscription(
        self, max_queue: int = 500
    ) -> AsyncIterator[asyncio.Queue[HydraFlowEvent]]:
        """Async context manager that auto-unsubscribes on exit."""
        queue = self.subscribe(max_queue)
        try:
            yield queue
        finally:
            self.unsubscribe(queue)

    def get_history(self) -> list[HydraFlowEvent]:
        """Return a copy of all recorded events."""
        return list(self._history)

    def clear(self) -> None:
        """Remove all history and subscribers."""
        self._history.clear()
        self._subscribers.clear()
        self._active_session_id = None
        self._active_repo = ""
