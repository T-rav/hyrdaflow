"""Fixtures for browser scenario tests.

All fixtures are **function-scoped** so every test gets its own asyncio event
loop, its own Chromium instance, its own browser context, and its own
``MockWorld`` instance.

Why session-scoped browser fixtures are not used
------------------------------------------------
Session-scoped async Playwright fixtures (``_playwright`` / ``browser``) share
a *session* event loop, while async test functions run on a *function*-scoped
loop by default (``asyncio_default_test_loop_scope = "function"`` in
pytest-asyncio ≤ 1.3.0 when ``asyncio_mode = "auto"``).  Using a session-
loop Playwright object from a function-loop test causes a cross-loop deadlock:
the Playwright ``Future`` is attached to the session loop but the test awaits
it from the function loop.

The clean fix requires setting *both*
``asyncio_default_fixture_loop_scope = "session"`` and
``asyncio_default_test_loop_scope = "session"`` in pyproject.toml.  That
changes the event-loop scope for the **entire** test suite, which is a
high-risk global change for a codebase with hundreds of async unit tests that
rely on function-scope loop isolation.

Until the test suite is audited for session-loop compatibility, we keep
function-scoped browser fixtures.  Each of the 15 Tier-3 contract tests
launches its own Chromium process (~5–8 s overhead per test).  If total
browser-suite wall-time becomes a bottleneck, revisit this after running the
full unit suite under ``asyncio_default_test_loop_scope = "session"`` and
confirming zero regressions.

See: https://pytest-asyncio.readthedocs.io/en/latest/reference/fixtures.html

The root conftest sets HOME=/tmp/hydraflow-test for hermeticity, which breaks
Playwright's browser-path resolution.  We capture the real Playwright cache
path at import time (before setup_test_environment runs) and export it as
PLAYWRIGHT_BROWSERS_PATH when starting the driver.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_browser


def _platform_playwright_browsers_path() -> Path:
    """Return Playwright's platform-default browsers cache path.

    macOS: ``~/Library/Caches/ms-playwright``
    Linux: ``~/.cache/ms-playwright``
    Windows: ``%LOCALAPPDATA%\\ms-playwright``

    A pre-set ``PLAYWRIGHT_BROWSERS_PATH`` env var wins over the default,
    matching Playwright's own discovery rules.
    """
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if explicit:
        return Path(explicit)
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "ms-playwright"
        return home / "AppData" / "Local" / "ms-playwright"
    return home / ".cache" / "ms-playwright"


# Captured at import time, before HOME is overridden by the root conftest.
_REAL_PLAYWRIGHT_BROWSERS_PATH: str = str(_platform_playwright_browsers_path())


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
