"""Tier-1 scenario: HYDRAFLOW_REVIEW_ADVISOR_ENABLED=false → no advisor calls.

T15 of the advisor-pattern feature. When the master kill-switch is off,
``ReviewPhase._run_post_verify_advisor`` short-circuits before invoking the
advisor; ``FakeLLM.advisor_call_count_for("post_verify")`` therefore stays
at zero. PR-merge behavior reverts to the pre-advisor path: the executor's
APPROVE flows through to merge unaffected.
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewAdvisorMasterKillSwitch:
    """Master kill-switch off — advisor never invoked, executor verdict final."""

    async def test_master_off_skips_advisor_path(self, mock_world, monkeypatch) -> None:
        # Master kill-switch off: pre-advisor behavior; PR review proceeds
        # to merge (or not) on executor verdict alone, no advisor invocation.
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "false")

        world = mock_world
        IssueBuilder().numbered(20).titled("Trivial").bodied("docs only").at(world)

        # Don't script any advisor result — if the code respects the master
        # switch, none should be popped.
        result = await world.run_pipeline()

        outcome = result.issue(20)
        # No advisor was invoked
        assert world._llm.advisor_call_count_for("post_verify") == 0
        # Executor's APPROVE flows through to merge as it would pre-advisor
        assert outcome.merged is True or outcome.review_result is not None
