import pytest
from pydantic import ValidationError
from review_advisor import (
    Disagreement,
    FocusArea,
    PostVerifyInput,
    PostVerifyResult,
    PreFlightInput,
    ReviewPlan,
)


class TestReviewPlanSchema:
    def test_focus_area_requires_description_files_rationale(self):
        fa = FocusArea(description="d", files=["a.py"], rationale="r")
        assert fa.description == "d"
        assert fa.files == ["a.py"]

    def test_review_plan_full_shape(self):
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[FocusArea(description="d", files=["a.py"], rationale="r")],
            rubric=["check 1", "check 2"],
            escalation_signals=["see X"],
        )
        assert plan.rubric == ["check 1", "check 2"]

    def test_review_plan_serializes_to_json_round_trip(self):
        plan = ReviewPlan(
            risk_summary="r", focus_areas=[], rubric=[], escalation_signals=[]
        )
        data = plan.model_dump_json()
        restored = ReviewPlan.model_validate_json(data)
        assert restored == plan


class TestPostVerifyResultSchema:
    def test_verdict_must_be_approve_or_veto(self):
        with pytest.raises(ValidationError):
            PostVerifyResult(verdict="MAYBE", reasoning="r", disagreements=[])

    def test_disagreement_severity_constrained(self):
        with pytest.raises(ValidationError):
            Disagreement(
                executor_claim="c",
                advisor_assessment="a",
                severity="critical",
            )

    def test_post_verify_result_minimal(self):
        r = PostVerifyResult(verdict="APPROVE", reasoning="ok", disagreements=[])
        assert r.suggested_fix_direction is None


class TestInputSchemas:
    def test_pre_flight_input_minimal(self):
        inp = PreFlightInput(surface="pr_review", diff="d")
        assert inp.spec is None
        assert inp.related_paths == []
        assert inp.prior_attempts == 0

    def test_post_verify_input_minimal(self):
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        assert inp.attempt_number == 0
        assert inp.pre_flight_plan is None
