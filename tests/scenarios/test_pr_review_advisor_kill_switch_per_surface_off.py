"""Tier-1 scenario: HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED=false → that
surface's advisor is disabled even with master + role enabled.

T15 of the advisor-pattern feature. Validates the per-surface tier of
``is_advisor_enabled``: master and per-role both enabled, per-surface
off — ``_run_post_verify_advisor`` must short-circuit so no advisor
call is recorded for the pr_review surface.
"""

from __future__ import annotations

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewAdvisorPerSurfaceOff:
    """Per-surface kill-switch off — advisor not invoked on pr_review."""

    async def test_pr_review_surface_off_skips_advisor(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "false")

        world = mock_world
        IssueBuilder().numbered(22).titled("doc fix").bodied("doc fix").at(world)

        result = await world.run_pipeline()
        _ = result.issue(22)

        # Per-surface off — no post-verify on pr_review
        assert world._llm.advisor_call_count_for("post_verify") == 0
