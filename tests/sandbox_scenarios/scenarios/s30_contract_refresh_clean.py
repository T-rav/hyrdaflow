"""s30 — ContractRefreshLoop runs with no contract drift and emits a worker-status event.

Golden path: the loop records no drift across adapters (github, git, docker,
claude) and opens no PR. It emits a BACKGROUND_WORKER_STATUS event for
``contract_refresh``, proving caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s30_contract_refresh_clean"
DESCRIPTION = (
    "ContractRefreshLoop sees no adapter drift → idle tick, emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["contract_refresh"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by contract_refresh."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "contract_refresh"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    cr_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "contract_refresh"
    ]
    assert len(cr_events) >= 1, (
        f"Expected at least one contract_refresh worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
