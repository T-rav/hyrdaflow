"""Clicking Start turns on the orchestrator; Stop turns it off."""

from __future__ import annotations

import asyncio

import pytest
from playwright.async_api import expect

pytestmark = pytest.mark.scenario_browser


async def test_start_button_starts_orchestrator(world, page):
    """Clicking the Start button flips the real orchestrator into running state."""
    world.add_issue(1, "Hello", "...", labels=["hydraflow-find"])
    url = await world.start_dashboard(with_orchestrator=True)

    # Before clicking Start the orchestrator is idle (not running).
    assert world._dashboard._orchestrator.running is False

    await page.goto(url)
    # Wait for WebSocket connection to be established.
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    await page.click('[data-testid="header-start-button"]')

    # The UI reflects the new status via the WS-pushed orchestrator_status event.
    await expect(page.locator('[data-testid="orchestrator-status"]')).to_contain_text(
        "running", timeout=10_000
    )

    # Python-side: the dashboard's orchestrator should now report running.
    # (world._dashboard._orchestrator is replaced by the new orch on start.)
    assert world._dashboard._orchestrator.running is True


async def test_stop_button_stops_orchestrator(world, page):
    """Clicking Stop transitions the orchestrator out of running state."""
    world.add_issue(1, "Hello", "...", labels=["hydraflow-find"])
    url = await world.start_dashboard(with_orchestrator=True)

    await page.goto(url)
    await page.wait_for_selector('body[data-connected="true"]', timeout=10_000)

    # Start the orchestrator via UI.
    await page.click('[data-testid="header-start-button"]')
    await expect(page.locator('[data-testid="orchestrator-status"]')).to_contain_text(
        "running", timeout=10_000
    )

    # Stop via UI.
    await page.click('[data-testid="header-stop-button"]')
    await expect(
        page.locator('[data-testid="orchestrator-status"]')
    ).not_to_contain_text("running", timeout=10_000)

    # Give the orchestrator task a moment to fully wind down, then check Python-side.
    orch = world._dashboard._orchestrator
    for _ in range(20):
        if not orch.running:
            break
        await asyncio.sleep(0.25)
    assert orch.running is False
