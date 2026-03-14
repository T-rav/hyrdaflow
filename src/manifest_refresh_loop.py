"""Background worker loop -- project manifest refresh.

Periodically re-scans the repository for language markers, build systems,
test frameworks, and CI configuration, then persists the updated manifest
so agents have up-to-date project context.
"""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from manifest import ProjectManifestManager
from manifest_issue_syncer import ManifestIssueSyncer
from models import ManifestRefreshSummary
from state import StateTracker

logger = logging.getLogger("hydraflow.manifest_refresh_loop")


class ManifestRefreshLoop(BaseBackgroundLoop):
    """Periodically rescans the repo and updates the project manifest file.

    Follows the same background-worker pattern as
    :class:`MemorySyncLoop` and :class:`MetricsSyncLoop`.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        manifest_manager: ProjectManifestManager,
        state: StateTracker,
        deps: LoopDeps,
        manifest_syncer: ManifestIssueSyncer | None = None,
    ) -> None:
        super().__init__(
            worker_name="manifest_refresh",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._manifest_manager = manifest_manager
        self._state = state
        self._syncer = manifest_syncer

    def _get_default_interval(self) -> int:
        return self._config.manifest_refresh_interval

    async def _do_work(self) -> dict[str, Any] | None:
        content, digest_hash = self._manifest_manager.refresh()
        self._state.update_manifest_state(digest_hash)
        if self._syncer is not None:
            await self._syncer.sync(content, digest_hash, source="manifest-refresh")
        logger.info(
            "Project manifest refreshed (hash=%s, %d chars)",
            digest_hash,
            len(content),
        )
        result: ManifestRefreshSummary = {"hash": digest_hash, "length": len(content)}
        return dict(result)
