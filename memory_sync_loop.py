"""Background worker loop — memory sync."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from issue_fetcher import IssueFetcher
from memory import MemorySyncWorker
from models import MemoryIssueData, StatusCallback

logger = logging.getLogger("hydraflow.memory_sync_loop")


class MemorySyncLoop(BaseBackgroundLoop):
    """Polls ``hydraflow-memory`` issues and rebuilds the digest."""

    def __init__(
        self,
        config: HydraFlowConfig,
        fetcher: IssueFetcher,
        memory_sync: MemorySyncWorker,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(
            worker_name="memory_sync",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._fetcher = fetcher
        self._memory_sync = memory_sync

    def _get_default_interval(self) -> int:
        return self._config.memory_sync_interval

    async def _do_work(self) -> dict[str, Any] | None:
        issues = await self._fetcher.fetch_issues_by_labels(
            self._config.memory_label, limit=100
        )
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
        return dict(stats)
