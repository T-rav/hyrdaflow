"""Background worker loop — ADR council review for proposed ADRs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from adr_reviewer import ADRCouncilReviewer
from base_background_loop import BaseBackgroundLoop
from config import HydraFlowConfig
from events import EventBus
from models import StatusCallback

logger = logging.getLogger("hydraflow.adr_reviewer_loop")


class ADRReviewerLoop(BaseBackgroundLoop):
    """Polls for proposed ADRs and runs council reviews."""

    def __init__(
        self,
        config: HydraFlowConfig,
        adr_reviewer: ADRCouncilReviewer,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        status_cb: StatusCallback,
        enabled_cb: Callable[[str], bool],
        sleep_fn: Callable[[int | float], Coroutine[Any, Any, None]],
        interval_cb: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(
            worker_name="adr_reviewer",
            config=config,
            bus=event_bus,
            stop_event=stop_event,
            status_cb=status_cb,
            enabled_cb=enabled_cb,
            sleep_fn=sleep_fn,
            interval_cb=interval_cb,
        )
        self._adr_reviewer = adr_reviewer

    def _get_default_interval(self) -> int:
        return self._config.adr_review_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Review proposed ADRs via the council process."""
        if not self._config.adr_review_enabled:
            return None
        return await self._adr_reviewer.review_proposed_adrs()
