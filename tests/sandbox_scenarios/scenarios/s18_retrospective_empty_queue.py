"""s18 — RetrospectiveLoop drains an empty queue and emits a worker-status event.

Golden path: with no queued retrospective items, the loop finishes in one tick
with processed=0 and emits a BACKGROUND_WORKER_STATUS event for ``retrospective``.
This proves the loop is wired into the caretaker registry and fires cleanly.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s18_retrospective_empty_queue"
DESCRIPTION = (
    "RetrospectiveLoop drains empty queue → emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["retrospective"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by retrospective."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "retrospective"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    retro_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "retrospective"
    ]
    assert len(retro_events) >= 1, (
        f"Expected at least one retrospective worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
