"""Tier-1 scenario: executor calls consult_advisor mid-review.

T21 of the advisor-pattern feature. The MockWorld FakeLLM scripts both an
executor verdict path and a mid-flight advisor response.

Note: in production, the executor's actual mid-flight Task call is emitted
from inside its session — MockWorld doesn't simulate the executor's
internal Task dispatch (the FakeReviewRunner.review just returns a baked
ReviewResult). This scenario therefore verifies, in two complementary
shapes:

  1. End-to-end: the standard pipeline runs post-verify exactly once on
     the APPROVE path (sanity that mid-flight wiring doesn't disrupt the
     existing post-verify dispatch).
  2. Direct adapter smoke: the ``_PostVerifyRunner`` adapter on the live
     ReviewPhase is invoked with a mid-flight prompt and the FakeLLM
     ``mid_flight`` queue is correctly drained — pinning the role-detection
     contract used by the executor's in-session Task call.

Together these document the role-routing plumbing without requiring a
faked executor that emits Task calls.
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewMidFlightConsult:
    """Mid-flight consult role routing pipes through to FakeLLM correctly."""

    async def test_midflight_advisor_role_routes_correctly(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")

        world = mock_world
        IssueBuilder().numbered(40).titled("ambiguous").bodied("judgment-heavy fix").at(
            world
        )

        # Script a mid-flight advisor response keyed by issue 40.
        world._llm.script_advisor(
            40,
            "mid_flight",
            [
                json.dumps(
                    {
                        "reasoning": "the test is correct; the fix is wrong",
                        "recommendation": "revert the fix",
                        "confidence": 0.85,
                    }
                )
            ],
        )

        # Also script post-verify (which the standard pipeline calls).
        world._llm.script_advisor(
            40,
            "post_verify",
            [
                json.dumps(
                    {
                        "verdict": "APPROVE",
                        "reasoning": "executor correctly handled the mid-flight advice",
                        "disagreements": [],
                    }
                )
            ],
        )

        # Run the pipeline — executor + post-verify run.
        result = await world.run_pipeline()
        outcome = result.issue(40)
        assert outcome.review_result is not None

        # Post-verify ran exactly once on the APPROVE path.
        assert world._llm.advisor_call_count_for("post_verify") == 1

        # Direct-runner smoke: invoke the adapter with a mid-flight prompt
        # to pin the role-detection contract the executor's in-session
        # Task call relies on. The harness's review_phase carries the
        # adapter that production also uses.
        #
        # The mid-flight prompt MUST start with ``MidFlightAdvisor.SENTINEL``
        # — that's the only signal the runner adapter sees for in-session
        # Task calls (which can't pass ``role=`` through the Task tool). The
        # ``role=`` parameter below is set to ``"post_verify"`` to mimic the
        # ``role`` default the runner would receive from a non-mid-flight
        # caller; the sentinel takes precedence when present (T24.5 closed
        # I1+I2).
        from review_advisor import MidFlightAdvisor

        review_phase = world._harness.review_phase
        runner = review_phase._post_verify_runner

        midflight_prompt = (
            f"{MidFlightAdvisor.SENTINEL}\n"
            "## Mid-flight consult\n"
            "Issue: 40\n"
            "### Question\nis the test wrong or the fix wrong?\n"
            "### Context (summary from executor)\n"
            "line 42 fails after the one-line change\n"
            'Respond with JSON: {"reasoning":str,"recommendation":str,'
            '"confidence":float}'
        )
        payload = await runner.run(
            model="opus",
            subagent_type="hydraflow-review-advisor",
            prompt=midflight_prompt,
            role="post_verify",
        )
        parsed = json.loads(payload)
        assert parsed["recommendation"] == "revert the fix"
        assert world._llm.advisor_call_count_for("mid_flight") == 1
