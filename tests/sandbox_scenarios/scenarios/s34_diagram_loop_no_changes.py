"""s34 — DiagramLoop runs with no module changes and emits a worker-status event.

Golden path: the loop checks for module-graph changes since the last
architecture regen, finds none, and emits a BACKGROUND_WORKER_STATUS event
for ``diagram-loop``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s34_diagram_loop_no_changes"
DESCRIPTION = (
    "DiagramLoop finds no module changes since last regen → idle tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["diagram_loop"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by diagram-loop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "diagram-loop"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    dl_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "diagram-loop"
    ]
    assert len(dl_events) >= 1, (
        f"Expected at least one diagram-loop worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
