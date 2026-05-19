"""s19 — ReportIssueLoop drains an empty report queue and emits a worker-status event.

Golden path: with no pending bug reports, the loop returns None (no work)
but must still emit a BACKGROUND_WORKER_STATUS event for ``report_issue``,
proving the loop is wired into the caretaker registry.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s19_report_issue_empty_queue"
DESCRIPTION = "ReportIssueLoop sees empty queue → emits worker-status event."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["report_issue"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by report_issue."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "report_issue"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    report_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "report_issue"
    ]
    assert len(report_events) >= 1, (
        f"Expected at least one report_issue worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
