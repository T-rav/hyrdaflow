"""Contract snapshots for the idle/empty dashboard."""

from __future__ import annotations

import pytest

from tests.scenarios.browser.contract.seeds import seed_empty_pipeline
from tests.scenarios.browser.pages.base import BasePage

pytestmark = pytest.mark.scenario_browser


async def _setup(world):
    world._clock.freeze("2025-06-15T12:00:00Z")
    seed_empty_pipeline(world)
    return await world.start_dashboard()


@pytest.mark.parametrize(
    "tab,name",
    [
        ("issues", "empty-issues"),
        ("outcomes", "empty-outcomes"),
        ("hitl", "empty-hitl"),
        ("worklog", "empty-worklog"),
        ("system", "empty-system"),
    ],
)
async def test_empty_tab(world, page, assert_screenshot, tab, name):
    url = await _setup(world)
    await BasePage(page, url).goto(f"/?tab={tab}")
    await assert_screenshot(page, f"{name}.png", max_diff_pixels=60)
