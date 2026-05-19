"""s26 — CostBudgetWatcherLoop runs in unlimited mode and emits a worker-status event.

Golden path: ``daily_cost_budget_usd`` is None (unlimited mode), so the loop
takes no action and emits a BACKGROUND_WORKER_STATUS event for
``cost_budget_watcher``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s26_cost_budget_watcher_unlimited"
DESCRIPTION = (
    "CostBudgetWatcherLoop in unlimited mode (no cap) → no-op tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["cost_budget_watcher"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by cost_budget_watcher."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "cost_budget_watcher"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    cbw_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "cost_budget_watcher"
    ]
    assert len(cbw_events) >= 1, (
        f"Expected at least one cost_budget_watcher worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
