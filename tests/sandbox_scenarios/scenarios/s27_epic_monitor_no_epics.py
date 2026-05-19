"""s27 — EpicMonitorLoop runs with no open epics and emits a worker-status event.

Golden path: the epic_manager delegate returns an empty result and the loop
emits a BACKGROUND_WORKER_STATUS event for ``epic_monitor``, proving
caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s27_epic_monitor_no_epics"
DESCRIPTION = (
    "EpicMonitorLoop sees no open epics → idle tick, emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["epic_monitor"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by epic_monitor."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "epic_monitor"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    em_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "epic_monitor"
    ]
    assert len(em_events) >= 1, (
        f"Expected at least one epic_monitor worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
