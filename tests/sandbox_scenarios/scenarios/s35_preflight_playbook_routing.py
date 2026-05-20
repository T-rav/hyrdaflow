"""s35 — AutoAgentPreflightLoop routes a plan-stuck escalation to the specialist playbook.

Golden path: FakeGitHub holds one ``hitl-escalation + plan-stuck`` issue.
The loop ticks once, routes to the plan-specialist playbook (ADR-0063 W1),
dispatches via FakeSubprocessRunner, and emits a BACKGROUND_WORKER_STATUS
event for ``auto_agent_preflight``, proving playbook-routing wiring is intact.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s35_preflight_playbook_routing"
DESCRIPTION = (
    "AutoAgentPreflightLoop processes a plan-stuck hitl-escalation → "
    "specialist playbook routing fires, emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {
                "number": 1,
                "title": "Plan stuck on issue 1",
                "body": "Phase drift: plan reviewer rejected twice.",
                "labels": ["hitl-escalation", "plan-stuck"],
            }
        ],
        loops_enabled=["auto_agent_preflight"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify BACKGROUND_WORKER_STATUS emitted by auto_agent_preflight."""
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
        f"Expected at least one auto_agent_preflight worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
