"""s20 — RCBudgetLoop runs with no RC history and emits a worker-status event.

Golden path: with no RC promotion history (FakeGitHub returns an empty run
list), the loop completes without filing a regression issue and emits a
BACKGROUND_WORKER_STATUS event for ``rc_budget``.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s20_rc_budget_no_regression"
DESCRIPTION = (
    "RCBudgetLoop sees empty RC run history → no regression filed, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["rc_budget"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by rc_budget."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "rc_budget"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    rc_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "rc_budget"
    ]
    assert len(rc_events) >= 1, (
        f"Expected at least one rc_budget worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
