"""Tier-1 scenario: 3 vetoes exhaust the retry budget and escalate to HITL.

T11 of the advisor-pattern feature. With ``max_veto_retries=2`` (the
``pr_review`` surface default), three consecutive VETOs (initial attempt
+ 2 retries) trip the exhaustion branch in
``ReviewPhase._run_post_verify_advisor`` and route the PR to HITL via
``_escalate_to_hitl`` with the full disagreement transcript. The
exhausted run must NOT merge.
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewVetoExhaustedEscalatesHITL:
    """3 vetoes (max_veto_retries=2 + the initial attempt) -> HITL, no merge."""

    async def test_three_vetoes_escalate_hitl(self, mock_world, monkeypatch) -> None:
        # Enable the advisor master and the pr_review surface kill-switches
        # explicitly so the retry loop is reachable regardless of test-suite
        # default overrides.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")

        world = mock_world
        IssueBuilder().numbered(13).titled("Stuck change").bodied(
            "Persistently disputed by advisor"
        ).at(world)

        veto_payload = json.dumps(
            {
                "verdict": "VETO",
                "reasoning": "missed regression in module Y",
                "disagreements": [
                    {
                        "executor_claim": "addressed",
                        "advisor_assessment": "still missing Y test",
                        "severity": "blocking",
                    }
                ],
                "suggested_fix_direction": "add a regression test for Y",
            }
        )
        # max_veto_retries=2 -> initial + 2 retries = 3 advisor calls all VETO.
        world._llm.script_advisor(13, "post_verify", [veto_payload] * 3)

        result = await world.run_pipeline()

        outcome = result.issue(13)
        assert outcome.review_result is not None
        assert outcome.merged is False, "PR must not merge after veto exhaustion"
        # The advisor was popped exactly three times — once for the initial
        # VETO and once per retry — before the budget tripped exhaustion.
        assert world._llm.advisor_call_count_for("post_verify") == 3, (
            "advisor should fire 3 times (initial + 2 retries) then escalate"
        )
        # Exhaustion routes through ``_escalate_to_hitl``, which publishes a
        # ``HITL_ESCALATION`` event with cause ``advisor_post_verify_veto``.
        # Asserting on the event (rather than label state) is durable across
        # post-escalation pipeline phases that may re-label the issue: after
        # T10's exhaustion branch flips the verdict to REQUEST_CHANGES, the
        # caller's normal REQUEST_CHANGES handling re-queues to ready and
        # would otherwise overwrite the diagnose label.
        events = result.pipeline_results[0].events
        veto_escalations = [
            e
            for e in events
            if e.type.value == "hitl_escalation"
            and e.data.get("cause") == "advisor_post_verify_veto"
            and e.data.get("issue") == 13
        ]
        assert len(veto_escalations) == 1, (
            f"expected exactly one advisor_post_verify_veto HITL_ESCALATION "
            f"event for issue 13, got {[(e.type.value, e.data) for e in events if e.type.value == 'hitl_escalation']!r}"
        )
