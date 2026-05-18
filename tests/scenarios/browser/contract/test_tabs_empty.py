"""Smoke contract: each dashboard tab loads cleanly with an empty pipeline.

Pixel-baseline screenshot comparison was removed — every UI tweak broke it
and the failure modes (138K-pixel diffs) were uninformative.  These tests
now verify the load contract that actually matters: the tab navigates,
the WebSocket reaches ``connected=true``, and no React error boundary
mounts.  Semantic regressions on individual widgets are covered by the
happy/sad scenario tests under ``tests/scenarios/browser/scenarios/``.
"""

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
    "tab",
    ["issues", "outcomes", "hitl", "worklog", "system"],
)
async def test_empty_tab_loads(world, page, tab):
    url = await _setup(world)
    await BasePage(page, url).goto(f"/?tab={tab}")
    # ``goto`` already waited for body[data-connected="true"].
    # Wait for network to settle so any deferred fetch surfaces an overlay.
    await page.wait_for_load_state("networkidle")
    # React error boundary mounts ``[data-error-boundary]`` if a render
    # threw; absence is the load contract.
    assert await page.locator("[data-error-boundary]").count() == 0, (
        f"tab '{tab}' rendered an error boundary"
    )
    # URL faithfully reflects the requested tab so deep-links still work.
    assert f"tab={tab}" in page.url
