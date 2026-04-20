"""Contract snapshots for the populated dashboard — ports JS screenshots.spec.js."""

from __future__ import annotations

import pytest

from tests.scenarios.browser.contract.seeds import seed_populated_pipeline
from tests.scenarios.browser.pages.base import BasePage
from tests.scenarios.browser.pages.system import SystemPage
from tests.scenarios.browser.pages.work_stream import WorkStreamPage

pytestmark = pytest.mark.scenario_browser


async def _setup(world):
    world._clock.freeze("2025-06-15T12:00:00Z")
    seed_populated_pipeline(world)
    return await world.start_dashboard()


async def test_populated_issues(world, page, assert_screenshot):
    url = await _setup(world)
    await WorkStreamPage(page, url).open()
    await assert_screenshot(page, "populated-issues.png", max_diff_pixels=60)


async def test_populated_outcomes(world, page, assert_screenshot):
    url = await _setup(world)
    await BasePage(page, url).goto("/?tab=outcomes")
    await assert_screenshot(page, "populated-outcomes.png", max_diff_pixels=60)


async def test_populated_hitl(world, page, assert_screenshot):
    url = await _setup(world)
    await BasePage(page, url).goto("/?tab=hitl")
    await assert_screenshot(page, "populated-hitl.png", max_diff_pixels=60)


async def test_populated_worklog(world, page, assert_screenshot):
    url = await _setup(world)
    await BasePage(page, url).goto("/?tab=worklog")
    await assert_screenshot(page, "populated-worklog.png", max_diff_pixels=60)


async def test_populated_system(world, page, assert_screenshot):
    url = await _setup(world)
    await SystemPage(page, url).open("workers")
    await assert_screenshot(page, "populated-system.png", max_diff_pixels=60)


@pytest.mark.parametrize(
    "sub,name",
    [
        ("workers", "populated-system-workers"),
        ("pipeline", "populated-system-pipeline"),
        ("metrics", "populated-system-metrics"),
        ("insights", "populated-system-insights"),
        ("livestream", "populated-system-livestream"),
    ],
)
async def test_populated_system_subtab(world, page, assert_screenshot, sub, name):
    url = await _setup(world)
    await SystemPage(page, url).open(sub)
    await assert_screenshot(page, f"{name}.png", max_diff_pixels=60)
