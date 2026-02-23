"""Background worker loop — memory sync."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_fetcher import IssueFetcher
from memory import MemorySyncWorker
from models import MemoryIssueData
from subprocess_util import AuthenticationError, CreditExhaustedError

logger = logging.getLogger("hydraflow.memory_sync_loop")


class MemorySyncLoop:
    """Polls ``hydraflow-memory`` issues and rebuilds the digest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        fetcher: IssueFetcher,
        memory_sync: MemorySyncWorker,
        bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: Callable[[str, str, dict[str, Any] | None], None],
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        self._config = config
        self._fetcher = fetcher
        self._memory_sync = memory_sync
        self._bus = bus
        self._stop_event = stop_event
        self._status_cb = status_cb
        self._enabled_cb = enabled_cb
        self._sleep_fn = sleep_fn
        self._interval_cb = interval_cb

    def _get_interval(self) -> int:
        """Return the effective interval, preferring dynamic override."""
        if self._interval_cb is not None:
            return self._interval_cb("memory_sync")
        return self._config.memory_sync_interval

    async def run(self) -> None:
        """Continuously poll ``hydraflow-memory`` issues and rebuild the digest."""
        while not self._stop_event.is_set():
            interval = self._get_interval()
            if not self._enabled_cb("memory_sync"):
                await self._sleep_fn(interval)
                continue
            try:
                issues = await self._fetcher.fetch_issues_by_labels(
                    self._config.memory_label, limit=100
                )
                # Convert to typed dicts for the sync worker
                issue_dicts: list[MemoryIssueData] = [
                    MemoryIssueData(
                        number=i.number,
                        title=i.title,
                        body=i.body,
                        createdAt=i.created_at,
                    )
                    for i in issues
                ]
                stats = await self._memory_sync.sync(issue_dicts)
                await self._memory_sync.publish_sync_event(stats)
                last_run = datetime.now(UTC).isoformat()
                self._status_cb("memory_sync", "ok", dict(stats))
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BACKGROUND_WORKER_STATUS,
                        data={
                            "worker": "memory_sync",
                            "status": "ok",
                            "last_run": last_run,
                            "details": dict(stats),
                        },
                    )
                )
            except (AuthenticationError, CreditExhaustedError):
                raise
            except Exception:
                logger.exception(
                    "Memory sync loop iteration failed — will retry next cycle"
                )
                last_run = datetime.now(UTC).isoformat()
                self._status_cb("memory_sync", "error", None)
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BACKGROUND_WORKER_STATUS,
                        data={
                            "worker": "memory_sync",
                            "status": "error",
                            "last_run": last_run,
                            "details": {},
                        },
                    )
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.ERROR,
                        data={
                            "message": "Memory sync loop error",
                            "source": "memory_sync",
                        },
                    )
                )
            await self._sleep_fn(interval)
