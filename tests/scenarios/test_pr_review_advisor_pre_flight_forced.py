"""Tier-1 scenario: ``HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON=true`` runs pre-flight
on an otherwise-trivial PR.

T18 of the advisor-pattern feature. The composite trigger normally returns
False on the MockWorld trivial diff (see the sibling
``..._skipped_trivial`` scenario), but the ``FORCE_ON`` env override
bypasses every other branch of ``should_pre_flight``. This scenario
asserts the override path is plumbed end-to-end: the pre-flight runner
adapter fires exactly once and the FakeAdvisorRunner pops the scripted
``ReviewPlan`` payload.
"""

from __future__ import annotations

import json

import pytest

from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario


class TestPRReviewPreFlightForcedOn:
    """``HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON=true`` on a trivial PR runs pre-flight."""

    async def test_force_on_runs_preflight_on_trivial_pr(
        self, mock_world, monkeypatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", "true")

        world = mock_world
        IssueBuilder().numbered(31).titled("docs tweak").bodied(
            "Update README only"
        ).at(world)

        # Script BOTH pre_flight (a ReviewPlan) and post_verify (APPROVE).
        # If the FORCE_ON path doesn't actually invoke pre-flight, the
        # FakeAdvisorRunner pop returns None and the count assertion below
        # catches the regression.
        world._llm.script_advisor(
            31,
            "pre_flight",
            [
                json.dumps(
                    {
                        "risk_summary": "minor docs change",
                        "focus_areas": [],
                        "rubric": ["check spelling"],
                        "escalation_signals": [],
                    }
                )
            ],
        )
        world._llm.script_advisor(
            31,
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
        outcome = result.issue(31)
        assert outcome.review_result is not None

        # FORCE_ON bypasses the composite trigger's False branch; pre-flight
        # runs once. Post-verify always runs once on the APPROVE path.
        assert world._llm.advisor_call_count_for("pre_flight") == 1
        assert world._llm.advisor_call_count_for("post_verify") == 1
