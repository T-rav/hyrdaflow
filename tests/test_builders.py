"""Tests for fluent builder classes (WorkerResultBuilder, PlanResultBuilder, ReviewResultBuilder)."""

from __future__ import annotations

import inspect
import pathlib

import pytest

from tests.conftest import (
    PlanResultBuilder,
    PlanResultFactory,
    ReviewResultBuilder,
    ReviewResultFactory,
    WorkerResultBuilder,
    WorkerResultFactory,
)


class TestWorkerResultBuilder:
    """Tests for WorkerResultBuilder fluent API."""

    def test_build_defaults_match_factory(self):
        """Builder with no overrides produces same result as factory defaults."""
        from_factory = WorkerResultFactory.create()
        from_builder = WorkerResultBuilder().build()

        assert from_builder.issue_number == from_factory.issue_number
        assert from_builder.branch == from_factory.branch
        assert from_builder.success == from_factory.success
        assert from_builder.transcript == from_factory.transcript
        assert from_builder.commits == from_factory.commits

    def test_with_methods_override_fields(self):
        result = (
            WorkerResultBuilder()
            .with_issue_number(99)
            .with_branch("agent/issue-99")
            .with_success(False)
            .with_error("boom")
            .with_transcript("log")
            .with_commits(0)
            .with_duration_seconds(5.0)
            .build()
        )

        assert result.issue_number == 99
        assert result.branch == "agent/issue-99"
        assert result.success is False
        assert result.error == "boom"
        assert result.transcript == "log"
        assert result.commits == 0
        assert result.duration_seconds == 5.0

    def test_fluent_chaining_returns_self(self):
        builder = WorkerResultBuilder()
        same = builder.with_issue_number(1)
        assert same is builder

    def test_with_workspace_path(self):
        result = WorkerResultBuilder().with_workspace_path("/tmp/wt").build()
        assert result.workspace_path == "/tmp/wt"

    def test_with_quality_attempts(self):
        result = (
            WorkerResultBuilder()
            .with_pre_quality_review_attempts(3)
            .with_quality_fix_attempts(2)
            .build()
        )
        assert result.pre_quality_review_attempts == 3
        assert result.quality_fix_attempts == 2

    def test_with_pr_info(self):
        from tests.conftest import PRInfoFactory

        pr_info = PRInfoFactory.create(number=200, issue_number=42)
        result = WorkerResultBuilder().with_pr_info(pr_info).build()
        assert result.pr_info is pr_info

    def test_model_defaults_uses_pydantic_defaults(self):
        """with_model_defaults() uses Pydantic model defaults, not factory hardcoded values."""
        result = WorkerResultBuilder().with_model_defaults().build()
        # Pydantic defaults: success=False, transcript="", commits=0
        assert result.success is False
        assert result.transcript == ""
        assert result.commits == 0
        assert result.workspace_path == ""

    def test_model_defaults_with_overrides(self):
        """with_model_defaults() still respects explicit .with_*() overrides."""
        result = (
            WorkerResultBuilder()
            .with_model_defaults()
            .with_success(True)
            .with_commits(5)
            .build()
        )
        assert result.success is True
        assert result.commits == 5
        # Non-overridden fields use Pydantic defaults
        assert result.transcript == ""

    def test_model_defaults_chaining_returns_self(self):
        builder = WorkerResultBuilder()
        same = builder.with_model_defaults()
        assert same is builder


class TestPlanResultBuilder:
    """Tests for PlanResultBuilder fluent API."""

    def test_build_defaults_match_factory(self):
        from_factory = PlanResultFactory.create()
        from_builder = PlanResultBuilder().build()

        assert from_builder.issue_number == from_factory.issue_number
        assert from_builder.success == from_factory.success
        assert from_builder.plan == from_factory.plan
        assert from_builder.summary == from_factory.summary

    def test_with_methods_override_fields(self):
        result = (
            PlanResultBuilder()
            .with_issue_number(77)
            .with_success(False)
            .with_plan("## New Plan")
            .with_summary("New summary")
            .with_error("plan failed")
            .with_duration_seconds(20.0)
            .build()
        )

        assert result.issue_number == 77
        assert result.success is False
        assert result.plan == "## New Plan"
        assert result.summary == "New summary"
        assert result.error == "plan failed"
        assert result.duration_seconds == 20.0

    def test_fluent_chaining_returns_self(self):
        builder = PlanResultBuilder()
        same = builder.with_success(True)
        assert same is builder

    def test_with_new_issues(self):
        from models import NewIssueSpec

        specs = [NewIssueSpec(title="Sub-task A", body="Do A")]
        result = PlanResultBuilder().with_new_issues(specs).build()
        assert result.new_issues == specs

    def test_with_validation_errors(self):
        result = (
            PlanResultBuilder()
            .with_validation_errors(["missing step", "no tests"])
            .build()
        )
        assert result.validation_errors == ["missing step", "no tests"]

    def test_with_retry_and_satisfaction(self):
        result = (
            PlanResultBuilder()
            .with_retry_attempted(True)
            .with_already_satisfied(True)
            .build()
        )
        assert result.retry_attempted is True
        assert result.already_satisfied is True

    def test_with_actionability(self):
        result = (
            PlanResultBuilder()
            .with_actionability_score(85)
            .with_actionability_rank("high")
            .build()
        )
        assert result.actionability_score == 85
        assert result.actionability_rank == "high"

    def test_with_epic_number(self):
        result = PlanResultBuilder().with_epic_number(10).build()
        assert result.epic_number == 10

    def test_with_transcript(self):
        result = (
            PlanResultBuilder().with_transcript("PLAN_START\n## Plan\nPLAN_END").build()
        )
        assert result.transcript == "PLAN_START\n## Plan\nPLAN_END"

    def test_model_defaults_uses_pydantic_defaults(self):
        """with_model_defaults() uses Pydantic model defaults, not factory hardcoded values."""
        result = PlanResultBuilder().with_model_defaults().build()
        # Pydantic defaults: success=False, plan="", summary=""
        assert result.success is False
        assert result.plan == ""
        assert result.summary == ""
        assert result.duration_seconds == 0.0

    def test_model_defaults_with_overrides(self):
        """with_model_defaults() still respects explicit .with_*() overrides."""
        result = (
            PlanResultBuilder()
            .with_model_defaults()
            .with_success(True)
            .with_plan("## Custom Plan")
            .build()
        )
        assert result.success is True
        assert result.plan == "## Custom Plan"
        # Non-overridden fields use Pydantic defaults
        assert result.summary == ""

    def test_model_defaults_chaining_returns_self(self):
        builder = PlanResultBuilder()
        same = builder.with_model_defaults()
        assert same is builder


