"""s10 — disable EVERY loop via static config; no loop ticks for 5 cycles."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s10_kill_switch_universal"
DESCRIPTION = "All loops disabled via static config -> no ticks (proves ADR-0049)."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        # Empty loops_enabled list = disable all.
        loops_enabled=[],
        cycles_to_run=5,
    )


async def assert_outcome(api, page) -> None:
    state = await api.get("/api/state")
    # Every loop's tick_count should be 0 (or unchanged from boot).
    for name, info in state["worker_health"].items():
        assert info["tick_count"] == 0, (
            f"loop {name} ticked {info['tick_count']} times despite static-disable"
        )
