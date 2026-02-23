"""Background worker loop — PR unsticker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from pr_manager import PRManager
from pr_unsticker import PRUnsticker
from subprocess_util import AuthenticationError, CreditExhaustedError

logger = logging.getLogger("hydraflow.pr_unsticker_loop")


class PRUnstickerLoop:
    """Polls HITL items and resolves merge-conflict PRs."""

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_unsticker: PRUnsticker,
        prs: PRManager,
        bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: Callable[[str, str, dict[str, Any] | None], None],
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
    ) -> None:
        self._config = config
        self._pr_unsticker = pr_unsticker
        self._prs = prs
        self._bus = bus
        self._stop_event = stop_event
        self._status_cb = status_cb
        self._enabled_cb = enabled_cb
        self._sleep_fn = sleep_fn

    async def run(self) -> None:
        """Continuously poll HITL items and resolve merge-conflict PRs."""
        while not self._stop_event.is_set():
            if not self._enabled_cb("pr_unsticker"):
                await self._sleep_fn(self._config.pr_unstick_interval)
                continue
            try:
                hitl_items = await self._prs.list_hitl_items(self._config.hitl_label)
                stats = await self._pr_unsticker.unstick(hitl_items)
                last_run = datetime.now(UTC).isoformat()
                self._status_cb("pr_unsticker", "ok", stats)
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BACKGROUND_WORKER_STATUS,
                        data={
                            "worker": "pr_unsticker",
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
                    "PR unsticker loop iteration failed — will retry next cycle"
                )
                last_run = datetime.now(UTC).isoformat()
                self._status_cb("pr_unsticker", "error", None)
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.BACKGROUND_WORKER_STATUS,
                        data={
                            "worker": "pr_unsticker",
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
                            "message": "PR unsticker loop error",
                            "source": "pr_unsticker",
                        },
                    )
                )
            await self._sleep_fn(self._config.pr_unstick_interval)
