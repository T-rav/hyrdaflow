"""In-process event bus for broadcasting state changes to the dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from file_util import atomic_write


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


def _log_persist_failure(task: asyncio.Future[None]) -> None:
    """Log unhandled exceptions from fire-and-forget persist tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("Event persist task failed: %s", exc, exc_info=exc)


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
    EPIC_READY = "epic_ready"
    PIPELINE_STATS = "pipeline_stats"


class HydraFlowEvent(BaseModel):
    """A single event published on the bus."""

    id: int = Field(default_factory=lambda: next(_event_counter))
    type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class EventLog:
    """Append-only JSONL file for persisting events to disk.

    Each event is serialized as a single JSON line. Corrupt lines
    are skipped during loading (logged as warnings, never crash).
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _append_sync(self, line: str) -> None:
        """Synchronous append — called via ``asyncio.to_thread``."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a") as f:
                f.write(line + "\n")
                f.flush()
        except OSError:
            logger.warning(
                "Could not append to event log %s",
                self._path,
                exc_info=True,
            )

    async def append(self, event: HydraFlowEvent) -> None:
        """Serialize *event* to JSON and append a line to the log file."""
        line = event.model_dump_json()
        await asyncio.to_thread(self._append_sync, line)

    def _load_sync(
        self,
        since: datetime | None = None,
        max_events: int = 5000,
    ) -> list[HydraFlowEvent]:
        """Synchronous load — called via ``asyncio.to_thread``."""
        if not self._path.exists():
            return []

        events: list[HydraFlowEvent] = []
        try:
            with open(self._path) as f:
                for line_num, raw_line in enumerate(f, 1):
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    try:
                        event = HydraFlowEvent.model_validate_json(stripped)
                    except ValidationError:
                        logger.warning(
                            "Skipping corrupt event log line %d in %s",
                            line_num,
                            self._path,
                            exc_info=True,
                        )
                        continue

                    if since is not None:
                        try:
                            ts = datetime.fromisoformat(event.timestamp)
                            if ts < since:
                                continue
                        except (ValueError, TypeError):
                            pass  # Keep events with unparseable timestamps

                    events.append(event)
        except OSError:
            logger.warning(
                "Could not read event log %s",
                self._path,
                exc_info=True,
            )
            return []

        # Return only the last max_events
        if len(events) > max_events:
            events = events[-max_events:]
        return events

    async def load(
        self,
        since: datetime | None = None,
        max_events: int = 5000,
    ) -> list[HydraFlowEvent]:
        """Read events from the JSONL file, optionally filtered by timestamp."""
        return await asyncio.to_thread(self._load_sync, since, max_events)

    def _rotate_sync(self, max_size_bytes: int, max_age_days: int) -> None:
        """Synchronous rotation — called via ``asyncio.to_thread``."""
        if not self._path.exists():
            return

        try:
            file_size = self._path.stat().st_size
        except OSError:
            return

        if file_size <= max_size_bytes:
            return

        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        kept_lines: list[str] = []

        with open(self._path) as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    event = HydraFlowEvent.model_validate_json(stripped)
                    ts = datetime.fromisoformat(event.timestamp)
                    if ts >= cutoff:
                        kept_lines.append(stripped)
                except (ValidationError, ValueError):
                    logger.debug(
                        "Dropping corrupt event line during rotation",
                        exc_info=True,
                    )
                    continue

        content = "\n".join(kept_lines) + "\n" if kept_lines else ""
        atomic_write(self._path, content)

    async def rotate(self, max_size_bytes: int, max_age_days: int) -> None:
        """Rotate the log file if it exceeds *max_size_bytes*.

        Keeps only events within *max_age_days*. Uses atomic write
        (temp file + ``os.replace``) following the ``StateTracker`` pattern.
        """
        await asyncio.to_thread(self._rotate_sync, max_size_bytes, max_age_days)


class EventBus:
    """Async pub/sub bus with history replay.

    Subscribers receive an ``asyncio.Queue`` that yields
    :class:`HydraFlowEvent` objects as they are published.
    """

    def __init__(
        self,
        max_history: int = 5000,
        event_log: EventLog | None = None,
    ) -> None:
        self._subscribers: list[asyncio.Queue[HydraFlowEvent]] = []
        self._history: list[HydraFlowEvent] = []
        self._max_history = max_history
        self._event_log = event_log
        self._active_session_id: str | None = None
        self._active_repo: str = ""
        self._pending_persists: set[asyncio.Task[None]] = set()

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

        if self._event_log is not None:
            task = asyncio.create_task(self._persist_event(event))
            self._pending_persists.add(task)
            task.add_done_callback(self._pending_persists.discard)
            task.add_done_callback(_log_persist_failure)

    async def _persist_event(self, event: HydraFlowEvent) -> None:
        """Write event to disk, logging any errors without crashing."""
        try:
            assert self._event_log is not None  # noqa: S101
            await self._event_log.append(event)
        except Exception:
            logger.warning("Failed to persist event to disk", exc_info=True)

    async def flush_persists(self) -> None:
        """Await all in-flight persist tasks, suppressing exceptions.

        Use in tests instead of ``asyncio.sleep(0)`` to reliably drain
        fire-and-forget persist tasks without timing assumptions.
        """
        if self._pending_persists:
            await asyncio.gather(*self._pending_persists, return_exceptions=True)

    async def load_history_from_disk(self) -> None:
        """Populate in-memory history from the on-disk event log.

        After loading, advances the global event counter past the highest
        historical ID so that new events are never mistaken for duplicates
        by the frontend's deduplication logic.
        """
        if self._event_log is None:
            return
        events = await self._event_log.load(max_events=self._max_history)
        self._history = events
        if events:
            max_id = max(e.id for e in events)
            _event_counter.advance(max_id + 1)

    async def load_events_since(self, since: datetime) -> list[HydraFlowEvent] | None:
        """Load persisted events from disk since *since*.

        Returns ``None`` when no event log is configured (caller should
        fall back to in-memory history).
        """
        if self._event_log is None:
            return None
        return await self._event_log.load(since=since)

    async def rotate_log(self, max_size_bytes: int, max_age_days: int) -> None:
        """Rotate the on-disk event log if it exceeds *max_size_bytes*."""
        if self._event_log is None:
            return
        await self._event_log.rotate(max_size_bytes, max_age_days)

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
