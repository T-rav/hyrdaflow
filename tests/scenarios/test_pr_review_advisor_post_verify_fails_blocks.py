"""Tier-1 scenario: HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO=true →
when advisor errors, treat as VETO instead of degrading.

T15 of the advisor-pattern feature. Validates the fail-closed mode of
the advisor failure-mode envelope: each advisor invocation hits a
parse-error path (no scripted result), ``_handle_failure`` returns VETO
(because FAIL_AS_VETO=true), and the bounded retry loop exhausts after
``max_veto_retries+1 == 3`` calls — escalating to HITL with the merge
blocked.
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewAdvisorPostVerifyFailsBlocks:
    """Runner-error treated as VETO under FAIL_AS_VETO — exhausts to HITL."""

    async def test_runner_error_blocks_with_fail_as_veto(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", "true")

        world = mock_world
        IssueBuilder().numbered(24).titled("docs").bodied("docs").at(world)

        # No advisor result scripted → JSON parse error on each retry attempt
        # → all attempts return VETO under FAIL_AS_VETO=true →
        # exhausted → HITL escalation, no merge

        result = await world.run_pipeline()
        outcome = result.issue(24)
        # Advisor was invoked max_veto_retries+1 times = 3 times
        assert world._llm.advisor_call_count_for("post_verify") == 3
        assert outcome.merged is False
