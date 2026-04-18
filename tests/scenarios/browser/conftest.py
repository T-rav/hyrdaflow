"""Fixtures for browser scenario tests.

Session-scoped browser (reused across tests). Function-scoped MockWorld
and dashboard lifecycle, each test gets its own tmp_path and OS-allocated
port (pytest-xdist safe).
"""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_browser


@pytest.fixture(scope="session")
async def _playwright():
    async with async_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
async def browser(_playwright):
    browser = await _playwright.chromium.launch()
    try:
        yield browser
    finally:
        await browser.close()


@pytest.fixture
async def browser_context(browser):
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
