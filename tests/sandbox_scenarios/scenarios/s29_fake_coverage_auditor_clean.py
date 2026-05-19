"""s29 — FakeCoverageAuditorLoop runs with a clean repo state and emits a worker-status event.

Golden path: the loop finds no coverage gaps (empty last-known catalog,
clean diff) and emits a BACKGROUND_WORKER_STATUS event for
``fake_coverage_auditor``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s29_fake_coverage_auditor_clean"
DESCRIPTION = (
    "FakeCoverageAuditorLoop sees no coverage gaps → idle tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["fake_coverage_auditor"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by fake_coverage_auditor."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "fake_coverage_auditor"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    fca_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "fake_coverage_auditor"
    ]
    assert len(fca_events) >= 1, (
        f"Expected at least one fake_coverage_auditor worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
