"""Tier-1 scenario: PostVerifyAdvisor VETO -> retry -> APPROVE -> PR merges.

T10 of the advisor-pattern feature. Asserts that when the advisor vetoes
the first attempt and approves the second, the executor's fix is
re-reviewed and the PR merges. Validates the bounded veto-retry loop
introduced in `ReviewPhase._run_post_verify_advisor`.
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewVetoRetryRecovers:
    """Advisor VETO on attempt 1, APPROVE on attempt 2 -> PR merges."""

    async def test_veto_then_approve_merges(self, mock_world, monkeypatch) -> None:
        # Enable the advisor master and the pr_review surface kill-switches
        # explicitly so the retry loop is reachable regardless of test-suite
        # default overrides.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")

        world = mock_world
        IssueBuilder().numbered(11).titled("Risky change").bodied(
            "Touches load-bearing module"
        ).at(world)

        # Two scripted advisor responses: VETO first, APPROVE second. The
        # retry loop in _run_post_verify_advisor pops one per advisor call.
        veto_payload = json.dumps(
            {
                "verdict": "VETO",
                "reasoning": "missed a regression in module X",
                "disagreements": [
                    {
                        "executor_claim": "fix is complete",
                        "advisor_assessment": "still missing X test",
                        "severity": "blocking",
                    }
                ],
                "suggested_fix_direction": "add a regression test for X",
            }
        )
        approve_payload = json.dumps(
            {
                "verdict": "APPROVE",
                "reasoning": "regression test added; risk addressed",
                "disagreements": [],
                "suggested_fix_direction": None,
            }
        )
        world._llm.script_advisor(11, "post_verify", [veto_payload, approve_payload])

        result = await world.run_pipeline()
        outcome = result.issue(11)
        assert outcome.review_result is not None
        assert outcome.merged is True, "PR should merge after retry"
        # The advisor was popped exactly twice — once for the initial VETO,
        # once for the post-fix APPROVE.
        assert world._llm.advisor_call_count_for("post_verify") == 2
