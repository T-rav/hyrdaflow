"""Background worker loop -- project manifest refresh.

Periodically re-scans the repository for language markers, build systems,
test frameworks, and CI configuration, then persists the updated manifest
so agents have up-to-date project context.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from manifest import ProjectManifestManager
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
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: Callable[[str, str, dict[str, Any] | None], None],
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(
            worker_name="manifest_refresh",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
            run_on_startup=True,
        )
        self._manifest_manager = manifest_manager
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.manifest_refresh_interval

    async def _do_work(self) -> dict[str, Any] | None:
        content, digest_hash = self._manifest_manager.refresh()
        self._state.update_manifest_state(digest_hash)
        logger.info(
            "Project manifest refreshed (hash=%s, %d chars)",
            digest_hash,
            len(content),
        )
        return {"hash": digest_hash, "length": len(content)}
