"""s31 — AutoAgentPreflightLoop runs with an empty escalation queue and emits a worker-status event.

Golden path: the loop finds no issues awaiting HITL preflight and emits a
BACKGROUND_WORKER_STATUS event for ``auto_agent_preflight``, proving
caretaker-registry wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s31_auto_agent_preflight_no_escalations"
DESCRIPTION = (
    "AutoAgentPreflightLoop sees empty escalation queue → idle tick, "
    "emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["auto_agent_preflight"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by auto_agent_preflight."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "auto_agent_preflight"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    aap_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "auto_agent_preflight"
    ]
    assert len(aap_events) >= 1, (
        f"Expected at least one auto_agent_preflight worker-status event; got none. "
        f"All events: {events_payload!r}"
    )
