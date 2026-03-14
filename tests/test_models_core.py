"""Tests for models — core."""

from __future__ import annotations

import pytest

from models import (
    GitHubIssue,
    HITLItem,
    NewIssueSpec,
    Phase,
    PlannerStatus,
    PRInfo,
    PRListItem,
    ReviewerStatus,
    ReviewResult,
    ReviewVerdict,
    Task,
    WorkerResult,
    WorkerStatus,
)
from tests.conftest import PlanResultFactory

# ---------------------------------------------------------------------------
# GitHubIssue
# ---------------------------------------------------------------------------


class TestGitHubIssue:
    """Tests for the GitHubIssue model."""

    def test_minimal_instantiation(self) -> None:
        """Should create an issue with only required fields."""
        # Arrange / Act
        issue = GitHubIssue(number=1, title="Fix the bug")

        # Assert
        assert issue.number == 1
        assert issue.title == "Fix the bug"

    def test_body_defaults_to_empty_string(self) -> None:
        # Arrange / Act
        issue = GitHubIssue(number=1, title="t")

        # Assert
        assert issue.body == ""

    def test_labels_defaults_to_empty_list(self) -> None:
        # Arrange / Act
        issue = GitHubIssue(number=1, title="t")

        # Assert
        assert issue.labels == []

    def test_comments_defaults_to_empty_list(self) -> None:
        # Arrange / Act
        issue = GitHubIssue(number=1, title="t")

        # Assert
        assert issue.comments == []

    def test_url_defaults_to_empty_string(self) -> None:
        # Arrange / Act
        issue = GitHubIssue(number=1, title="t")

        # Assert
        assert issue.url == ""

    def test_all_fields_set(self) -> None:
        # Arrange / Act
        issue = GitHubIssue(
            number=42,
            title="Improve widget",
            body="The widget is slow.",
            labels=["ready", "perf"],
            comments=["LGTM", "Needs tests"],
            url="https://github.com/org/repo/issues/42",
        )

        # Assert
        assert issue.number == 42
        assert issue.title == "Improve widget"
        assert issue.body == "The widget is slow."
        assert issue.labels == ["ready", "perf"]
        assert issue.comments == ["LGTM", "Needs tests"]
        assert issue.url == "https://github.com/org/repo/issues/42"

    def test_labels_are_independent_between_instances(self) -> None:
        """Default mutable lists should not be shared between instances."""
        # Arrange
        issue_a = GitHubIssue(number=1, title="a")
        issue_b = GitHubIssue(number=2, title="b")

        # Act
        issue_a.labels.append("ready")

        # Assert
        assert issue_b.labels == []

    def test_serialization_with_model_dump(self) -> None:
        # Arrange
        issue = GitHubIssue(number=5, title="Serialise me", body="body text")

        # Act
        data = issue.model_dump()

        # Assert
        assert data["number"] == 5
        assert data["title"] == "Serialise me"
        assert data["body"] == "body text"
        assert data["labels"] == []
        assert data["comments"] == []
        assert data["url"] == ""

    # -- Label field validator ------------------------------------------------

    def test_labels_from_dict_list(self) -> None:
        """gh CLI returns labels as list of dicts with a 'name' key."""
        # Arrange / Act
        issue = GitHubIssue.model_validate(
            {"number": 1, "title": "t", "labels": [{"name": "bug"}, {"name": "ready"}]}
        )

        # Assert
        assert issue.labels == ["bug", "ready"]

    def test_labels_from_string_list(self) -> None:
        """Plain string lists (existing usage) must still work."""
        # Arrange / Act
        issue = GitHubIssue(number=1, title="t", labels=["bug", "ready"])

        # Assert
        assert issue.labels == ["bug", "ready"]

    def test_labels_mixed_dict_and_string(self) -> None:
        """Mixed list of dicts and strings should normalise correctly."""
        # Arrange / Act
        issue = GitHubIssue.model_validate(
            {"number": 1, "title": "t", "labels": [{"name": "bug"}, "enhancement"]}
        )

        # Assert
        assert issue.labels == ["bug", "enhancement"]

    # -- Comment field validator -----------------------------------------------

    def test_comments_from_dict_list(self) -> None:
        """gh CLI returns comments as list of dicts with a 'body' key."""
        # Arrange / Act
        issue = GitHubIssue.model_validate(
            {"number": 1, "title": "t", "comments": [{"body": "LGTM"}]}
        )

        # Assert
        assert issue.comments == ["LGTM"]

    def test_comments_from_string_list(self) -> None:
        """Plain string lists (existing usage) must still work."""
        # Arrange / Act
        issue = GitHubIssue(number=1, title="t", comments=["LGTM", "Ship it"])

        # Assert
        assert issue.comments == ["LGTM", "Ship it"]

    def test_comments_mixed_dict_and_string(self) -> None:
        """Mixed list of dicts and strings should normalise correctly."""
        # Arrange / Act
        issue = GitHubIssue.model_validate(
            {"number": 1, "title": "t", "comments": [{"body": "Nice"}, "plain"]}
        )

        # Assert
        assert issue.comments == ["Nice", "plain"]

    def test_comments_dict_missing_body_key(self) -> None:
        """A dict without 'body' should fall back to empty string."""
        # Arrange / Act
        issue = GitHubIssue.model_validate(
            {"number": 1, "title": "t", "comments": [{"author": "alice"}]}
        )

        # Assert
        assert issue.comments == [""]

    # -- Full round-trip -------------------------------------------------------

    def test_model_validate_full_gh_json(self) -> None:
        """Full round-trip: realistic gh issue list JSON blob."""
        # Arrange
        raw = {
            "number": 42,
            "title": "Improve widget",
            "body": "The widget is slow.",
            "labels": [{"name": "hydraflow-ready"}, {"name": "perf"}],
            "comments": [{"body": "LGTM"}, {"body": "Needs tests"}],
            "url": "https://github.com/org/repo/issues/42",
        }

        # Act
        issue = GitHubIssue.model_validate(raw)

        # Assert
        assert issue.number == 42
        assert issue.title == "Improve widget"
        assert issue.body == "The widget is slow."
        assert issue.labels == ["hydraflow-ready", "perf"]
        assert issue.comments == ["LGTM", "Needs tests"]
        assert issue.url == "https://github.com/org/repo/issues/42"

    # -- Author field ----------------------------------------------------------

    def test_author_defaults_to_empty_string(self) -> None:
        issue = GitHubIssue(number=1, title="t")
        assert issue.author == ""

    def test_author_propagated_to_task_metadata(self) -> None:
        issue = GitHubIssue(number=1, title="t", author="alice")
        task = issue.to_task()
        assert task.metadata["author"] == "alice"

    def test_empty_author_not_in_metadata(self) -> None:
        issue = GitHubIssue(number=1, title="t", author="")
        task = issue.to_task()
        assert "author" not in task.metadata

    def test_from_task_round_trips_author(self) -> None:
        issue = GitHubIssue(number=1, title="t", author="bob")
        task = issue.to_task()
        restored = GitHubIssue.from_task(task)
        assert restored.author == "bob"

    def test_milestone_number_propagated_to_task_metadata(self) -> None:
        issue = GitHubIssue(number=1, title="t", milestone_number=5)
        task = issue.to_task()
        assert task.metadata["milestone_number"] == 5

    def test_no_milestone_not_in_metadata(self) -> None:
        issue = GitHubIssue(number=1, title="t")
        task = issue.to_task()
        assert "milestone_number" not in task.metadata


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TestTask:
    """Tests for the Task model and GitHubIssue conversion helpers."""

    def test_task_requires_id_and_title(self) -> None:
        """Task constructor should store the required id and title fields."""
        task = Task(id=1, title="Fix it")
        assert task.id == 1
        assert task.title == "Fix it"

    def test_task_string_defaults_to_empty(self) -> None:
        """Optional string fields should default to empty strings."""
        task = Task(id=1, title="Fix it")
        assert task.body == ""
        assert task.source_url == ""
        assert task.created_at == ""

    def test_task_collection_defaults_to_empty(self) -> None:
        """Optional collection fields should default to empty containers."""
        task = Task(id=1, title="Fix it")
        assert task.tags == []
        assert task.comments == []
        assert task.metadata == {}

    def test_round_trip_to_task(self) -> None:
        """GitHubIssue.to_task() followed by from_task() should reproduce the original."""
        issue = GitHubIssue(
            number=7,
            title="Round trip",
            body="Body text",
            labels=["hydraflow-ready", "bug"],
            comments=["LGTM"],
            url="https://github.com/org/repo/issues/7",
            created_at="2024-01-01T00:00:00Z",
        )
        task = issue.to_task()
        assert task.id == 7
        assert task.title == "Round trip"
        assert task.body == "Body text"
        assert task.tags == ["hydraflow-ready", "bug"]
        assert task.comments == ["LGTM"]
        assert task.source_url == "https://github.com/org/repo/issues/7"
        assert task.created_at == "2024-01-01T00:00:00Z"

        restored = GitHubIssue.from_task(task)
        assert restored.number == 7
        assert restored.title == "Round trip"
        assert restored.body == "Body text"
        assert restored.labels == ["hydraflow-ready", "bug"]
        assert restored.comments == ["LGTM"]
        assert restored.url == "https://github.com/org/repo/issues/7"
        assert restored.created_at == "2024-01-01T00:00:00Z"

    def test_label_preservation(self) -> None:
        """Labels survive the GitHubIssue -> Task -> GitHubIssue trip."""
        labels = ["hydraflow-plan", "enhancement", "priority-high"]
        issue = GitHubIssue(number=99, title="t", labels=labels)
        assert GitHubIssue.from_task(issue.to_task()).labels == labels


