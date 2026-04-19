"""Fixtures for browser scenario tests.

All fixtures are function-scoped so every test gets its own asyncio event
loop, its own browser context, and its own MockWorld instance.  This avoids
cross-scope event-loop conflicts in pytest-asyncio (the session-scoped async
fixture + function-scoped test combination can deadlock when the two run on
different loops).

The root conftest sets HOME=/tmp/hydraflow-test for hermeticity, which breaks
Playwright's browser-path resolution.  We capture the real Playwright cache
path at import time (before setup_test_environment runs) and export it as
PLAYWRIGHT_BROWSERS_PATH when starting the driver.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_browser

# Captured at import time, before HOME is overridden.
_REAL_PLAYWRIGHT_BROWSERS_PATH: str = str(
    Path.home() / "Library" / "Caches" / "ms-playwright"
)


@pytest.fixture
async def browser_context():
    """Fresh Playwright browser + context per test."""
    old = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _REAL_PLAYWRIGHT_BROWSERS_PATH
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="dark",
                locale="en-US",
                timezone_id="UTC",
                device_scale_factor=1,
            )
            try:
                yield ctx
            finally:
                await ctx.close()
            await browser.close()
    finally:
        if old is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old


@pytest.fixture
async def page(browser_context):
    p = await browser_context.new_page()
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
async def world(tmp_path):
    w = MockWorld(tmp_path)
    try:
        yield w
    finally:
        stop = getattr(w, "stop_dashboard", None)
        if stop is not None:
            await stop()
