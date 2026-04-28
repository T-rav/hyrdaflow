"""Playwright + SandboxAPIClient fixtures for the sandbox runner.

These fixtures are scoped to the 'sandbox' test directory only — they
don't pollute the broader pytest collection.
"""

from __future__ import annotations

import os

import pytest_asyncio
from playwright.async_api import async_playwright

from tests.sandbox_scenarios.runner.api_client import SandboxAPIClient


@pytest_asyncio.fixture
async def api():
    """Async API client targeting the in-container hydraflow dashboard."""
    yield SandboxAPIClient()


@pytest_asyncio.fixture
async def browser():
    """Headless Chromium for the sandbox network."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture
async def page(browser):
    """A fresh page targeting SANDBOX_BASE_URL (the UI service)."""
    base_url = os.environ.get("SANDBOX_BASE_URL", "http://ui")
    context = await browser.new_context(base_url=base_url)
    page = await context.new_page()
    yield page
    await context.close()
