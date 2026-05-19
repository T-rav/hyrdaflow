"""s24 — EntryEvidenceLoop runs with no UL terms and emits a worker-status event.

Golden path: with no term files on disk, the loop skips LLM matching,
opens no bot PR, and emits a BACKGROUND_WORKER_STATUS event for
``entry_evidence``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s24_entry_evidence_no_terms"
DESCRIPTION = (
    "EntryEvidenceLoop finds no UL terms → idle tick, emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["entry_evidence"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by entry_evidence."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "entry_evidence"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    ee_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "entry_evidence"
    ]
    assert len(ee_events) >= 1, (
        f"Expected at least one entry_evidence worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
