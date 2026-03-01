"""Background worker loop — metrics sync."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from issue_store import IssueStore
from models import StatusCallback

if TYPE_CHECKING:
    from metrics_manager import MetricsManager

logger = logging.getLogger("hydraflow.metrics_sync_loop")


class MetricsSyncLoop(BaseBackgroundLoop):
    """Aggregates and persists metrics snapshots."""

    def __init__(
        self,
        config: HydraFlowConfig,
        store: IssueStore,
        metrics_manager: MetricsManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(
            worker_name="metrics",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._store = store
        self._metrics_manager = metrics_manager

    def _get_default_interval(self) -> int:
        return self._config.metrics_sync_interval

    async def _do_work(self) -> dict[str, Any] | None:
        queue_stats = self._store.get_queue_stats()
        stats = await self._metrics_manager.sync(queue_stats)
        return dict(stats)
