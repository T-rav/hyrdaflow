"""Background worker loop — metrics sync."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from issue_store import IssueStore

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
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="metrics", config=config, deps=deps)
        self._store = store
        self._metrics_manager = metrics_manager

    def _get_default_interval(self) -> int:
        return self._config.metrics_sync_interval

    async def _do_work(self) -> dict[str, Any] | None:
        queue_stats = self._store.get_queue_stats()
        stats = await self._metrics_manager.sync(queue_stats)
        return dict(stats)
