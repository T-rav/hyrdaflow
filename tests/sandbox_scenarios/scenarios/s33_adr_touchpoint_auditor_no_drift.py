"""s33 — AdrTouchpointAuditorLoop runs with no ADR drift and emits a worker-status event.

Golden path: the loop scans recent merged PRs, finds no ADR touchpoint
violations, and emits a BACKGROUND_WORKER_STATUS event for
``adr_touchpoint_auditor``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s33_adr_touchpoint_auditor_no_drift"
DESCRIPTION = (
    "AdrTouchpointAuditorLoop finds no ADR drift in recent PRs → idle tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["adr_touchpoint_auditor"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by adr_touchpoint_auditor."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "adr_touchpoint_auditor"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    ata_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "adr_touchpoint_auditor"
    ]
    assert len(ata_events) >= 1, (
        f"Expected at least one adr_touchpoint_auditor worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
