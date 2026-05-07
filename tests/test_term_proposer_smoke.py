"""End-to-end smoke test for TermProposerLoop using a recorded LLM cassette.

Skipped on CI: the cassette format may evolve and this is a developer sanity
check. Run locally with:

    pytest tests/test_term_proposer_smoke.py -v -m "not skip"

Per ADR-0054 / spec §14: this placeholder exists so the test surface is in
the codebase and shows up in test counts. Recording the actual cassette is a
one-shot manual operation during local development; until then the test is
skipped.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Integration smoke test; run locally only — cassette pending")
@pytest.mark.asyncio
async def test_full_tick_against_synthetic_repo() -> None:
    """Build a synthetic 5-class repo with 1 seeded term, run one tick, assert the loop:
    - detected the 4 uncovered candidates,
    - drafted them via the (cassette-replayed) LLM,
    - validated the drafts,
    - opened ONE bundled PR with all surviving drafts,
    - recorded each candidate in the DedupStore.

    Skeleton — implementation depends on the project's cassette wiring (ADR-0047)
    discovered during local development. The spec calls for this test; this
    file creates the placeholder. Actual cassette recording happens before
    promoting the test from skip-on-CI to active.
    """
    pytest.fail("Cassette not yet recorded — run locally to record")
