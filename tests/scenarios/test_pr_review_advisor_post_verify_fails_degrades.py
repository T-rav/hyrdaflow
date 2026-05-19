"""Tier-1 scenario: when the advisor runner errors and FAIL_AS_VETO is unset,
the post-verify result degrades to APPROVE so merge proceeds (PostVerifyAdvisor
internal _handle_failure default behavior).

T15 of the advisor-pattern feature. Validates the fail-open default for
the advisor failure-mode envelope: with no scripted advisor result, the
MockWorld runner returns an empty string, ``json.loads`` raises, and
``_handle_failure`` resolves to APPROVE (the default when
``HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO`` is unset).
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewAdvisorPostVerifyFailsDegrades:
    """Runner-error / parse-error degrades to APPROVE under default failure mode."""

    async def test_runner_error_degrades_to_approve(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)

        world = mock_world
        IssueBuilder().numbered(23).titled("docs").bodied("docs").at(world)

        # Script no advisor result — pop_advisor_result returns None →
        # PostVerifyAdvisor.run will fail JSON parse and route through
        # _handle_failure, which defaults to APPROVE.
        # (Does NOT script_advisor — leaves the queue empty)

        result = await world.run_pipeline()
        outcome = result.issue(23)
        # Advisor was invoked (count == 1), got None → parse-error → APPROVE
        assert world._llm.advisor_call_count_for("post_verify") == 1
        assert outcome.merged is True
