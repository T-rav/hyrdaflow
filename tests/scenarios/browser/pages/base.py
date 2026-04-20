"""Shared helpers for page objects."""

from __future__ import annotations

from playwright.async_api import Page

_DISABLE_ANIMATIONS_CSS = """
  *, *::before, *::after {
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    transition-duration: 0s !important;
    transition-delay: 0s !important;
    caret-color: transparent !important;
  }
"""


class BasePage:
    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    async def goto(self, path: str = "/") -> None:
        await self.page.goto(self.base_url + path)
        await self.page.add_style_tag(content=_DISABLE_ANIMATIONS_CSS)
        await self.wait_for_ws_ready()

    async def wait_for_ws_ready(self, timeout: float = 10_000) -> None:
        """Block until the React app reports ``connected=true``.

        Task 13 adds a ``data-connected`` attribute on ``body`` that flips
        to ``"true"`` once the WS handshake completes. Tests must wait for
        this before asserting, or they race against the initial state push.
        """
        await self.page.wait_for_selector(
            'body[data-connected="true"]', timeout=timeout
        )
