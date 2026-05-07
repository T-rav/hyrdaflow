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
    # When every loop is statically disabled (loops_enabled=[]), no loop's
    # _execute_cycle runs, so no BACKGROUND_WORKER_STATUS event publishes,
    # so neither bg_worker_states nor worker_heartbeats gets populated.
    # Original test referenced a state["worker_health"]["...]["tick_count"]
    # shape that has never existed in src/models.py StateData — fixed here
    # to assert against the real state fields.
    bg_states = state.get("bg_worker_states") or {}
    heartbeats = state.get("worker_heartbeats") or {}
    assert not bg_states and not heartbeats, (
        f"loops should not have ticked under universal kill-switch: "
        f"bg_worker_states={list(bg_states.keys())}, "
        f"worker_heartbeats={list(heartbeats.keys())}"
    )
