"""Background worker loop — epic stale detection and progress updates."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from epic import EpicManager

logger = logging.getLogger("hydraflow.epic_monitor_loop")


class EpicMonitorLoop(BaseBackgroundLoop):
    """Periodic check for stale epics and progress updates."""

    def __init__(
        self,
        config: HydraFlowConfig,
        epic_manager: EpicManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="epic_monitor", config=config, deps=deps)
        self._epic_manager = epic_manager

    def _get_default_interval(self) -> int:
        return self._config.epic_monitor_interval

    async def _do_work(self) -> dict[str, Any] | None:
        stale = await self._epic_manager.check_stale_epics()
        await self._epic_manager.refresh_cache()
        all_progress = self._epic_manager.get_all_progress()
        return {"stale_count": len(stale), "tracked_epics": len(all_progress)}
