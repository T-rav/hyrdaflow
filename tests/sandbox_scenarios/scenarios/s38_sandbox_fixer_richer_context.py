"""s38 — SandboxFailureFixerLoop ticks with a sandbox-fail-auto-fix PR and emits a worker-status event.

Golden path (ADR-0063 W3c): FakeGitHub holds one PR labeled
``sandbox-fail-auto-fix``. The loop ticks once (config gate returns
``config_disabled`` since ``sandbox_failure_fixer_enabled`` defaults off),
and emits a BACKGROUND_WORKER_STATUS event for ``sandbox_failure_fixer``,
proving caretaker-registry wiring is intact. The richer-context injection
path (commit diffs + CI failure log, W3c) is exercised on live fix attempts;
this scenario proves the loop is registered and ticks without crashing.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s38_sandbox_fixer_richer_context"
DESCRIPTION = (
    "SandboxFailureFixerLoop sees a sandbox-fail-auto-fix PR → idle tick "
    "(config_disabled), emits worker-status event."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        prs=[
            {
                "number": 101,
                "issue_number": 0,
                "branch": "hf/issue-99",
                "ci_status": "fail",
                "merged": False,
                "labels": ["sandbox-fail-auto-fix"],
            }
        ],
        loops_enabled=["sandbox_failure_fixer"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify BACKGROUND_WORKER_STATUS emitted by sandbox_failure_fixer."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "sandbox_failure_fixer"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    sfx_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "sandbox_failure_fixer"
    ]
    assert len(sfx_events) >= 1, (
        f"Expected at least one sandbox_failure_fixer worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
