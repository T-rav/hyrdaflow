"""Background worker loop — ADR council review for proposed ADRs."""

from __future__ import annotations

import logging
from typing import Any

from adr_reviewer import ADRCouncilReviewer
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.adr_reviewer_loop")


class ADRReviewerLoop(BaseBackgroundLoop):
    """Polls for proposed ADRs and runs council reviews."""

    def __init__(
        self,
        config: HydraFlowConfig,
        adr_reviewer: ADRCouncilReviewer,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="adr_reviewer", config=config, deps=deps)
        self._adr_reviewer = adr_reviewer

    def _get_default_interval(self) -> int:
        return self._config.adr_review_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Review proposed ADRs via the council process."""
        if not self._config.adr_review_enabled:
            return None
        return await self._adr_reviewer.review_proposed_adrs()
