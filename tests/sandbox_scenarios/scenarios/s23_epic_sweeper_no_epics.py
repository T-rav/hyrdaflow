"""s23 — EpicSweeperLoop scans open epics (empty) and emits a worker-status event.

Golden path: with no open epics in FakeGitHub, the loop runs one tick,
sweeps nothing, and emits a BACKGROUND_WORKER_STATUS event for
``epic_sweeper``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s23_epic_sweeper_no_epics"
DESCRIPTION = (
    "EpicSweeperLoop sees no open epics → sweeps nothing, emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["epic_sweeper"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by epic_sweeper."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "epic_sweeper"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    sweep_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "epic_sweeper"
    ]
    assert len(sweep_events) >= 1, (
        f"Expected at least one epic_sweeper worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
