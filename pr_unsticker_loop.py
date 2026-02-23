"""Background worker loop — PR unsticker."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager
from pr_unsticker import PRUnsticker

logger = logging.getLogger("hydraflow.pr_unsticker_loop")


class PRUnstickerLoop(BaseBackgroundLoop):
    """Polls HITL items and resolves merge-conflict PRs."""

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_unsticker: PRUnsticker,
        prs: PRManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: Callable[[str, str, dict[str, Any] | None], None],
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(
            worker_name="pr_unsticker",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
        )
        self._pr_unsticker = pr_unsticker
        self._prs = prs

    def _get_default_interval(self) -> int:
        return self._config.pr_unstick_interval

    async def _do_work(self) -> dict[str, Any] | None:
        hitl_items = await self._prs.list_hitl_items(self._config.hitl_label)
        stats = await self._pr_unsticker.unstick(hitl_items)
        return dict(stats)
