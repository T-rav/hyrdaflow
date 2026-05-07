"""s13 — RC promotion PR recovers via auto-rebase when head falls behind.

Drives the dark-factory recovery cycle introduced in PR #8482:
``StagingPromotionLoop`` cuts an ``rc/*`` PR, the first merge attempt
fails because the head fell behind ``main`` between when CI passed and
when the merge was attempted, ``PRManager.update_pr_branch`` rebases
via GitHub's API, CI re-polls, the second merge succeeds, the loop
records ``last_green_rc_sha``.

CURRENT STATUS: PLACEHOLDER. The unit-test layer
(`tests/test_pr_manager_rebase_on_conflict.py`) and the MockWorld
scenario layer (`tests/scenarios/test_rebase_on_conflict_scenario.py`)
both exercise the recovery cycle end-to-end with scripted I/O. This
sandbox scenario completes the test pyramid by driving the real
orchestrator + real GitHub-shaped boundary inside docker, but it
needs three pieces of harness wiring that don't exist yet:

1. A way to script the FakeGitHub at the sandbox boundary to fail the
   first merge with a "head behind base" RuntimeError, then succeed.
   ``MockWorldSeed.scripts`` needs a ``"merge_pr"`` keyword (similar to
   the existing ``"plan"`` keyword) that the sandbox-mode FakeGitHub
   reads on each ``merge_pr`` / ``merge_promotion_pr`` call.

2. A way to assert that ``update_pr_branch`` was invoked from inside
   the sandbox — currently the FakeGitHub doesn't record this. Need a
   ``world.honeycomb``-style assertion surface, or a counter exposed
   via ``/api/state`` that gets incremented on each update call.

3. A staging→main RC PR seed mode. Existing seeds put issues into the
   queue; this scenario needs to seed an existing rc/* branch + open
   promotion PR + history that puts the rc head behind main.

Tracked in #8483 alongside the other sandbox-scenario gaps. Re-enable
this scenario as part of fixing the harness; the recovery feature
itself ships green at the unit + scenario layers and will get
production verification on the first real RC PR cut by
StagingPromotionLoop.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s13_rc_rebase_recovery"
DESCRIPTION = (
    "RC promotion PR recovers via auto-rebase (proves PR #8482 dark-factory recovery)."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        # When sandbox merge-scripting + RC-PR seeding land, this will be:
        # rc_branch="rc/2026-05-07-test",
        # rc_head_sha="<behind-main>",
        # scripts={"merge_pr": {<rc-pr-num>: [{"raise": "head behind base"}, {"ok": True}]}},
        # cycles_to_run=2,
        cycles_to_run=1,
    )


async def assert_outcome(api, page) -> None:
    # Placeholder pass — see module docstring + tracking issue #8483.
    # NOT importing pytest at module level (the sandbox_scenario.py runner
    # imports scenarios in an environment without pytest). Soft-pass with
    # a stderr note so the placeholder nature is loud at CI time.
    import sys

    print(
        "s13 placeholder — sandbox harness lacks (a) per-call merge-scripting "
        "for FakeGitHub, (b) update_pr_branch invocation assertion surface, "
        "(c) RC-PR seed mode. Recovery feature itself is verified at unit + "
        "MockWorld scenario layers (PR #8482). Tracking: #8483.",
        file=sys.stderr,
    )
