"""Background worker loop — garbage-collect expired run artifacts."""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from run_recorder import RunRecorder

logger = logging.getLogger("hydraflow.runs_gc_loop")


class RunsGCLoop(BaseBackgroundLoop):
    """Periodically purges expired and oversized run artifacts.

    Enforces the configured retention TTL (``artifact_retention_days``)
    and size cap (``artifact_max_size_mb``) by delegating to
    :class:`RunRecorder` purge methods.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        run_recorder: RunRecorder,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="runs_gc", config=config, deps=deps)
        self._recorder = run_recorder

    def _get_default_interval(self) -> int:
        return self._config.runs_gc_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Run one GC cycle: purge expired runs, then enforce size cap."""
        expired = self._recorder.purge_expired(self._config.artifact_retention_days)
        oversized = self._recorder.purge_oversized(self._config.artifact_max_size_mb)
        stats = self._recorder.get_storage_stats()

        total_purged = expired + oversized
        if total_purged > 0:
            logger.info(
                "Runs GC: purged %d expired, %d oversized (%d runs remain, %.1f MB)",
                expired,
                oversized,
                stats["total_runs"],
                stats["total_mb"],
            )

        return {
            "expired_purged": expired,
            "oversized_purged": oversized,
            "total_runs": stats["total_runs"],
            "total_mb": stats["total_mb"],
            "issues": stats["issues"],
        }
