"""Tier-1 scenario: PostVerifyAdvisor on the pr_review surface — happy path.

T9 of the advisor-pattern feature. Asserts that when the executor returns
APPROVE and the advisor returns APPROVE, the PR is merged and the advisor
was invoked exactly once for the post_verify role.

Tier-2 parity test: ``tests/sandbox_scenarios/scenarios/s_advisor_full_loop.py``
(ADR-0052 rule 3 — every sandbox scenario has a Tier-1 parity test).
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewPostVerifyHappyPath:
    """Executor APPROVE + advisor APPROVE → PR merges, advisor runs once."""

    async def test_post_verify_approves_and_merges(
        self, mock_world, monkeypatch
    ) -> None:
        # Enable the advisor master and the pr_review surface kill-switches
        # explicitly. is_advisor_enabled defaults to True when env unset, but
        # being explicit guards against test-suite-wide overrides.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")

        world = mock_world
        IssueBuilder().numbered(7).titled("Add advisor wiring").bodied(
            "Wire PostVerifyAdvisor into ReviewPhase"
        ).at(world)

        # Script the advisor: APPROVE with empty disagreements. The runner
        # adapter inside ReviewPhase pops this when post-verify fires.
        advisor_payload = json.dumps(
            {
                "verdict": "APPROVE",
                "reasoning": "Executor verdict matches diff intent.",
                "disagreements": [],
                "suggested_fix_direction": None,
            }
        )
        world._llm.script_advisor(7, "post_verify", [advisor_payload])

        result = await world.run_pipeline()

        outcome = result.issue(7)
        assert outcome.review_result is not None
        assert outcome.merged is True, "PR should merge after advisor APPROVE"
        # The advisor's pop_advisor_result is invoked exactly once for the
        # one post-verify call this scenario produces.
        assert world._llm.advisor_call_count_for("post_verify") == 1
