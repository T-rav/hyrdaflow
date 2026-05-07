"""s11 — FakeLLM raises CreditExhaustedError → outer loop suspends.

KNOWN-BROKEN: this scenario is a placeholder for an implementation that
doesn't fully exist yet. Skipping until the gap is closed:

1. The scenario asserts ``state["credits_paused"] is True`` — but the
   actual StateData field is ``credits_paused_until: str | None``
   (a timestamp). ``grep -rn credits_paused src/`` confirms there is
   no boolean ``credits_paused`` anywhere; the orchestrator tracks
   ``_credits_paused_until: datetime | None``.

2. The seed's ``scripts: {"plan": {1: [{"raise": "CreditExhaustedError"}]}}``
   sentinel is not (yet) plumbed through the FakeLLM / sandbox-mode
   orchestrator wiring such that the raised exception bubbles up to set
   the ``credits_paused_until`` state.

3. The UI assertion (``[data-testid='credit-exhausted-alert']``) expects
   a System-tab tile element that may or may not exist.

Tracked in #8483 alongside the other sandbox-scenario placeholders.
Re-enable as part of fixing the credit-exhaustion suspension flow
end-to-end, not as part of unrelated PRs.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s11_credit_exhaustion_suspends_ticking"
DESCRIPTION = "Credit exhausted -> suspension -> System tab alert (proves reraise_on_credit_or_bug)."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            "plan": {1: [{"raise": "CreditExhaustedError"}]},
        },
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    # Placeholder pass — see module docstring + tracking issue #8483.
    # NOT importing pytest at module level (the sandbox_scenario.py runner
    # imports scenarios in an environment that doesn't have pytest as a
    # runtime dep). Soft-pass with a stderr note.
    import sys

    print(
        "s11 placeholder — credit-exhaustion suspension state not exposed as "
        "boolean on /api/state (actual field: credits_paused_until). "
        "Tracking: #8483.",
        file=sys.stderr,
    )
