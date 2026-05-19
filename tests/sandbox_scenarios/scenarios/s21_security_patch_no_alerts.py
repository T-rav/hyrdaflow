"""s21 — SecurityPatchLoop runs with no Dependabot alerts and emits a worker-status event.

Golden path: FakeGitHub returns an empty Dependabot alert list, so the loop
files zero issues and emits a BACKGROUND_WORKER_STATUS event for
``security_patch``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s21_security_patch_no_alerts"
DESCRIPTION = (
    "SecurityPatchLoop sees no Dependabot alerts → files nothing, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["security_patch"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by security_patch."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "security_patch"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    sec_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "security_patch"
    ]
    assert len(sec_events) >= 1, (
        f"Expected at least one security_patch worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