# ---------------------------------------------------------------------------
# PlannerStatus
# ---------------------------------------------------------------------------


class TestPlannerStatus:
    """Tests for the PlannerStatus enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (PlannerStatus.QUEUED, "queued"),
            (PlannerStatus.PLANNING, "planning"),
            (PlannerStatus.VALIDATING, "validating"),
            (PlannerStatus.RETRYING, "retrying"),
            (PlannerStatus.DONE, "done"),
            (PlannerStatus.FAILED, "failed"),
        ],
    )
    def test_enum_values(self, member: PlannerStatus, expected_value: str) -> None:
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(PlannerStatus.DONE, str)

    def test_all_members_present(self) -> None:
        assert len(PlannerStatus) == 6

    def test_lookup_by_value(self) -> None:
        status = PlannerStatus("planning")
        assert status is PlannerStatus.PLANNING


# ---------------------------------------------------------------------------
# PlanResult
# ---------------------------------------------------------------------------


class TestNewIssueSpec:
    """Tests for the NewIssueSpec model."""

    def test_minimal_instantiation(self) -> None:
        spec = NewIssueSpec(title="Fix bug")
        assert spec.title == "Fix bug"
        assert spec.body == ""
        assert spec.labels == []

    def test_all_fields_set(self) -> None:
        spec = NewIssueSpec(
            title="Tech debt",
            body="Needs cleanup",
            labels=["tech-debt", "low-priority"],
        )
        assert spec.title == "Tech debt"
        assert spec.body == "Needs cleanup"
        assert spec.labels == ["tech-debt", "low-priority"]

    def test_labels_independent_between_instances(self) -> None:
        a = NewIssueSpec(title="a")
        b = NewIssueSpec(title="b")
        a.labels.append("bug")
        assert b.labels == []


class TestPlanResult:
    """Tests for the PlanResult model."""

    @staticmethod
    def _create(**overrides):
        overrides.setdefault("issue_number", 1)
        overrides.setdefault("use_defaults", True)
        return PlanResultFactory.create(**overrides)

    def test_minimal_instantiation(self) -> None:
        result = self._create(issue_number=10)
        assert result.issue_number == 10

    def test_success_defaults_to_false(self) -> None:
        result = self._create()
        assert result.success is False

    def test_plan_defaults_to_empty_string(self) -> None:
        result = self._create()
        assert result.plan == ""

    def test_summary_defaults_to_empty_string(self) -> None:
        result = self._create()
        assert result.summary == ""

    def test_error_defaults_to_none(self) -> None:
        result = self._create()
        assert result.error is None

    def test_transcript_defaults_to_empty_string(self) -> None:
        result = self._create()
        assert result.transcript == ""

    def test_duration_seconds_defaults_to_zero(self) -> None:
        result = self._create()
        assert result.duration_seconds == pytest.approx(0.0)

    def test_new_issues_defaults_to_empty_list(self) -> None:
        result = self._create()
        assert result.new_issues == []

    def test_new_issues_can_be_populated(self) -> None:
        spec = NewIssueSpec(title="Bug", body="Details")
        result = self._create(new_issues=[spec])
        assert len(result.new_issues) == 1
        assert result.new_issues[0].title == "Bug"

    def test_validation_errors_defaults_to_empty_list(self) -> None:
        result = self._create()
        assert result.validation_errors == []

    def test_validation_errors_can_be_populated(self) -> None:
        result = self._create(validation_errors=["Missing section", "Too short"])
        assert len(result.validation_errors) == 2

    def test_retry_attempted_defaults_to_false(self) -> None:
        result = self._create()
        assert result.retry_attempted is False

    def test_retry_attempted_can_be_set(self) -> None:
        result = self._create(retry_attempted=True)
        assert result.retry_attempted is True

    def test_already_satisfied_defaults_to_false(self) -> None:
        result = self._create()
        assert result.already_satisfied is False

    def test_already_satisfied_can_be_set(self) -> None:
        result = self._create(already_satisfied=True)
        assert result.already_satisfied is True

    def test_all_fields_set(self) -> None:
        result = self._create(
            issue_number=7,
            success=True,
            plan="Step 1: Do the thing",
            summary="Implementation plan",
            error=None,
            transcript="Full transcript here.",
            duration_seconds=30.5,
        )
        assert result.issue_number == 7
        assert result.success is True
        assert result.plan == "Step 1: Do the thing"
        assert result.summary == "Implementation plan"
        assert result.error is None
        assert result.transcript == "Full transcript here."
        assert result.duration_seconds == pytest.approx(30.5)

    def test_serialization_with_model_dump(self) -> None:
        result = self._create(
            issue_number=3,
            success=True,
            plan="The plan",
            summary="Summary",
        )
        data = result.model_dump()
        assert data["issue_number"] == 3
        assert data["success"] is True
        assert data["plan"] == "The plan"
        assert data["summary"] == "Summary"
        assert data["error"] is None


# ---------------------------------------------------------------------------
# WorkerStatus
# ---------------------------------------------------------------------------


class TestWorkerStatus:
    """Tests for the WorkerStatus enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (WorkerStatus.QUEUED, "queued"),
            (WorkerStatus.RUNNING, "running"),
            (WorkerStatus.PRE_QUALITY_REVIEW, "pre_quality_review"),
            (WorkerStatus.TESTING, "testing"),
            (WorkerStatus.COMMITTING, "committing"),
            (WorkerStatus.QUALITY_FIX, "quality_fix"),
            (WorkerStatus.MERGE_FIX, "merge_fix"),
            (WorkerStatus.DONE, "done"),
            (WorkerStatus.FAILED, "failed"),
        ],
    )
    def test_enum_values(self, member: WorkerStatus, expected_value: str) -> None:
        # Arrange / Act / Assert
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        # Assert
        assert isinstance(WorkerStatus.DONE, str)

    def test_all_ten_members_present(self) -> None:
        # Assert
        assert len(WorkerStatus) == 10

    def test_lookup_by_value(self) -> None:
        # Act
        status = WorkerStatus("running")

        # Assert
        assert status is WorkerStatus.RUNNING


