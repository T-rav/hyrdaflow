"""Background worker loop — metrics sync."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from subprocess_util import AuthenticationError, CreditExhaustedError

logger = logging.getLogger("hydraflow.metrics_sync_loop")


class MetricsSyncLoop:
    """Aggregates and persists metrics snapshots."""

    def __init__(
        self,
        config: HydraFlowConfig,
        store: IssueStore,
        metrics_manager: Any,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: Callable[[str, str, dict[str, Any] | None], None],
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._metrics_manager = metrics_manager
        self._bus = event_bus
        self._stop_event = stop_event
        self._status_cb = status_cb
        self._enabled_cb = enabled_cb
        self._sleep_fn = sleep_fn
        self._interval_cb = interval_cb

    def _get_interval(self) -> int:
        """Return the effective interval, preferring dynamic override."""
        if self._interval_cb is not None:
            return self._interval_cb("metrics")
        return self._config.metrics_sync_interval

    async def run(self) -> None:
        """Continuously aggregate and persist metrics snapshots."""
        while not self._stop_event.is_set():
            interval = self._get_interval()
            if not self._enabled_cb("metrics"):
                await self._sleep_fn(interval)
                continue
            try:
                queue_stats = self._store.get_queue_stats()
                stats = await self._metrics_manager.sync(queue_stats)
                last_run = datetime.now(UTC).isoformat()
                self._status_cb("metrics", "ok", stats)
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BACKGROUND_WORKER_STATUS,
                        data={
                            "worker": "metrics",
                            "status": "ok",
                            "last_run": last_run,
                            "details": stats or {},
                        },
                    )
                )
            except (AuthenticationError, CreditExhaustedError):
                raise
            except Exception:
                logger.exception(
                    "Metrics sync loop iteration failed — will retry next cycle"
                )
                last_run = datetime.now(UTC).isoformat()
                self._status_cb("metrics", "error", None)
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BACKGROUND_WORKER_STATUS,
                        data={
                            "worker": "metrics",
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
                            "message": "Metrics sync loop error",
                            "source": "metrics",
                        },
                    )
                )
            await self._sleep_fn(interval)
