"""Background worker loop -- project manifest refresh.

Periodically re-scans the repository for language markers, build systems,
test frameworks, and CI configuration, then persists the updated manifest
so agents have up-to-date project context.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from manifest import ProjectManifestManager
from state import StateTracker
from subprocess_util import AuthenticationError, CreditExhaustedError

logger = logging.getLogger("hydraflow.manifest_refresh_loop")


class ManifestRefreshLoop:
    """Periodically rescans the repo and updates the project manifest file.

    Follows the same background-worker pattern as
    :class:`MemorySyncLoop` and :class:`MetricsSyncLoop`.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        manifest_manager: ProjectManifestManager,
        state: StateTracker,
        bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: Callable[[str, str, dict[str, Any] | None], None],
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        self._config = config
        self._manifest_manager = manifest_manager
        self._state = state
        self._bus = bus
        self._stop_event = stop_event
        self._status_cb = status_cb
        self._enabled_cb = enabled_cb
        self._sleep_fn = sleep_fn
        self._interval_cb = interval_cb

    def _get_interval(self) -> int:
        """Return the effective interval, preferring dynamic override."""
        if self._interval_cb is not None:
            return self._interval_cb("manifest_refresh")
        return self._config.manifest_refresh_interval

    async def run(self) -> None:
        """Continuously rescan the repo and update the manifest file."""
        # Perform an initial refresh immediately on startup so the
        # manifest is available before the first agent run.
        await self._do_refresh()

        while not self._stop_event.is_set():
            interval = self._get_interval()
            await self._sleep_fn(interval)
            if self._stop_event.is_set():
                break
            if not self._enabled_cb("manifest_refresh"):
                continue
            await self._do_refresh()

    async def _do_refresh(self) -> None:
        """Execute a single refresh cycle."""
        try:
            content, digest_hash = self._manifest_manager.refresh()
            self._state.update_manifest_state(digest_hash)
            last_run = datetime.now(UTC).isoformat()
            details = {"hash": digest_hash, "length": len(content)}
            self._status_cb("manifest_refresh", "ok", details)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data={
                        "worker": "manifest_refresh",
                        "status": "ok",
                        "last_run": last_run,
                        "details": details,
                    },
                )
            )
            logger.info(
                "Project manifest refreshed (hash=%s, %d chars)",
                digest_hash,
                len(content),
            )
        except (AuthenticationError, CreditExhaustedError):
            raise
        except Exception:
            logger.exception("Manifest refresh failed -- will retry next cycle")
            last_run = datetime.now(UTC).isoformat()
            self._status_cb("manifest_refresh", "error", None)
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.BACKGROUND_WORKER_STATUS,
                    data={
                        "worker": "manifest_refresh",
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
                        "message": "Manifest refresh loop error",
                        "source": "manifest_refresh",
                    },
                )
            )