class TestReviewResultBuilder:
    """Tests for ReviewResultBuilder fluent API."""

    def test_build_defaults_match_factory(self):
        from_factory = ReviewResultFactory.create()
        from_builder = ReviewResultBuilder().build()

        assert from_builder.pr_number == from_factory.pr_number
        assert from_builder.issue_number == from_factory.issue_number
        assert from_builder.verdict == from_factory.verdict
        assert from_builder.summary == from_factory.summary

    def test_with_methods_override_fields(self):
        from models import ReviewVerdict

        result = (
            ReviewResultBuilder()
            .with_pr_number(200)
            .with_issue_number(55)
            .with_verdict(ReviewVerdict.REQUEST_CHANGES)
            .with_summary("Needs work")
            .with_fixes_made(True)
            .with_merged(True)
            .with_duration_seconds(15.0)
            .with_ci_passed(True)
            .with_ci_fix_attempts(2)
            .build()
        )

        assert result.pr_number == 200
        assert result.issue_number == 55
        assert result.verdict == ReviewVerdict.REQUEST_CHANGES
        assert result.summary == "Needs work"
        assert result.fixes_made is True
        assert result.merged is True
        assert result.duration_seconds == 15.0
        assert result.ci_passed is True
        assert result.ci_fix_attempts == 2

    def test_fluent_chaining_returns_self(self):
        builder = ReviewResultBuilder()
        same = builder.with_pr_number(1)
        assert same is builder

    def test_with_transcript(self):
        result = ReviewResultBuilder().with_transcript("review log").build()
        assert result.transcript == "review log"

    def test_with_success_and_error(self):
        result = ReviewResultBuilder().with_success(True).with_error("oops").build()
        assert result.success is True
        assert result.error == "oops"

    def test_with_commit_stat(self):
        result = ReviewResultBuilder().with_commit_stat("1 file changed").build()
        assert result.commit_stat == "1 file changed"

    def test_with_visual_passed(self):
        result = ReviewResultBuilder().with_visual_passed(False).build()
        assert result.visual_passed is False

    def test_with_files_changed(self):
        result = ReviewResultBuilder().with_files_changed(["src/foo.py"]).build()
        assert result.files_changed == ["src/foo.py"]

    def test_model_defaults_uses_pydantic_defaults(self):
        """with_model_defaults() uses Pydantic model defaults, not factory hardcoded values."""
        from models import ReviewVerdict

        result = ReviewResultBuilder().with_model_defaults().build()
        # Pydantic defaults: verdict=COMMENT, summary="", transcript=""
        assert result.verdict == ReviewVerdict.COMMENT
        assert result.summary == ""
        assert result.transcript == ""
        assert result.fixes_made is False

    def test_model_defaults_with_overrides(self):
        """with_model_defaults() still respects explicit .with_*() overrides."""
        from models import ReviewVerdict

        result = (
            ReviewResultBuilder()
            .with_model_defaults()
            .with_verdict(ReviewVerdict.APPROVE)
            .with_summary("LGTM")
            .build()
        )
        assert result.verdict == ReviewVerdict.APPROVE
        assert result.summary == "LGTM"
        # Non-overridden fields use Pydantic defaults
        assert result.transcript == ""

    def test_model_defaults_chaining_returns_self(self):
        builder = ReviewResultBuilder()
        same = builder.with_model_defaults()
        assert same is builder


@pytest.mark.parametrize(
    "builder_cls",
    [WorkerResultBuilder, PlanResultBuilder, ReviewResultBuilder],
    ids=["WorkerResultBuilder", "PlanResultBuilder", "ReviewResultBuilder"],
)
def test_all_with_methods_are_tested(builder_cls):
    """Every with_* method on each builder must be exercised in this test file."""
    source = pathlib.Path(__file__).read_text()
    with_methods = [
        name
        for name, _ in inspect.getmembers(builder_cls, predicate=inspect.isfunction)
        if name.startswith("with_")
    ]
    untested = [m for m in with_methods if f".{m}(" not in source]
    assert untested == [], (
        f"{builder_cls.__name__} has untested with_* methods: {untested}"
    )
