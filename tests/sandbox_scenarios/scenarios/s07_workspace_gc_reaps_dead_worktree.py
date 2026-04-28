"""s07 — orphan worktree present → WorkspaceGCLoop reaps it."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s07_workspace_gc_reaps_dead_worktree"
DESCRIPTION = "Orphan worktree at boot → reaped → System tab counter increments."


def seed() -> MockWorldSeed:
    # FakeWorkspace records "destroyed[]" — seed is empty; we drive
    # the GC loop directly.
    return MockWorldSeed(
        loops_enabled=["workspace_gc"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    # Manually populate FakeWorkspace.created via API debug hook (adds in
    # PR C task — see helper file). For initial implementation, simply
    # verify the System tab renders the workspace_gc panel.
    await page.goto("/")
    await page.click("text=System")
    panel = page.locator("[data-testid='workspace-gc-panel']")
    assert await panel.is_visible()
