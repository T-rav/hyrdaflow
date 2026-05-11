"""Tier-1 scenario: trivial PR diff skips pre-flight (composite trigger says no).

T18 of the advisor-pattern feature. The MockWorld FakeGitHub returns a
trivial unified-diff string (``diff --git a/x b/x``) which has no ``+++``
post-image headers and no ``+``/``-`` body lines. ``should_pre_flight``
therefore returns False (no critical paths, no non-trivial src files,
no prior fix attempts), and the pre-flight runner adapter is never
invoked. Post-verify still fires once on the APPROVE verdict.
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewPreFlightSkippedTrivial:
    """Trivial diff + no prior fix attempts → pre-flight is skipped."""

    async def test_trivial_pr_skips_preflight(self, mock_world, monkeypatch) -> None:
        # Explicit kill-switch state: advisor master + pr_review surface +
        # pre_flight role all enabled. We're testing the composite trigger,
        # not the kill-switch path.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")
        # Make sure FORCE_ON isn't bleeding in from a sibling test.
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)

        world = mock_world
        IssueBuilder().numbered(30).titled("docs tweak").bodied(
            "Update README only"
        ).at(world)

        # Script post-verify APPROVE so the (always-running) post-verify
        # path doesn't degrade. We deliberately do NOT script pre_flight —
        # if the wiring fires it, the FakeAdvisorRunner will pop None and
        # the call_count assertion below will catch the leak.
        world._llm.script_advisor(
            30,
            "post_verify",
            [
                json.dumps(
                    {
                        "verdict": "APPROVE",
                        "reasoning": "ok",
                        "disagreements": [],
                    }
                )
            ],
        )

        result = await world.run_pipeline()
        outcome = result.issue(30)
        assert outcome.review_result is not None

        # Trivial diff → composite trigger returns False → pre-flight runner
        # adapter is never called → call counter stays at 0.
        assert world._llm.advisor_call_count_for("pre_flight") == 0
        # Post-verify still runs exactly once on the APPROVE verdict.
        assert world._llm.advisor_call_count_for("post_verify") == 1
