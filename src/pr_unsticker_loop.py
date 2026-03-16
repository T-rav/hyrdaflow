"""Background worker loop — goal-driven PR unsticker for all HITL causes."""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from pr_manager import PRManager
from pr_unsticker import PRUnsticker

logger = logging.getLogger("hydraflow.pr_unsticker_loop")


class PRUnstickerLoop(BaseBackgroundLoop):
    """Polls HITL items and resolves all HITL causes (conflicts, CI, generic)."""

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_unsticker: PRUnsticker,
        prs: PRManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(worker_name="pr_unsticker", config=config, deps=deps)
        self._pr_unsticker = pr_unsticker
        self._prs = prs

    def _get_default_interval(self) -> int:
        return self._config.pr_unstick_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Resolve all HITL causes (conflicts, CI failures, generic)."""
        hitl_items = await self._prs.list_hitl_items(self._config.hitl_label)
        # Only process HITL issues that currently have an open PR.
        active_pr_items = [item for item in hitl_items if int(item.pr or 0) > 0]
        stats = await self._pr_unsticker.unstick(active_pr_items)
        return dict(stats)
