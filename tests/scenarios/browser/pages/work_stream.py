"""Work Stream tab — pipeline rows grouped by phase."""

from __future__ import annotations

from .base import BasePage


class WorkStreamPage(BasePage):
    async def open(self) -> None:
        await self.goto("/?tab=issues")
