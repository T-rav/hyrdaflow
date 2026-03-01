"""Background worker loop — epic stale detection and progress updates."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from models import StatusCallback

if TYPE_CHECKING:
    from epic import EpicManager

logger = logging.getLogger("hydraflow.epic_monitor_loop")


class EpicMonitorLoop(BaseBackgroundLoop):
    """Periodic check for stale epics and progress updates."""

    def __init__(
        self,
        config: HydraFlowConfig,
        epic_manager: EpicManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(
            worker_name="epic_monitor",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._epic_manager = epic_manager

    def _get_default_interval(self) -> int:
        return self._config.epic_monitor_interval

    async def _do_work(self) -> dict[str, Any] | None:
        stale = await self._epic_manager.check_stale_epics()
        all_progress = self._epic_manager.get_all_progress()
        return {"stale_count": len(stale), "tracked_epics": len(all_progress)}
