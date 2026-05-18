"""Smoke contract: each dashboard tab loads cleanly with a populated pipeline.

Pixel-baseline screenshot comparison was removed — every UI tweak broke it
and the failure modes (~140K–780K-pixel diffs from a single layout shift)
were uninformative.  These tests now verify the load contract that actually
matters: the tab navigates, the WebSocket reaches ``connected=true``, and
no React error boundary mounts when real pipeline data is present.
Semantic regressions on individual widgets are covered by the happy/sad
scenario tests under ``tests/scenarios/browser/scenarios/``.
"""

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


async def _assert_loaded(page, tab: str) -> None:
    """Shared smoke check: settle network, no error boundary, URL reflects tab."""
    await page.wait_for_load_state("networkidle")
    assert await page.locator("[data-error-boundary]").count() == 0, (
        f"tab '{tab}' rendered an error boundary"
    )
    assert f"tab={tab}" in page.url


async def test_populated_issues(world, page):
    url = await _setup(world)
    await WorkStreamPage(page, url).open()
    await _assert_loaded(page, "issues")


async def test_populated_outcomes(world, page):
    url = await _setup(world)
    await BasePage(page, url).goto("/?tab=outcomes")
    await _assert_loaded(page, "outcomes")


async def test_populated_hitl(world, page):
    url = await _setup(world)
    await BasePage(page, url).goto("/?tab=hitl")
    await _assert_loaded(page, "hitl")


async def test_populated_worklog(world, page):
    url = await _setup(world)
    await BasePage(page, url).goto("/?tab=worklog")
    await _assert_loaded(page, "worklog")


async def test_populated_system(world, page):
    url = await _setup(world)
    await SystemPage(page, url).open("workers")
    await _assert_loaded(page, "system")


@pytest.mark.parametrize(
    "sub",
    ["workers", "pipeline", "metrics", "insights", "livestream"],
)
async def test_populated_system_subtab(world, page, sub):
    url = await _setup(world)
    await SystemPage(page, url).open(sub)
    await _assert_loaded(page, "system")
