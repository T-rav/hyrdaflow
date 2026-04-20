"""Outcomes tab — merged PRs and done issues."""

from __future__ import annotations

from .base import BasePage


class OutcomesPage(BasePage):
    async def open(self) -> None:
        await self.goto("/?tab=outcomes")
