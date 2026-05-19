"""s32 — DiagnosticLoop runs with no recent failures and emits a worker-status event.

Golden path: the loop scans recent CI runs, finds no failures requiring
diagnosis, and emits a BACKGROUND_WORKER_STATUS event for ``diagnostic``,
proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s32_diagnostic_no_failures"
DESCRIPTION = (
    "DiagnosticLoop sees no recent CI failures → idle tick, emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["diagnostic"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by diagnostic."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "diagnostic"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    diag_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "diagnostic"
    ]
    assert len(diag_events) >= 1, (
        f"Expected at least one diagnostic worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
