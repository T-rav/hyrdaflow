"""s00_smoke — trivial parity-only scenario proving the wiring resolves.

PR A scenario. Has no Tier-2 (sandbox) implementation yet; just
exercises the full apply_seed -> run_with_loops chain in-process to
verify nothing in the foundation refactor broke.

Tier-2 implementation lands in PR B (s01_happy_single_issue).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s00_smoke"
DESCRIPTION = "Trivial parity-only scenario - no UI assertions; proves wiring."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "smoke", "body": "b", "labels": ["hydraflow-ready"]},
        ],
        cycles_to_run=2,
    )


# No assert_outcome - this scenario is parity-only (Tier 1 in-process).
# PR B's s01 introduces the assert_outcome pattern for Tier 2.
