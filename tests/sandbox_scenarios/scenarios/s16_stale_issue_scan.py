"""s16 — StaleIssueLoop scans open issues and emits a worker-status event.

Golden path: with no stale issues in FakeGitHub (no issues seeded), the loop
runs one tick, reports scanned=0 / closed=0, and emits a BACKGROUND_WORKER_STATUS
event for ``stale_issue``. This proves the loop is wired into the caretaker
registry and fires without crashing under the air-gapped sandbox.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s16_stale_issue_scan"
DESCRIPTION = "StaleIssueLoop scans issues (empty repo) → emits worker-status event."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["stale_issue"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by stale_issue."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "stale_issue"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    stale_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "stale_issue"
    ]
    assert len(stale_events) >= 1, (
        f"Expected at least one stale_issue worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
