"""s06 — operator toggles loop off via System tab; loop stops ticking."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s06_kill_switch_via_ui"
DESCRIPTION = (
    "Toggle loop off in System tab → ADR-0049 in-body gate fires; no further ticks."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(cycles_to_run=4)


async def assert_outcome(api, page) -> None:
    # Capture baseline tick count for triage_loop.
    state_before = await api.get("/api/state")
    triage_ticks_before = state_before["worker_health"]["triage_loop"]["tick_count"]

    # Toggle off via UI System tab.
    await page.goto("/")
    await page.click("text=System")
    toggle = page.locator("[data-testid='toggle-triage_loop']")
    await toggle.click()

    # Wait one tick interval, then re-check: count should not have advanced.
    import asyncio

    await asyncio.sleep(5)

    state_after = await api.get("/api/state")
    triage_ticks_after = state_after["worker_health"]["triage_loop"]["tick_count"]
    assert triage_ticks_after == triage_ticks_before, (
        f"triage_loop kept ticking after disable: {triage_ticks_before} → {triage_ticks_after}"
    )
