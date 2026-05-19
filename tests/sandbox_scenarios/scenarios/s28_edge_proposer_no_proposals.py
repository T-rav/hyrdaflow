"""s28 — EdgeProposerLoop runs with no pending edge proposals and emits a worker-status event.

Golden path: the loop finds no missing wiki edges and opens no bot PR.
It emits a BACKGROUND_WORKER_STATUS event for ``edge_proposer``, proving
caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s28_edge_proposer_no_proposals"
DESCRIPTION = (
    "EdgeProposerLoop finds no missing wiki edges → idle tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["edge_proposer"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by edge_proposer."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "edge_proposer"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    ep_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "edge_proposer"
    ]
    assert len(ep_events) >= 1, (
        f"Expected at least one edge_proposer worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
