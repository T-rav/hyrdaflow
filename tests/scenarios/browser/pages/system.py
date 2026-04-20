"""System tab — workers, pipeline config, metrics, insights, livestream subtabs."""

from __future__ import annotations

from .base import BasePage


class SystemPage(BasePage):
    async def open(self, sub: str = "workers") -> None:
        await self.goto(f"/?tab=system&sub={sub}")