# ---------------------------------------------------------------------------
# WorkerResult
# ---------------------------------------------------------------------------


class TestWorkerResult:
    """Tests for the WorkerResult model."""

    def test_minimal_instantiation(self) -> None:
        """Should create a result with only required fields."""
        # Arrange / Act
        result = WorkerResult(issue_number=10, branch="agent/issue-10")

        # Assert
        assert result.issue_number == 10
        assert result.branch == "agent/issue-10"

    def test_worktree_path_defaults_to_empty_string(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.worktree_path == ""

    def test_success_defaults_to_false(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.success is False

    def test_error_defaults_to_none(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.error is None

    def test_transcript_defaults_to_empty_string(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.transcript == ""

    def test_commits_defaults_to_zero(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.commits == 0

    def test_duration_seconds_defaults_to_zero(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.duration_seconds == pytest.approx(0.0)

    def test_pre_quality_review_attempts_defaults_to_zero(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.pre_quality_review_attempts == 0

    def test_pr_info_defaults_to_none(self) -> None:
        result = WorkerResult(issue_number=1, branch="b")
        assert result.pr_info is None

    def test_pr_info_can_be_set(self) -> None:
        pr = PRInfo(number=101, issue_number=1, branch="b")
        result = WorkerResult(issue_number=1, branch="b", pr_info=pr)
        assert result.pr_info is not None
        assert result.pr_info.number == 101

    def test_all_fields_set(self) -> None:
        # Arrange / Act
        result = WorkerResult(
            issue_number=7,
            branch="agent/issue-7",
            worktree_path="/tmp/wt/issue-7",
            success=True,
            error=None,
            transcript="Done in 3 steps.",
            commits=2,
            duration_seconds=45.3,
        )

        # Assert
        assert result.issue_number == 7
        assert result.branch == "agent/issue-7"
        assert result.worktree_path == "/tmp/wt/issue-7"
        assert result.success is True
        assert result.error is None
        assert result.transcript == "Done in 3 steps."
        assert result.commits == 2
        assert result.duration_seconds == pytest.approx(45.3)

    def test_failed_result_stores_error_message(self) -> None:
        # Arrange / Act
        result = WorkerResult(
            issue_number=99,
            branch="agent/issue-99",
            success=False,
            error="TimeoutError: agent exceeded budget",
        )

        # Assert
        assert result.success is False
        assert result.error == "TimeoutError: agent exceeded budget"

    def test_serialization_with_model_dump(self) -> None:
        # Arrange
        result = WorkerResult(
            issue_number=3, branch="agent/issue-3", commits=1, success=True
        )

        # Act
        data = result.model_dump()

        # Assert
        assert data["issue_number"] == 3
        assert data["branch"] == "agent/issue-3"
        assert data["commits"] == 1
        assert data["success"] is True


# ---------------------------------------------------------------------------
# PRInfo
# ---------------------------------------------------------------------------


class TestPRInfo:
    """Tests for the PRInfo model."""

    def test_minimal_instantiation(self) -> None:
        # Arrange / Act
        pr = PRInfo(number=101, issue_number=42, branch="agent/issue-42")

        # Assert
        assert pr.number == 101
        assert pr.issue_number == 42
        assert pr.branch == "agent/issue-42"

    def test_url_defaults_to_empty_string(self) -> None:
        pr = PRInfo(number=1, issue_number=1, branch="b")
        assert pr.url == ""

    def test_draft_defaults_to_false(self) -> None:
        pr = PRInfo(number=1, issue_number=1, branch="b")
        assert pr.draft is False

    def test_all_fields_set(self) -> None:
        # Arrange / Act
        pr = PRInfo(
            number=200,
            issue_number=55,
            branch="agent/issue-55",
            url="https://github.com/org/repo/pull/200",
            draft=True,
        )

        # Assert
        assert pr.number == 200
        assert pr.issue_number == 55
        assert pr.branch == "agent/issue-55"
        assert pr.url == "https://github.com/org/repo/pull/200"
        assert pr.draft is True

    def test_serialization_with_model_dump(self) -> None:
        # Arrange
        pr = PRInfo(
            number=5,
            issue_number=3,
            branch="agent/issue-3",
            url="https://example.com/pr/5",
        )

        # Act
        data = pr.model_dump()

        # Assert
        assert data["number"] == 5
        assert data["issue_number"] == 3
        assert data["branch"] == "agent/issue-3"
        assert data["url"] == "https://example.com/pr/5"
        assert data["draft"] is False


# ---------------------------------------------------------------------------
# ReviewerStatus
# ---------------------------------------------------------------------------


class TestReviewerStatus:
    """Tests for the ReviewerStatus enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ReviewerStatus.REVIEWING, "reviewing"),
            (ReviewerStatus.DONE, "done"),
            (ReviewerStatus.FAILED, "failed"),
            (ReviewerStatus.FIXING, "fixing"),
            (ReviewerStatus.FIXING_REVIEW_FINDINGS, "fixing_review_findings"),
            (ReviewerStatus.FIX_DONE, "fix_done"),
        ],
    )
    def test_enum_values(self, member: ReviewerStatus, expected_value: str) -> None:
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(ReviewerStatus.DONE, str)

    def test_all_members_present(self) -> None:
        assert len(ReviewerStatus) == 6

    def test_lookup_by_value(self) -> None:
        status = ReviewerStatus("reviewing")
        assert status is ReviewerStatus.REVIEWING


# ---------------------------------------------------------------------------
# ReviewVerdict
# ---------------------------------------------------------------------------


class TestReviewVerdict:
    """Tests for the ReviewVerdict enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ReviewVerdict.APPROVE, "approve"),
            (ReviewVerdict.REQUEST_CHANGES, "request-changes"),
            (ReviewVerdict.COMMENT, "comment"),
        ],
    )
    def test_enum_values(self, member: ReviewVerdict, expected_value: str) -> None:
        # Assert
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(ReviewVerdict.APPROVE, str)

    def test_all_three_members_present(self) -> None:
        assert len(ReviewVerdict) == 3

    def test_lookup_by_value(self) -> None:
        verdict = ReviewVerdict("approve")
        assert verdict is ReviewVerdict.APPROVE

    def test_request_changes_value_with_hyphen(self) -> None:
        """Value uses a hyphen to match the GitHub API string."""
        assert ReviewVerdict.REQUEST_CHANGES.value == "request-changes"


# ---------------------------------------------------------------------------
# ReviewResult
# ---------------------------------------------------------------------------


class TestReviewResult:
    """Tests for the ReviewResult model."""

    def test_minimal_instantiation(self) -> None:
        # Arrange / Act
        review = ReviewResult(pr_number=10, issue_number=5)

        # Assert
        assert review.pr_number == 10
        assert review.issue_number == 5

    def test_verdict_defaults_to_comment(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.verdict is ReviewVerdict.COMMENT

    def test_summary_defaults_to_empty_string(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.summary == ""

    def test_fixes_made_defaults_to_false(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.fixes_made is False

    def test_merged_defaults_to_false(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.merged is False

    def test_merged_can_be_set(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1, merged=True)
        assert review.merged is True

    def test_transcript_defaults_to_empty_string(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.transcript == ""

    def test_all_fields_set(self) -> None:
        # Arrange / Act
        review = ReviewResult(
            pr_number=77,
            issue_number=33,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks great!",
            fixes_made=True,
            transcript="Reviewed 5 files.",
            duration_seconds=12.3,
        )

        # Assert
        assert review.pr_number == 77
        assert review.issue_number == 33
        assert review.verdict is ReviewVerdict.APPROVE
        assert review.summary == "Looks great!"
        assert review.fixes_made is True
        assert review.transcript == "Reviewed 5 files."
        assert review.duration_seconds == pytest.approx(12.3)

    def test_duration_seconds_defaults_to_zero(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.duration_seconds == pytest.approx(0.0)

    def test_duration_seconds_can_be_set(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1, duration_seconds=42.5)
        assert review.duration_seconds == pytest.approx(42.5)

    def test_ci_passed_defaults_to_none(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.ci_passed is None

    def test_ci_fix_attempts_defaults_to_zero(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.ci_fix_attempts == 0

    def test_duration_seconds_in_serialization(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1, duration_seconds=30.0)
        data = review.model_dump()
        assert data["duration_seconds"] == pytest.approx(30.0)

    def test_ci_passed_can_be_set_true(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1, ci_passed=True)
        assert review.ci_passed is True

    def test_ci_passed_can_be_set_false(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1, ci_passed=False)
        assert review.ci_passed is False

    def test_request_changes_verdict(self) -> None:
        review = ReviewResult(
            pr_number=2, issue_number=2, verdict=ReviewVerdict.REQUEST_CHANGES
        )
        assert review.verdict is ReviewVerdict.REQUEST_CHANGES

    def test_serialization_with_model_dump(self) -> None:
        # Arrange
        review = ReviewResult(
            pr_number=8, issue_number=4, verdict=ReviewVerdict.APPROVE, summary="LGTM"
        )

        # Act
        data = review.model_dump()

        # Assert
        assert data["pr_number"] == 8
        assert data["issue_number"] == 4
        assert data["verdict"] == ReviewVerdict.APPROVE
        assert data["summary"] == "LGTM"
        assert data["fixes_made"] is False


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------


class TestPhase:
    """Tests for the Phase enum."""

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (Phase.IDLE, "idle"),
            (Phase.PLAN, "plan"),
            (Phase.IMPLEMENT, "implement"),
            (Phase.REVIEW, "review"),
            (Phase.CLEANUP, "cleanup"),
            (Phase.DONE, "done"),
        ],
    )
    def test_enum_values(self, member: Phase, expected_value: str) -> None:
        # Assert
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(Phase.IMPLEMENT, str)

    def test_all_six_members_present(self) -> None:
        assert len(Phase) == 6

    def test_plan_is_second_phase(self) -> None:
        """PLAN should be the second declared phase (after IDLE)."""
        members = list(Phase)
        assert members[1] is Phase.PLAN

    def test_lookup_by_value(self) -> None:
        phase = Phase("implement")
        assert phase is Phase.IMPLEMENT

    def test_idle_is_first_phase(self) -> None:
        """IDLE should be the first declared phase."""
        members = list(Phase)
        assert members[0] is Phase.IDLE

    def test_done_is_terminal_phase(self) -> None:
        """DONE should be the last declared phase."""
        members = list(Phase)
        assert members[-1] is Phase.DONE

    def test_idle_value_is_idle_string(self) -> None:
        assert Phase.IDLE.value == "idle"

    def test_idle_lookup_by_value(self) -> None:
        phase = Phase("idle")
        assert phase is Phase.IDLE


# ---------------------------------------------------------------------------
# PRListItem
# ---------------------------------------------------------------------------


class TestPRListItem:
    """Tests for the PRListItem response model."""

    def test_minimal_instantiation(self) -> None:
        """Only pr is required."""
        item = PRListItem(pr=42)
        assert item.pr == 42

    def test_pr_list_item_defaults_to_empty_branch_and_no_draft(self) -> None:
        item = PRListItem(pr=1)
        assert item.issue == 0
        assert item.branch == ""
        assert item.url == ""
        assert item.draft is False
        assert item.title == ""

    def test_all_fields_set(self) -> None:
        item = PRListItem(
            pr=10,
            issue=5,
            branch="agent/issue-5",
            url="https://github.com/org/repo/pull/10",
            draft=True,
            title="Fix widget",
        )
        assert item.pr == 10
        assert item.issue == 5
        assert item.branch == "agent/issue-5"
        assert item.url == "https://github.com/org/repo/pull/10"
        assert item.draft is True
        assert item.title == "Fix widget"

    def test_serialization_with_model_dump(self) -> None:
        item = PRListItem(pr=7, issue=3, branch="agent/issue-3", title="Add tests")
        data = item.model_dump()
        assert data == {
            "pr": 7,
            "issue": 3,
            "branch": "agent/issue-3",
            "url": "",
            "draft": False,
            "title": "Add tests",
        }


# ---------------------------------------------------------------------------
# HITLItem
# ---------------------------------------------------------------------------


class TestHITLItem:
    """Tests for the HITLItem response model."""

    def test_minimal_instantiation(self) -> None:
        """Only issue is required."""
        item = HITLItem(issue=42)
        assert item.issue == 42

    def test_hitl_item_defaults_to_empty_title_and_pending_status(self) -> None:
        item = HITLItem(issue=1)
        assert item.title == ""
        assert item.issueUrl == ""
        assert item.pr == 0
        assert item.prUrl == ""
        assert item.branch == ""
        assert item.cause == ""
        assert item.status == "pending"

    def test_all_fields_set(self) -> None:
        item = HITLItem(
            issue=42,
            title="Fix widget",
            issueUrl="https://github.com/org/repo/issues/42",
            pr=99,
            prUrl="https://github.com/org/repo/pull/99",
            branch="agent/issue-42",
            cause="CI failure",
            status="processing",
        )
        assert item.issue == 42
        assert item.title == "Fix widget"
        assert item.issueUrl == "https://github.com/org/repo/issues/42"
        assert item.pr == 99
        assert item.prUrl == "https://github.com/org/repo/pull/99"
        assert item.branch == "agent/issue-42"
        assert item.cause == "CI failure"
        assert item.status == "processing"

    def test_cause_defaults_to_empty_string(self) -> None:
        item = HITLItem(issue=1)
        assert item.cause == ""

    def test_status_defaults_to_pending(self) -> None:
        item = HITLItem(issue=1)
        assert item.status == "pending"

    def test_serialization_with_model_dump(self) -> None:
        """Confirm camelCase keys (issueUrl, prUrl) and new fields serialize correctly."""
        item = HITLItem(
            issue=10,
            title="Broken thing",
            issueUrl="https://example.com/issues/10",
            pr=20,
            prUrl="https://example.com/pull/20",
            branch="agent/issue-10",
            cause="test failure",
            status="processing",
        )
        data = item.model_dump()
        assert data == {
            "issue": 10,
            "title": "Broken thing",
            "issueUrl": "https://example.com/issues/10",
            "pr": 20,
            "prUrl": "https://example.com/pull/20",
            "branch": "agent/issue-10",
            "cause": "test failure",
            "status": "processing",
            "isMemorySuggestion": False,
            "llmSummary": "",
            "llmSummaryUpdatedAt": None,
            "visualEvidence": None,
        }

    def test_serialization_defaults_include_new_fields(self) -> None:
        """model_dump includes cause, status, and isMemorySuggestion even with defaults."""
        item = HITLItem(issue=1)
        data = item.model_dump()
        assert data["cause"] == ""
        assert data["status"] == "pending"
        assert data["isMemorySuggestion"] is False
        assert data["llmSummary"] == ""
        assert data["llmSummaryUpdatedAt"] is None
