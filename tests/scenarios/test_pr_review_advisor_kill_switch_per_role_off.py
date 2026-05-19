"""Tier-1 scenario: HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED=false → post-verify
disabled even when master + surface are enabled.

T15 of the advisor-pattern feature. Validates ``is_advisor_enabled``'s
AND-across-master/role/surface composition: with master and per-surface
both enabled but the per-role flag off, ``_run_post_verify_advisor``
must still short-circuit and never invoke the advisor.
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewAdvisorPostVerifyRoleOff:
    """Per-role kill-switch off — advisor not invoked, executor verdict final."""

    async def test_post_verify_role_off_skips_advisor(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "false")

        world = mock_world
        IssueBuilder().numbered(21).titled("docs").bodied("docs").at(world)

        result = await world.run_pipeline()
        _ = result.issue(21)

        # Per-role kill-switch off: no post-verify call, executor verdict final
        assert world._llm.advisor_call_count_for("post_verify") == 0
