"""Tests for dx/hydraflow/models.py."""

from __future__ import annotations

import inspect

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from pydantic import ValidationError

from models import (
    BackgroundWorkerStatus,
    BatchResult,
    BGWorkerHealth,
    ConflictResolutionResult,
    ControlStatusConfig,
    ControlStatusResponse,
    GitHubIssue,
    HITLItem,
    InstructionsQuality,
    InstructionsQualityResult,
    IntentResponse,
    IssueTimeline,
    JudgeResult,
    LifetimeStats,
    ManifestRefreshResult,
    MetricsSnapshot,
    NewIssueSpec,
    ParsedCriteria,
    Phase,
    PipelineIssue,
    PipelineIssueStatus,
    PipelineStage,
    PipelineStats,
    PlanAccuracyResult,
    PlannerStatus,
    PrecheckResult,
    PRInfo,
    PRInfoExtract,
    PRListItem,
    QueueStats,
    ReviewerStatus,
    ReviewResult,
    ReviewVerdict,
    SessionLog,
    SessionStatus,
    StageStats,
    StageStatus,
    StateData,
    Task,
    TaskLink,
    TaskLinkKind,
    ThroughputStats,
    TimelineStage,
    VerificationCriteria,
    VerificationCriterion,
    VisualEvidence,
    VisualEvidenceItem,
    WorkerResult,
    WorkerStatus,
    parse_task_links,
)
from tests.conftest import AnalysisResultFactory, PlanResultFactory, ReviewResultFactory

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

    def test_defaults(self) -> None:
        """Task should accept only id and title with sensible defaults."""
        task = Task(id=1, title="Fix it")
        assert task.id == 1
        assert task.title == "Fix it"
        assert task.body == ""
        assert task.tags == []
        assert task.comments == []
        assert task.source_url == ""
        assert task.created_at == ""
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
        """Labels survive the GitHubIssue → Task → GitHubIssue trip."""
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
            (ReviewerStatus.FIX_DONE, "fix_done"),
        ],
    )
    def test_enum_values(self, member: ReviewerStatus, expected_value: str) -> None:
        assert member.value == expected_value

    def test_enum_is_string_subclass(self) -> None:
        assert isinstance(ReviewerStatus.DONE, str)

    def test_all_members_present(self) -> None:
        assert len(ReviewerStatus) == 5

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
# BatchResult
# ---------------------------------------------------------------------------


class TestBatchResult:
    """Tests for the BatchResult model."""

    def test_minimal_instantiation(self) -> None:
        # Arrange / Act
        batch = BatchResult(batch_number=1)

        # Assert
        assert batch.batch_number == 1

    def test_issues_defaults_to_empty_list(self) -> None:
        batch = BatchResult(batch_number=1)
        assert batch.issues == []

    def test_plan_results_defaults_to_empty_list(self) -> None:
        batch = BatchResult(batch_number=1)
        assert batch.plan_results == []

    def test_worker_results_defaults_to_empty_list(self) -> None:
        batch = BatchResult(batch_number=1)
        assert batch.worker_results == []

    def test_pr_infos_defaults_to_empty_list(self) -> None:
        batch = BatchResult(batch_number=1)
        assert batch.pr_infos == []

    def test_review_results_defaults_to_empty_list(self) -> None:
        batch = BatchResult(batch_number=1)
        assert batch.review_results == []

    def test_merged_prs_defaults_to_empty_list(self) -> None:
        batch = BatchResult(batch_number=1)
        assert batch.merged_prs == []

    def test_lists_are_independent_between_instances(self) -> None:
        """Default mutable lists must not be shared between BatchResult instances."""
        # Arrange
        batch_a = BatchResult(batch_number=1)
        batch_b = BatchResult(batch_number=2)

        # Act
        batch_a.merged_prs.append(99)

        # Assert
        assert batch_b.merged_prs == []

    def test_populated_batch_result(self) -> None:
        """Should hold multiple issues, worker results, PRs, reviews, and merged PR numbers."""
        # Arrange
        issues = [
            Task(id=1, title="Issue 1"),
            Task(id=2, title="Issue 2"),
        ]
        worker_results = [
            WorkerResult(
                issue_number=1, branch="agent/issue-1", success=True, commits=1
            ),
            WorkerResult(
                issue_number=2, branch="agent/issue-2", success=False, error="timeout"
            ),
        ]
        pr_infos = [
            PRInfo(number=100, issue_number=1, branch="agent/issue-1"),
        ]
        review_results = [
            ReviewResultFactory.create(
                pr_number=100, issue_number=1, verdict=ReviewVerdict.APPROVE
            ),
        ]
        merged_prs = [100]

        # Act
        batch = BatchResult(
            batch_number=3,
            issues=issues,
            worker_results=worker_results,
            pr_infos=pr_infos,
            review_results=review_results,
            merged_prs=merged_prs,
        )

        # Assert
        assert batch.batch_number == 3
        assert len(batch.issues) == 2
        assert batch.issues[0].id == 1
        assert batch.issues[1].id == 2
        assert len(batch.worker_results) == 2
        assert batch.worker_results[0].success is True
        assert batch.worker_results[1].success is False
        assert len(batch.pr_infos) == 1
        assert batch.pr_infos[0].number == 100
        assert len(batch.review_results) == 1
        assert batch.review_results[0].verdict is ReviewVerdict.APPROVE
        assert batch.merged_prs == [100]

    def test_serialization_with_model_dump(self) -> None:
        # Arrange
        batch = BatchResult(
            batch_number=2,
            issues=[Task(id=10, title="T")],
            merged_prs=[200, 201],
        )

        # Act
        data = batch.model_dump()

        # Assert
        assert data["batch_number"] == 2
        assert len(data["issues"]) == 1
        assert data["issues"][0]["id"] == 10
        assert data["merged_prs"] == [200, 201]
        assert data["worker_results"] == []
        assert data["pr_infos"] == []
        assert data["review_results"] == []

    def test_successful_worker_count_via_list_comprehension(self) -> None:
        """BatchResult does not have a built-in aggregation method, but its data should support it."""
        # Arrange
        batch = BatchResult(
            batch_number=1,
            worker_results=[
                WorkerResult(issue_number=1, branch="b1", success=True),
                WorkerResult(issue_number=2, branch="b2", success=False),
                WorkerResult(issue_number=3, branch="b3", success=True),
            ],
        )

        # Act
        successful = [r for r in batch.worker_results if r.success]

        # Assert
        assert len(successful) == 2


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


# ---------------------------------------------------------------------------
# ControlStatusConfig
# ---------------------------------------------------------------------------


class TestControlStatusConfig:
    """Tests for the ControlStatusConfig response model."""

    def test_minimal_instantiation(self) -> None:
        """No required fields."""
        cfg = ControlStatusConfig()
        assert cfg.repo == ""
        assert cfg.ready_label == []
        assert cfg.find_label == []
        assert cfg.planner_label == []
        assert cfg.review_label == []
        assert cfg.hitl_label == []
        assert cfg.fixed_label == []
        assert cfg.max_workers == 0
        assert cfg.max_planners == 0
        assert cfg.max_reviewers == 0
        assert cfg.batch_size == 0
        assert cfg.model == ""

    def test_all_fields_set(self) -> None:
        cfg = ControlStatusConfig(
            repo="org/repo",
            ready_label=["hydraflow-ready"],
            find_label=["hydraflow-find"],
            planner_label=["hydraflow-plan"],
            review_label=["hydraflow-review"],
            hitl_label=["hydraflow-hitl"],
            fixed_label=["hydraflow-fixed"],
            max_workers=4,
            max_planners=2,
            max_reviewers=1,
            batch_size=10,
            model="opus",
        )
        assert cfg.repo == "org/repo"
        assert cfg.ready_label == ["hydraflow-ready"]
        assert cfg.max_workers == 4
        assert cfg.model == "opus"

    def test_lists_are_independent_between_instances(self) -> None:
        a = ControlStatusConfig()
        b = ControlStatusConfig()
        a.ready_label.append("test")
        assert b.ready_label == []


# ---------------------------------------------------------------------------
# ControlStatusResponse
# ---------------------------------------------------------------------------


class TestControlStatusResponse:
    """Tests for the ControlStatusResponse response model."""

    def test_minimal_instantiation(self) -> None:
        resp = ControlStatusResponse()
        assert resp.status == "idle"
        assert resp.config.repo == ""

    def test_all_fields_set(self) -> None:
        cfg = ControlStatusConfig(repo="org/repo", max_workers=3, model="sonnet")
        resp = ControlStatusResponse(status="running", config=cfg)
        assert resp.status == "running"
        assert resp.config.repo == "org/repo"
        assert resp.config.max_workers == 3

    def test_serialization_with_model_dump(self) -> None:
        """Verify nested config serializes correctly."""
        cfg = ControlStatusConfig(
            repo="org/repo",
            ready_label=["hydraflow-ready"],
            max_workers=2,
            batch_size=15,
            model="sonnet",
        )
        resp = ControlStatusResponse(status="running", config=cfg)
        data = resp.model_dump()
        assert data["status"] == "running"
        assert data["config"]["repo"] == "org/repo"
        assert data["config"]["ready_label"] == ["hydraflow-ready"]
        assert data["config"]["max_workers"] == 2
        assert data["config"]["batch_size"] == 15
        assert data["config"]["model"] == "sonnet"

    def test_credits_paused_until_default_none(self) -> None:
        resp = ControlStatusResponse()
        assert resp.credits_paused_until is None

    def test_credits_paused_until_set(self) -> None:
        resp = ControlStatusResponse(
            status="credits_paused",
            credits_paused_until="2026-02-28T15:30:00+00:00",
        )
        assert resp.credits_paused_until == "2026-02-28T15:30:00+00:00"
        data = resp.model_dump()
        assert data["credits_paused_until"] == "2026-02-28T15:30:00+00:00"


# ---------------------------------------------------------------------------
# LifetimeStats
# ---------------------------------------------------------------------------


class TestLifetimeStats:
    """Tests for the LifetimeStats model."""

    def test_new_volume_counter_defaults(self) -> None:
        stats = LifetimeStats()
        assert stats.total_quality_fix_rounds == 0
        assert stats.total_ci_fix_rounds == 0
        assert stats.total_hitl_escalations == 0
        assert stats.total_review_request_changes == 0
        assert stats.total_review_approvals == 0
        assert stats.total_reviewer_fixes == 0

    def test_new_timing_defaults(self) -> None:
        stats = LifetimeStats()
        assert stats.total_implementation_seconds == pytest.approx(0.0)
        assert stats.total_review_seconds == pytest.approx(0.0)

    def test_fired_thresholds_default(self) -> None:
        stats = LifetimeStats()
        assert stats.fired_thresholds == []

    def test_fired_thresholds_are_independent_between_instances(self) -> None:
        a = LifetimeStats()
        b = LifetimeStats()
        a.fired_thresholds.append("test")
        assert b.fired_thresholds == []

    def test_serialization_roundtrip_with_new_fields(self) -> None:
        stats = LifetimeStats(
            issues_completed=10,
            total_quality_fix_rounds=5,
            total_implementation_seconds=120.5,
            fired_thresholds=["quality_fix_rate"],
        )
        json_str = stats.model_dump_json()
        restored = LifetimeStats.model_validate_json(json_str)
        assert restored == stats

    def test_backward_compat_missing_new_fields(self) -> None:
        """Old data without new fields should get zero defaults."""
        old_data = {"issues_completed": 3, "prs_merged": 1, "issues_created": 0}
        stats = LifetimeStats.model_validate(old_data)
        assert stats.issues_completed == 3
        assert stats.total_quality_fix_rounds == 0
        assert stats.total_implementation_seconds == 0.0
        assert stats.fired_thresholds == []


# ---------------------------------------------------------------------------
# VerificationCriterion
# ---------------------------------------------------------------------------


class TestVerificationCriterion:
    """Tests for the VerificationCriterion model."""

    def test_basic_instantiation(self) -> None:
        cr = VerificationCriterion(
            description="Tests pass", passed=True, details="All 10 pass"
        )
        assert cr.description == "Tests pass"
        assert cr.passed is True
        assert cr.details == "All 10 pass"

    def test_details_defaults_to_empty(self) -> None:
        cr = VerificationCriterion(description="Lint", passed=False)
        assert cr.details == ""

    def test_serialization_round_trip(self) -> None:
        cr = VerificationCriterion(
            description="Type check", passed=True, details="Clean"
        )
        data = cr.model_dump()
        restored = VerificationCriterion.model_validate(data)
        assert restored == cr


# ---------------------------------------------------------------------------
# JudgeResult
# ---------------------------------------------------------------------------


class TestJudgeResult:
    """Tests for the JudgeResult model."""

    def test_all_passed_when_all_criteria_pass(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[
                VerificationCriterion(description="A", passed=True),
                VerificationCriterion(description="B", passed=True),
            ],
        )
        assert judge.all_passed is True
        assert judge.failed_criteria == []

    def test_all_passed_false_when_some_fail(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[
                VerificationCriterion(description="A", passed=True),
                VerificationCriterion(description="B", passed=False, details="Failed"),
            ],
        )
        assert judge.all_passed is False
        assert len(judge.failed_criteria) == 1
        assert judge.failed_criteria[0].description == "B"

    def test_all_passed_true_when_no_criteria(self) -> None:
        judge = JudgeResult(issue_number=42, pr_number=101, criteria=[])
        assert judge.all_passed is True

    def test_failed_criteria_returns_only_failures(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[
                VerificationCriterion(description="A", passed=False),
                VerificationCriterion(description="B", passed=True),
                VerificationCriterion(description="C", passed=False),
            ],
        )
        failed = judge.failed_criteria
        assert len(failed) == 2
        assert {c.description for c in failed} == {"A", "C"}

    def test_judge_result_defaults_to_empty_criteria_instructions_and_summary(
        self,
    ) -> None:
        judge = JudgeResult(issue_number=1, pr_number=2)
        assert judge.criteria == []
        assert judge.verification_instructions == ""
        assert judge.summary == ""

    def test_serialization_round_trip(self) -> None:
        judge = JudgeResult(
            issue_number=42,
            pr_number=101,
            criteria=[VerificationCriterion(description="X", passed=True)],
            verification_instructions="Step 1",
            summary="Good",
        )
        data = judge.model_dump()
        restored = JudgeResult.model_validate(data)
        assert restored.issue_number == judge.issue_number
        assert restored.criteria[0].description == "X"
        assert restored.verification_instructions == "Step 1"


# ---------------------------------------------------------------------------
# StateData - verification_issues field
# ---------------------------------------------------------------------------


class TestStateDataVerificationIssues:
    """Tests for the verification_issues field on StateData."""

    def test_defaults_to_empty_dict(self) -> None:
        data = StateData()
        assert data.verification_issues == {}

    def test_accepts_verification_issues(self) -> None:
        data = StateData(verification_issues={"42": 500, "99": 501})
        assert data.verification_issues["42"] == 500
        assert data.verification_issues["99"] == 501


class TestStateDataManifestFields:
    """Regression tests for manifest-related fields on StateData."""

    def test_manifest_field_defaults(self) -> None:
        data = StateData()
        assert data.manifest_issue_number is None
        assert data.manifest_snapshot_hash == ""

    def test_manifest_fields_accept_explicit_values(self) -> None:
        data = StateData(manifest_issue_number=42, manifest_snapshot_hash="abc123")
        assert data.manifest_issue_number == 42
        assert data.manifest_snapshot_hash == "abc123"

    def test_manifest_fields_round_trip_serialization(self) -> None:
        start = StateData(manifest_issue_number=99, manifest_snapshot_hash="sha256hash")
        payload = start.model_dump()
        restored = StateData.model_validate(payload)
        assert restored.manifest_issue_number == 99
        assert restored.manifest_snapshot_hash == "sha256hash"

    def test_manifest_issue_number_none_survives_round_trip(self) -> None:
        start = StateData(manifest_issue_number=None)
        restored = StateData.model_validate(start.model_dump())
        assert restored.manifest_issue_number is None

    def test_no_duplicate_field_names_in_state_data(self) -> None:
        source = inspect.getsource(StateData)
        field_lines = [
            line.split(":")[0].strip()
            for line in source.splitlines()
            if ":" in line and not line.strip().startswith(("#", "class", '"""'))
        ]
        manifest_fields = [
            f
            for f in field_lines
            if f in {"manifest_issue_number", "manifest_snapshot_hash"}
        ]
        assert manifest_fields.count("manifest_issue_number") == 1
        assert manifest_fields.count("manifest_snapshot_hash") == 1


# ---------------------------------------------------------------------------
# TaskLink / TaskLinkKind
# ---------------------------------------------------------------------------


class TestTaskLink:
    """Tests for the TaskLink and TaskLinkKind models."""

    def test_tasklink_kind_values(self) -> None:
        # Arrange / Act / Assert
        assert TaskLinkKind.RELATES_TO == "relates_to"
        assert TaskLinkKind.DUPLICATES == "duplicates"
        assert TaskLinkKind.SUPERSEDES == "supersedes"
        assert TaskLinkKind.REPLIES_TO == "replies_to"

    def test_tasklink_minimal(self) -> None:
        link = TaskLink(kind=TaskLinkKind.RELATES_TO, target_id=7)

        assert link.kind == TaskLinkKind.RELATES_TO
        assert link.target_id == 7
        assert link.target_url == ""

    def test_tasklink_with_url(self) -> None:
        url = "https://github.com/org/repo/issues/7"
        link = TaskLink(kind=TaskLinkKind.DUPLICATES, target_id=7, target_url=url)

        assert link.target_url == url

    def test_task_links_field_defaults_to_empty(self) -> None:
        task = Task(id=1, title="t")

        assert task.links == []

    def test_task_links_field_accepts_links(self) -> None:
        links = [
            TaskLink(kind=TaskLinkKind.SUPERSEDES, target_id=3),
            TaskLink(kind=TaskLinkKind.REPLIES_TO, target_id=9),
        ]
        task = Task(id=1, title="t", links=links)

        assert len(task.links) == 2
        assert task.links[0].kind == TaskLinkKind.SUPERSEDES
        assert task.links[1].target_id == 9

    def test_task_links_independent_between_instances(self) -> None:
        """Default mutable lists must not be shared between Task instances."""
        task_a = Task(id=1, title="a")
        task_b = Task(id=2, title="b")

        task_a.links.append(TaskLink(kind=TaskLinkKind.RELATES_TO, target_id=5))

        assert task_b.links == []


# ---------------------------------------------------------------------------
# parse_task_links
# ---------------------------------------------------------------------------


class TestParseTaskLinks:
    """Tests for the parse_task_links() function."""

    # --- Empty / plain body ---

    def test_empty_body_returns_empty_list(self) -> None:
        assert parse_task_links("") == []

    def test_plain_body_no_links(self) -> None:
        assert parse_task_links("Fix the frobnicator widget so it works.") == []

    # --- relates_to ---

    def test_relates_to_pattern_relates_to(self) -> None:
        links = parse_task_links("This relates to #12.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.RELATES_TO
        assert links[0].target_id == 12

    def test_relates_to_pattern_related(self) -> None:
        links = parse_task_links("Also related: #99")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.RELATES_TO
        assert links[0].target_id == 99

    def test_relates_to_case_insensitive(self) -> None:
        links = parse_task_links("RELATES TO #7")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.RELATES_TO

    # --- duplicates ---

    def test_duplicates_pattern_duplicates(self) -> None:
        links = parse_task_links("This duplicates #5.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.DUPLICATES
        assert links[0].target_id == 5

    def test_duplicates_pattern_duplicate_of(self) -> None:
        links = parse_task_links("duplicate of #5")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.DUPLICATES
        assert links[0].target_id == 5

    def test_duplicates_case_insensitive(self) -> None:
        links = parse_task_links("DUPLICATE OF #10")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.DUPLICATES

    # --- supersedes ---

    def test_supersedes_pattern_supersedes(self) -> None:
        links = parse_task_links("This supersedes #3.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 3

    def test_supersedes_pattern_replaces(self) -> None:
        links = parse_task_links("This replaces #3.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES
        assert links[0].target_id == 3

    def test_supersedes_case_insensitive(self) -> None:
        links = parse_task_links("REPLACES #20")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.SUPERSEDES

    # --- replies_to ---

    def test_replies_to_pattern_replies_to(self) -> None:
        links = parse_task_links("This replies to #8.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO
        assert links[0].target_id == 8

    def test_replies_to_pattern_reply_to(self) -> None:
        links = parse_task_links("reply to #8")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO
        assert links[0].target_id == 8

    def test_replies_to_pattern_in_response_to(self) -> None:
        links = parse_task_links("In response to #8, see here.")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO
        assert links[0].target_id == 8

    def test_replies_to_case_insensitive(self) -> None:
        links = parse_task_links("IN RESPONSE TO #30")

        assert len(links) == 1
        assert links[0].kind == TaskLinkKind.REPLIES_TO

    # --- Multiple links ---

    def test_multiple_links_different_targets(self) -> None:
        body = "This relates to #1 and duplicates #2 and supersedes #3."
        links = parse_task_links(body)

        target_ids = [lnk.target_id for lnk in links]
        assert 1 in target_ids
        assert 2 in target_ids
        assert 3 in target_ids
        assert len(links) == 3

    def test_multiple_links_preserve_kinds(self) -> None:
        body = "Relates to #10. Duplicate of #20."
        links = parse_task_links(body)

        by_id = {lnk.target_id: lnk for lnk in links}
        assert by_id[10].kind == TaskLinkKind.RELATES_TO
        assert by_id[20].kind == TaskLinkKind.DUPLICATES

    # --- Deduplication ---

    def test_dedup_same_target_mentioned_twice_keeps_first(self) -> None:
        body = "This relates to #5. Also duplicates #5."
        links = parse_task_links(body)

        assert len(links) == 1
        assert links[0].target_id == 5
        assert links[0].kind == TaskLinkKind.RELATES_TO

    def test_dedup_same_pattern_same_target(self) -> None:
        body = "Relates to #7 and relates to #7."
        links = parse_task_links(body)

        assert len(links) == 1
        assert links[0].target_id == 7

    # --- GitHubIssue.to_task() propagation ---

    def test_github_issue_to_task_propagates_links(self) -> None:
        issue = GitHubIssue(
            number=42,
            title="Improve widget",
            body="This relates to #10 and duplicates #20.",
        )
        task = issue.to_task()

        assert len(task.links) == 2
        target_ids = {lnk.target_id for lnk in task.links}
        assert target_ids == {10, 20}

    def test_github_issue_to_task_empty_body_no_links(self) -> None:
        issue = GitHubIssue(number=1, title="t", body="")
        task = issue.to_task()

        assert task.links == []

    def test_github_issue_to_task_plain_body_no_links(self) -> None:
        issue = GitHubIssue(number=1, title="t", body="Just a plain description.")
        task = issue.to_task()

        assert task.links == []

    # --- Round-trip via from_task ---

    def test_from_task_round_trip_preserves_links(self) -> None:
        links = [TaskLink(kind=TaskLinkKind.SUPERSEDES, target_id=3)]
        task = Task(id=42, title="t", links=links)

        reconstructed = GitHubIssue.from_task(task).to_task()

        assert (
            len(reconstructed.links) == 0
        )  # from_task body is empty → no links parsed

    def test_pydantic_serialization_round_trip(self) -> None:
        task = Task(
            id=1,
            title="t",
            links=[TaskLink(kind=TaskLinkKind.REPLIES_TO, target_id=9)],
        )
        data = task.model_dump()
        restored = Task.model_validate(data)

        assert len(restored.links) == 1
        assert restored.links[0].kind == TaskLinkKind.REPLIES_TO
        assert restored.links[0].target_id == 9


# --- DeltaReport ---


class TestDeltaReport:
    """Tests for DeltaReport properties and methods."""

    def test_has_drift_false_when_no_missing_or_unexpected(self) -> None:
        from models import DeltaReport

        report = DeltaReport(planned=["a.py"], actual=["a.py"])
        assert report.has_drift is False

    def test_has_drift_true_when_missing(self) -> None:
        from models import DeltaReport

        report = DeltaReport(
            planned=["a.py", "b.py"], actual=["a.py"], missing=["b.py"]
        )
        assert report.has_drift is True

    def test_has_drift_true_when_unexpected(self) -> None:
        from models import DeltaReport

        report = DeltaReport(
            planned=["a.py"], actual=["a.py", "c.py"], unexpected=["c.py"]
        )
        assert report.has_drift is True

    def test_has_drift_true_when_both(self) -> None:
        from models import DeltaReport

        report = DeltaReport(
            planned=["a.py", "b.py"],
            actual=["a.py", "c.py"],
            missing=["b.py"],
            unexpected=["c.py"],
        )
        assert report.has_drift is True

    def test_format_summary_no_drift(self) -> None:
        from models import DeltaReport

        report = DeltaReport(planned=["a.py"], actual=["a.py"])
        summary = report.format_summary()
        assert "No drift detected" in summary
        assert "**Planned:** 1 files" in summary
        assert "**Actual:** 1 files" in summary

    def test_format_summary_with_missing(self) -> None:
        from models import DeltaReport

        report = DeltaReport(
            planned=["a.py", "b.py"], actual=["a.py"], missing=["b.py"]
        )
        summary = report.format_summary()
        assert "**Missing**" in summary
        assert "b.py" in summary
        assert "No drift detected" not in summary

    def test_format_summary_with_unexpected(self) -> None:
        from models import DeltaReport

        report = DeltaReport(
            planned=["a.py"], actual=["a.py", "c.py"], unexpected=["c.py"]
        )
        summary = report.format_summary()
        assert "**Unexpected**" in summary
        assert "c.py" in summary


# --- AnalysisResult ---


class TestAnalysisResult:
    """Tests for AnalysisResult properties and methods."""

    def test_blocked_false_when_no_block_verdicts(self) -> None:
        from models import AnalysisSection, AnalysisVerdict

        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(name="A", verdict=AnalysisVerdict.PASS, details=[]),
                AnalysisSection(name="B", verdict=AnalysisVerdict.WARN, details=[]),
            ]
        )
        assert result.blocked is False

    def test_blocked_true_when_any_block_verdict(self) -> None:
        from models import AnalysisSection, AnalysisVerdict

        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(name="A", verdict=AnalysisVerdict.PASS, details=[]),
                AnalysisSection(
                    name="B", verdict=AnalysisVerdict.BLOCK, details=["Bad"]
                ),
            ]
        )
        assert result.blocked is True

    def test_blocked_false_when_empty_sections(self) -> None:
        result = AnalysisResultFactory.create(sections=[])
        assert result.blocked is False

    def test_format_comment_contains_section_names(self) -> None:
        from models import AnalysisSection, AnalysisVerdict

        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(
                    name="File Validation",
                    verdict=AnalysisVerdict.PASS,
                    details=["All files exist."],
                ),
            ]
        )
        comment = result.format_comment()
        assert "File Validation" in comment

    def test_format_comment_verdict_icons(self) -> None:
        from models import AnalysisSection, AnalysisVerdict

        result = AnalysisResultFactory.create(
            sections=[
                AnalysisSection(name="A", verdict=AnalysisVerdict.PASS, details=[]),
                AnalysisSection(name="B", verdict=AnalysisVerdict.WARN, details=[]),
                AnalysisSection(name="C", verdict=AnalysisVerdict.BLOCK, details=[]),
            ]
        )
        comment = result.format_comment()
        assert "\u2705 PASS" in comment
        assert "\u26a0\ufe0f WARN" in comment
        assert "\U0001f6d1 BLOCK" in comment

    def test_format_comment_footer(self) -> None:
        result = AnalysisResultFactory.create()
        comment = result.format_comment()
        assert "Generated by HydraFlow Analyzer" in comment


# --- AuditResult ---


class TestAuditResult:
    """Tests for AuditResult properties and methods."""

    def test_missing_checks_returns_missing_and_partial(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="present"),
                AuditCheckFactory.create(name="Lint", status="missing"),
                AuditCheckFactory.create(name="Tests", status="partial"),
            ]
        )
        missing = result.missing_checks
        names = [c.name for c in missing]
        assert "Lint" in names
        assert "Tests" in names
        assert "CI" not in names

    def test_missing_checks_empty_when_all_present(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="present"),
                AuditCheckFactory.create(name="Lint", status="present"),
            ]
        )
        assert result.missing_checks == []

    def test_has_critical_gaps_true_when_critical_missing(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="missing", critical=True),
            ]
        )
        assert result.has_critical_gaps is True

    def test_has_critical_gaps_false_when_critical_partial(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="partial", critical=True),
            ]
        )
        assert result.has_critical_gaps is False

    def test_has_critical_gaps_false_when_non_critical_missing(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="missing", critical=False),
            ]
        )
        assert result.has_critical_gaps is False

    def test_format_report_no_color(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="present"),
            ]
        )
        report = result.format_report(color=False)
        assert "HydraFlow Repo Audit" in report
        assert "\033[" not in report

    def test_format_report_with_color(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="present"),
            ]
        )
        report = result.format_report(color=True)
        assert "\033[" in report

    def test_format_report_with_gaps(self) -> None:
        from tests.helpers import AuditCheckFactory, AuditResultFactory

        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="Lint", status="missing"),
            ]
        )
        report = result.format_report()
        assert "Missing (1)" in report
        assert "hydraflow prep" in report


# --- MemoryType ---


class TestMemoryType:
    """Tests for MemoryType.is_actionable classmethod."""

    def test_is_actionable_knowledge_false(self) -> None:
        from models import MemoryType

        assert MemoryType.is_actionable(MemoryType.KNOWLEDGE) is False

    def test_is_actionable_config_true(self) -> None:
        from models import MemoryType

        assert MemoryType.is_actionable(MemoryType.CONFIG) is True

    def test_is_actionable_instruction_true(self) -> None:
        from models import MemoryType

        assert MemoryType.is_actionable(MemoryType.INSTRUCTION) is True

    def test_is_actionable_code_true(self) -> None:
        from models import MemoryType

        assert MemoryType.is_actionable(MemoryType.CODE) is True


# ---------------------------------------------------------------------------
# Structured Return Types
# ---------------------------------------------------------------------------


class TestPrecheckResult:
    """Tests for the PrecheckResult dataclass."""

    def test_fields_accessible_by_name(self) -> None:
        result = PrecheckResult(
            risk="low",
            confidence=0.95,
            escalate=False,
            summary="All good",
            parse_failed=False,
        )
        assert result.risk == "low"
        assert result.confidence == 0.95
        assert result.escalate is False
        assert result.summary == "All good"
        assert result.parse_failed is False

    def test_equality(self) -> None:
        a = PrecheckResult(
            risk="high",
            confidence=0.3,
            escalate=True,
            summary="Bad",
            parse_failed=False,
        )
        b = PrecheckResult(
            risk="high",
            confidence=0.3,
            escalate=True,
            summary="Bad",
            parse_failed=False,
        )
        assert a == b

    def test_not_iterable(self) -> None:
        result = PrecheckResult(
            risk="low", confidence=0.5, escalate=False, summary="", parse_failed=False
        )
        with pytest.raises(TypeError):
            list(result)  # type: ignore[call-overload]

    def test_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        result = PrecheckResult(
            risk="low", confidence=0.5, escalate=False, summary="", parse_failed=False
        )
        with pytest.raises(FrozenInstanceError):
            result.risk = "high"  # type: ignore[misc]


class TestConflictResolutionResult:
    """Tests for the ConflictResolutionResult dataclass."""

    def test_fields_accessible_by_name(self) -> None:
        result = ConflictResolutionResult(success=True, used_rebuild=False)
        assert result.success is True
        assert result.used_rebuild is False

    def test_equality(self) -> None:
        a = ConflictResolutionResult(success=True, used_rebuild=False)
        b = ConflictResolutionResult(success=True, used_rebuild=False)
        assert a == b

    def test_inequality(self) -> None:
        a = ConflictResolutionResult(success=True, used_rebuild=False)
        b = ConflictResolutionResult(success=False, used_rebuild=False)
        assert a != b

    def test_not_iterable(self) -> None:
        result = ConflictResolutionResult(success=True, used_rebuild=False)
        with pytest.raises(TypeError):
            list(result)  # type: ignore[call-overload]

    def test_is_immutable(self) -> None:
        from dataclasses import FrozenInstanceError

        result = ConflictResolutionResult(success=True, used_rebuild=False)
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]


class TestPlanAccuracyResult:
    """Tests for the PlanAccuracyResult NamedTuple."""

    def test_supports_positional_unpacking(self) -> None:
        accuracy, unplanned, missed = PlanAccuracyResult(1.0, [], [])
        assert accuracy == 1.0
        assert unplanned == []
        assert missed == []

    def test_supports_named_access(self) -> None:
        result = PlanAccuracyResult(accuracy=75.0, unplanned=["a.py"], missed=["b.py"])
        assert result.accuracy == 75.0
        assert result.unplanned == ["a.py"]
        assert result.missed == ["b.py"]


class TestPRInfoExtract:
    """Tests for the PRInfoExtract NamedTuple."""

    def test_supports_positional_unpacking(self) -> None:
        pr_number, url, branch = PRInfoExtract(42, "https://example.com", "fix/42")
        assert pr_number == 42
        assert url == "https://example.com"
        assert branch == "fix/42"

    def test_none_pr_number(self) -> None:
        result = PRInfoExtract(pr_number=None, url="", branch="")
        assert result.pr_number is None


class TestManifestRefreshResult:
    """Tests for the ManifestRefreshResult NamedTuple."""

    def test_supports_positional_unpacking(self) -> None:
        content, digest_hash = ManifestRefreshResult("content", "abc123")
        assert content == "content"
        assert digest_hash == "abc123"


class TestInstructionsQualityResult:
    """Tests for the InstructionsQualityResult NamedTuple."""

    def test_supports_positional_unpacking(self) -> None:
        quality, feedback = InstructionsQualityResult(
            InstructionsQuality.READY, "Looks good"
        )
        assert quality == InstructionsQuality.READY
        assert feedback == "Looks good"


class TestParsedCriteria:
    """Tests for the ParsedCriteria NamedTuple."""

    def test_supports_positional_unpacking(self) -> None:
        criteria_list, instructions_text = ParsedCriteria(["AC-1"], "Step 1")
        assert criteria_list == ["AC-1"]
        assert instructions_text == "Step 1"


# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------


class TestUrlValidation:
    """Tests for HttpUrl validation on URL fields."""

    def test_valid_https_url_accepted_on_github_issue(self) -> None:
        issue = GitHubIssue(
            number=1, title="t", url="https://github.com/org/repo/issues/1"
        )
        assert issue.url == "https://github.com/org/repo/issues/1"

    def test_valid_http_url_accepted(self) -> None:
        issue = GitHubIssue(number=1, title="t", url="http://example.com")
        assert issue.url == "http://example.com"

    def test_empty_string_accepted(self) -> None:
        issue = GitHubIssue(number=1, title="t")
        assert issue.url == ""

    def test_invalid_url_plain_string_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            GitHubIssue(number=1, title="t", url="not-a-url")

    def test_invalid_url_missing_scheme_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            GitHubIssue(number=1, title="t", url="github.com/org/repo")

    def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            GitHubIssue(number=1, title="t", url="ftp://example.com/file")

    def test_url_validation_on_pr_info(self) -> None:
        pr = PRInfo(
            number=1, issue_number=42, branch="main", url="https://github.com/pr/1"
        )
        assert pr.url == "https://github.com/pr/1"

    def test_pr_info_rejects_invalid_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            PRInfo(number=1, issue_number=42, branch="main", url="bad-url")

    def test_url_validation_on_hitl_item_issue_url(self) -> None:
        item = HITLItem(issue=1, issueUrl="https://github.com/issues/1")
        assert item.issueUrl == "https://github.com/issues/1"

    def test_hitl_item_rejects_invalid_issue_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            HITLItem(issue=1, issueUrl="bad-url")

    def test_hitl_item_rejects_invalid_pr_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            HITLItem(issue=1, prUrl="bad-url")

    def test_url_validation_on_pipeline_issue(self) -> None:
        pi = PipelineIssue(issue_number=1, url="https://example.com")
        assert pi.url == "https://example.com"

    def test_pipeline_issue_rejects_invalid_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            PipelineIssue(issue_number=1, url="bad")

    def test_url_validation_on_pr_list_item(self) -> None:
        item = PRListItem(pr=1, url="https://github.com/pr/1")
        assert item.url == "https://github.com/pr/1"

    def test_pr_list_item_rejects_invalid_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            PRListItem(pr=1, url="bad")

    def test_url_validation_on_intent_response(self) -> None:
        resp = IntentResponse(issue_number=1, title="t", url="https://example.com")
        assert resp.url == "https://example.com"

    def test_url_validation_on_issue_timeline(self) -> None:
        tl = IssueTimeline(issue_number=1, pr_url="https://github.com/pr/1")
        assert tl.pr_url == "https://github.com/pr/1"

    def test_issue_timeline_rejects_invalid_pr_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            IssueTimeline(issue_number=1, pr_url="bad")


# ---------------------------------------------------------------------------
# MetricsSnapshot Rate Bounds
# ---------------------------------------------------------------------------


class TestMetricsSnapshotRateBounds:
    """Tests for MetricsSnapshot rate field constraints."""

    def test_valid_zero_rates_accepted(self) -> None:
        snap = MetricsSnapshot(timestamp="2026-01-01T00:00:00+00:00")
        assert snap.merge_rate == 0.0
        assert snap.first_pass_approval_rate == 0.0

    def test_valid_mid_range_rates_accepted(self) -> None:
        snap = MetricsSnapshot(
            timestamp="2026-01-01T00:00:00+00:00",
            merge_rate=0.5,
            quality_fix_rate=0.8,
            first_pass_approval_rate=0.75,
            avg_implementation_seconds=120.0,
        )
        assert snap.merge_rate == 0.5
        assert snap.first_pass_approval_rate == 0.75

    def test_negative_merge_rate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            MetricsSnapshot(timestamp="2026-01-01T00:00:00+00:00", merge_rate=-0.1)

    def test_negative_avg_implementation_seconds_rejected(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            MetricsSnapshot(
                timestamp="2026-01-01T00:00:00+00:00", avg_implementation_seconds=-1.0
            )

    def test_quality_fix_rate_above_one_accepted(self) -> None:
        snap = MetricsSnapshot(
            timestamp="2026-01-01T00:00:00+00:00", quality_fix_rate=2.5
        )
        assert snap.quality_fix_rate == 2.5

    def test_hitl_escalation_rate_above_one_accepted(self) -> None:
        snap = MetricsSnapshot(
            timestamp="2026-01-01T00:00:00+00:00", hitl_escalation_rate=1.5
        )
        assert snap.hitl_escalation_rate == 1.5

    def test_first_pass_approval_rate_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError, match="less than or equal to 1"):
            MetricsSnapshot(
                timestamp="2026-01-01T00:00:00+00:00", first_pass_approval_rate=1.01
            )

    def test_first_pass_approval_rate_exactly_one_accepted(self) -> None:
        snap = MetricsSnapshot(
            timestamp="2026-01-01T00:00:00+00:00", first_pass_approval_rate=1.0
        )
        assert snap.first_pass_approval_rate == 1.0


# ---------------------------------------------------------------------------
# ISO Timestamp Validation
# ---------------------------------------------------------------------------


class TestIsoTimestampValidation:
    """Tests for IsoTimestamp validation on timestamp fields."""

    def test_valid_iso_with_timezone_accepted(self) -> None:
        vc = VerificationCriteria(
            issue_number=1,
            pr_number=1,
            acceptance_criteria="AC",
            verification_instructions="VI",
            timestamp="2026-01-01T12:00:00+00:00",
        )
        assert vc.timestamp == "2026-01-01T12:00:00+00:00"

    def test_valid_iso_without_microseconds_accepted(self) -> None:
        snap = MetricsSnapshot(timestamp="2026-01-01T00:00:00")
        assert snap.timestamp == "2026-01-01T00:00:00"

    def test_valid_iso_with_z_suffix_accepted(self) -> None:
        snap = MetricsSnapshot(timestamp="2026-01-01T00:00:00Z")
        assert snap.timestamp == "2026-01-01T00:00:00Z"

    def test_malformed_timestamp_rejected_on_verification_criteria(self) -> None:
        with pytest.raises(ValidationError, match="Invalid ISO 8601 timestamp"):
            VerificationCriteria(
                issue_number=1,
                pr_number=1,
                acceptance_criteria="AC",
                verification_instructions="VI",
                timestamp="not-a-timestamp",
            )

    def test_malformed_timestamp_rejected_on_metrics_snapshot(self) -> None:
        with pytest.raises(ValidationError, match="Invalid ISO 8601 timestamp"):
            MetricsSnapshot(timestamp="yesterday")

    def test_date_only_iso_accepted(self) -> None:
        snap = MetricsSnapshot(timestamp="2026-01-01")
        assert snap.timestamp == "2026-01-01"


# ---------------------------------------------------------------------------
# Frozen Model Config
# ---------------------------------------------------------------------------


class TestFrozenModelConfig:
    """Tests for frozen model_config on immutable models."""

    def test_pipeline_issue_rejects_attribute_assignment(self) -> None:
        pi = PipelineIssue(issue_number=1, title="t")
        with pytest.raises(ValidationError):
            pi.title = "new title"

    def test_background_worker_status_rejects_attribute_assignment(self) -> None:
        bws = BackgroundWorkerStatus(name="test", label="Test Worker")
        with pytest.raises(ValidationError):
            bws.status = "ok"


# ---------------------------------------------------------------------------
# StrEnum parametrized tests
# ---------------------------------------------------------------------------


class TestPipelineStageEnum:
    """Tests for the PipelineStage StrEnum."""

    @pytest.mark.parametrize(
        "member, expected",
        [
            (PipelineStage.TRIAGE, "triage"),
            (PipelineStage.PLAN, "plan"),
            (PipelineStage.IMPLEMENT, "implement"),
            (PipelineStage.REVIEW, "review"),
            (PipelineStage.MERGE, "merge"),
        ],
        ids=[m.name for m in PipelineStage],
    )
    def test_member_values(self, member: PipelineStage, expected: str) -> None:
        assert member == expected

    def test_member_count(self) -> None:
        assert len(PipelineStage) == 5


class TestStageStatusEnum:
    """Tests for the StageStatus StrEnum."""

    @pytest.mark.parametrize(
        "member, expected",
        [
            (StageStatus.PENDING, "pending"),
            (StageStatus.IN_PROGRESS, "in_progress"),
            (StageStatus.DONE, "done"),
            (StageStatus.FAILED, "failed"),
        ],
        ids=[m.name for m in StageStatus],
    )
    def test_member_values(self, member: StageStatus, expected: str) -> None:
        assert member == expected

    def test_member_count(self) -> None:
        assert len(StageStatus) == 4


class TestSessionStatusEnum:
    """Tests for the SessionStatus StrEnum."""

    @pytest.mark.parametrize(
        "member, expected",
        [
            (SessionStatus.ACTIVE, "active"),
            (SessionStatus.COMPLETED, "completed"),
        ],
        ids=[m.name for m in SessionStatus],
    )
    def test_member_values(self, member: SessionStatus, expected: str) -> None:
        assert member == expected

    def test_member_count(self) -> None:
        assert len(SessionStatus) == 2


class TestPipelineIssueStatusEnum:
    """Tests for the PipelineIssueStatus StrEnum."""

    @pytest.mark.parametrize(
        "member, expected",
        [
            (PipelineIssueStatus.QUEUED, "queued"),
            (PipelineIssueStatus.ACTIVE, "active"),
            (PipelineIssueStatus.HITL, "hitl"),
        ],
        ids=[m.name for m in PipelineIssueStatus],
    )
    def test_member_values(self, member: PipelineIssueStatus, expected: str) -> None:
        assert member == expected

    def test_member_count(self) -> None:
        assert len(PipelineIssueStatus) == 3


class TestBGWorkerHealthEnum:
    """Tests for the BGWorkerHealth StrEnum."""

    @pytest.mark.parametrize(
        "member, expected",
        [
            (BGWorkerHealth.OK, "ok"),
            (BGWorkerHealth.ERROR, "error"),
            (BGWorkerHealth.DISABLED, "disabled"),
        ],
        ids=[m.name for m in BGWorkerHealth],
    )
    def test_member_values(self, member: BGWorkerHealth, expected: str) -> None:
        assert member == expected

    def test_member_count(self) -> None:
        assert len(BGWorkerHealth) == 3


# ---------------------------------------------------------------------------
# Validation rejection tests
# ---------------------------------------------------------------------------


class TestValidationRejection:
    """Tests that invalid values are rejected by Pydantic validation."""

    def test_session_log_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            SessionLog(id="x", repo="r", started_at="t", status="bogus")

    def test_pipeline_issue_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            PipelineIssue(issue_number=1, status="bogus")

    def test_bg_worker_status_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            BackgroundWorkerStatus(name="x", label="X", status="bogus")

    def test_timeline_stage_rejects_invalid_stage(self) -> None:
        with pytest.raises(ValidationError):
            TimelineStage(stage="bogus", status="pending")

    def test_timeline_stage_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            TimelineStage(stage="triage", status="bogus")

    def test_review_record_rejects_invalid_verdict(self) -> None:
        from review_insights import ReviewRecord

        with pytest.raises(ValidationError):
            ReviewRecord(
                pr_number=1,
                issue_number=1,
                timestamp="t",
                verdict="bogus",
                summary="s",
                fixes_made=False,
                categories=[],
            )

    def test_failure_record_rejects_invalid_category(self) -> None:
        from harness_insights import FailureRecord

        with pytest.raises(ValidationError):
            FailureRecord(issue_number=1, category="bogus")


# ---------------------------------------------------------------------------
# JSONL deserialization compatibility tests
# ---------------------------------------------------------------------------


class TestJSONLDeserialization:
    """Tests that models correctly deserialize from JSON strings (JSONL files)."""

    def test_failure_record_deserializes_from_json_string(self) -> None:
        from harness_insights import FailureCategory, FailureRecord

        record = FailureRecord.model_validate_json(
            '{"issue_number":1,"category":"quality_gate","stage":"plan"}'
        )
        assert record.category == FailureCategory.QUALITY_GATE
        assert record.stage == PipelineStage.PLAN

    def test_review_record_deserializes_from_json_string(self) -> None:
        from review_insights import ReviewRecord

        record = ReviewRecord.model_validate_json(
            '{"pr_number":1,"issue_number":1,"timestamp":"2024-01-01T00:00:00Z",'
            '"verdict":"approve","summary":"s","fixes_made":false,'
            '"categories":[]}'
        )
        assert record.verdict == ReviewVerdict.APPROVE


# ---------------------------------------------------------------------------
# IssueOutcomeType, IssueOutcome, HookFailureRecord
# ---------------------------------------------------------------------------


class TestIssueOutcomeModels:
    """Tests for outcome tracking models."""

    def test_issue_outcome_type_values(self) -> None:
        from models import IssueOutcomeType

        assert IssueOutcomeType.MERGED == "merged"
        assert IssueOutcomeType.ALREADY_SATISFIED == "already_satisfied"
        assert IssueOutcomeType.HITL_CLOSED == "hitl_closed"
        assert IssueOutcomeType.HITL_SKIPPED == "hitl_skipped"
        assert IssueOutcomeType.HITL_APPROVED == "hitl_approved"
        assert IssueOutcomeType.FAILED == "failed"
        assert IssueOutcomeType.MANUAL_CLOSE == "manual_close"

    def test_issue_outcome_creation(self) -> None:
        from models import IssueOutcome, IssueOutcomeType

        outcome = IssueOutcome(
            outcome=IssueOutcomeType.MERGED,
            reason="PR approved and merged",
            closed_at="2024-01-15T10:00:00Z",
            pr_number=42,
            phase="review",
        )
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.reason == "PR approved and merged"
        assert outcome.pr_number == 42
        assert outcome.phase == "review"

    def test_issue_outcome_without_pr_number(self) -> None:
        from models import IssueOutcome, IssueOutcomeType

        outcome = IssueOutcome(
            outcome=IssueOutcomeType.HITL_CLOSED,
            reason="Duplicate issue",
            closed_at="2024-01-15T10:00:00Z",
            phase="hitl",
        )
        assert outcome.pr_number is None

    def test_hook_failure_record_creation(self) -> None:
        from models import HookFailureRecord

        record = HookFailureRecord(
            hook_name="AC generation",
            error="Connection timeout",
            timestamp="2024-01-15T10:00:00Z",
        )
        assert record.hook_name == "AC generation"
        assert record.error == "Connection timeout"

    def test_hitl_close_request_requires_reason(self) -> None:
        from models import HITLCloseRequest

        with pytest.raises(ValidationError):
            HITLCloseRequest(reason="")

    def test_hitl_close_request_accepts_valid_reason(self) -> None:
        from models import HITLCloseRequest

        req = HITLCloseRequest(reason="Duplicate of #123")
        assert req.reason == "Duplicate of #123"

    def test_hitl_skip_request_requires_reason(self) -> None:
        from models import HITLSkipRequest

        with pytest.raises(ValidationError):
            HITLSkipRequest(reason="")

    def test_hitl_skip_request_accepts_valid_reason(self) -> None:
        from models import HITLSkipRequest

        req = HITLSkipRequest(reason="Not actionable")
        assert req.reason == "Not actionable"

    def test_issue_history_entry_outcome_defaults_to_none(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(issue_number=42)
        assert entry.outcome is None

    def test_issue_history_entry_outcome_can_be_set(self) -> None:
        from models import IssueHistoryEntry, IssueOutcome, IssueOutcomeType

        outcome = IssueOutcome(
            outcome=IssueOutcomeType.MERGED,
            reason="merged",
            closed_at="2024-01-15T10:00:00Z",
            pr_number=1,
            phase="review",
        )
        entry = IssueHistoryEntry(issue_number=42, outcome=outcome)
        assert entry.outcome is not None
        assert entry.outcome.outcome == IssueOutcomeType.MERGED

    def test_state_data_new_fields_default(self) -> None:
        data = StateData()
        assert data.issue_outcomes == {}
        assert data.hook_failures == {}

    def test_issue_history_link_defaults(self) -> None:
        from models import IssueHistoryLink, TaskLinkKind

        link = IssueHistoryLink(target_id=42)
        assert link.target_id == 42
        assert link.kind == TaskLinkKind.RELATES_TO
        assert link.target_url is None

    def test_issue_history_link_with_kind(self) -> None:
        from models import IssueHistoryLink, TaskLinkKind

        link = IssueHistoryLink(
            target_id=10,
            kind=TaskLinkKind.DUPLICATES,
            target_url="https://github.com/org/repo/issues/10",
        )
        assert link.target_id == 10
        assert link.kind == TaskLinkKind.DUPLICATES
        assert link.target_url == "https://github.com/org/repo/issues/10"

    def test_issue_history_link_serialization_round_trip(self) -> None:
        from models import IssueHistoryLink, TaskLinkKind

        link = IssueHistoryLink(target_id=5, kind=TaskLinkKind.SUPERSEDES)
        data = link.model_dump()
        assert data == {"target_id": 5, "kind": "supersedes", "target_url": None}
        restored = IssueHistoryLink.model_validate(data)
        assert restored == link
        assert restored.kind == TaskLinkKind.SUPERSEDES

    def test_issue_history_entry_linked_issues_accepts_history_links(self) -> None:
        from models import IssueHistoryEntry, IssueHistoryLink, TaskLinkKind

        links = [
            IssueHistoryLink(target_id=1, kind=TaskLinkKind.RELATES_TO),
            IssueHistoryLink(target_id=2, kind=TaskLinkKind.DUPLICATES),
        ]
        entry = IssueHistoryEntry(issue_number=42, linked_issues=links)
        assert len(entry.linked_issues) == 2
        assert entry.linked_issues[0].target_id == 1
        assert entry.linked_issues[1].kind == TaskLinkKind.DUPLICATES

    def test_issue_history_entry_linked_issues_defaults_empty(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(issue_number=42)
        assert entry.linked_issues == []

    def test_issue_history_entry_crate_fields_default(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(issue_number=42)
        assert entry.crate_number is None
        assert entry.crate_title == ""

    def test_issue_history_entry_crate_fields_can_be_set(self) -> None:
        from models import IssueHistoryEntry

        entry = IssueHistoryEntry(
            issue_number=42, crate_number=3, crate_title="Sprint 1"
        )
        assert entry.crate_number == 3
        assert entry.crate_title == "Sprint 1"

    def test_lifetime_stats_outcome_counters_default_zero(self) -> None:
        stats = LifetimeStats()
        assert stats.total_outcomes_merged == 0
        assert stats.total_outcomes_already_satisfied == 0
        assert stats.total_outcomes_hitl_closed == 0
        assert stats.total_outcomes_hitl_skipped == 0
        assert stats.total_outcomes_failed == 0


class TestStageStats:
    def test_defaults_all_zero(self) -> None:
        s = StageStats()
        assert s.queued == 0
        assert s.active == 0
        assert s.completed_session == 0
        assert s.completed_lifetime == 0
        assert s.worker_count == 0
        assert s.worker_cap is None

    def test_with_values(self) -> None:
        s = StageStats(
            queued=3,
            active=2,
            completed_session=10,
            completed_lifetime=50,
            worker_count=2,
            worker_cap=4,
        )
        assert s.queued == 3
        assert s.worker_cap == 4


class TestThroughputStats:
    def test_defaults_all_zero(self) -> None:
        t = ThroughputStats()
        assert t.triage == 0.0
        assert t.plan == 0.0
        assert t.implement == 0.0
        assert t.review == 0.0
        assert t.hitl == 0.0

    def test_with_values(self) -> None:
        t = ThroughputStats(triage=1.5, implement=3.0)
        assert t.triage == 1.5
        assert t.implement == 3.0


class TestPipelineStats:
    def test_minimal_creation(self) -> None:
        ps = PipelineStats(timestamp="2026-02-28T12:00:00+00:00")
        assert ps.timestamp == "2026-02-28T12:00:00+00:00"
        assert ps.stages == {}
        assert ps.uptime_seconds == 0.0

    def test_full_creation(self) -> None:
        ps = PipelineStats(
            timestamp="2026-02-28T12:00:00+00:00",
            stages={
                "triage": StageStats(queued=1, active=1, worker_count=1, worker_cap=1),
                "plan": StageStats(queued=2),
                "implement": StageStats(active=3, worker_count=2, worker_cap=2),
                "review": StageStats(completed_session=5, completed_lifetime=20),
                "hitl": StageStats(),
                "merged": StageStats(completed_session=4, completed_lifetime=15),
            },
            queue=QueueStats(queue_depth={"find": 1, "plan": 2}),
            throughput=ThroughputStats(triage=2.5, implement=1.0),
            uptime_seconds=3600.0,
        )
        assert len(ps.stages) == 6
        assert ps.stages["triage"].queued == 1
        assert ps.stages["merged"].completed_lifetime == 15
        assert ps.throughput.triage == 2.5
        assert ps.uptime_seconds == 3600.0

    def test_json_serializable(self) -> None:
        ps = PipelineStats(
            timestamp="2026-02-28T12:00:00+00:00",
            stages={"triage": StageStats(queued=1)},
            throughput=ThroughputStats(triage=1.0),
            uptime_seconds=60.0,
        )
        data = ps.model_dump()
        assert isinstance(data, dict)
        assert data["stages"]["triage"]["queued"] == 1
        assert data["throughput"]["triage"] == 1.0
        # Round-trip through JSON
        import json

        json_str = json.dumps(data)
        restored = PipelineStats.model_validate_json(json_str)
        assert restored.stages["triage"].queued == 1


# ---------------------------------------------------------------------------
# VisualEvidenceItem
# ---------------------------------------------------------------------------


class TestVisualEvidenceItem:
    """Tests for the VisualEvidenceItem model."""

    def test_minimal_instantiation(self) -> None:
        item = VisualEvidenceItem(screen_name="login", status="pass")
        assert item.screen_name == "login"
        assert item.diff_percent == 0.0
        assert item.status == "pass"

    def test_status_is_required(self) -> None:
        with pytest.raises(ValidationError):
            VisualEvidenceItem(screen_name="login")

    def test_all_fields(self) -> None:
        item = VisualEvidenceItem(
            screen_name="dashboard",
            diff_percent=12.5,
            baseline_url="https://example.com/baseline.png",
            actual_url="https://example.com/actual.png",
            diff_url="https://example.com/diff.png",
            status="warn",
        )
        assert item.screen_name == "dashboard"
        assert item.diff_percent == 12.5
        assert item.status == "warn"
        assert str(item.baseline_url) == "https://example.com/baseline.png"

    def test_status_pass(self) -> None:
        item = VisualEvidenceItem(screen_name="home", status="pass")
        assert item.status == "pass"


# ---------------------------------------------------------------------------
# VisualEvidence
# ---------------------------------------------------------------------------


class TestVisualEvidence:
    """Tests for the VisualEvidence model."""

    def test_defaults(self) -> None:
        ev = VisualEvidence()
        assert ev.items == []
        assert ev.summary == ""
        assert ev.attempt == 1

    def test_with_items(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="login", diff_percent=5.0, status="warn"
                ),
                VisualEvidenceItem(
                    screen_name="dashboard", diff_percent=20.0, status="fail"
                ),
            ],
            summary="2 screens failed visual check",
            run_url="https://ci.example.com/run/42",
            attempt=2,
        )
        assert len(ev.items) == 2
        assert ev.items[0].screen_name == "login"
        assert ev.items[1].status == "fail"
        assert ev.attempt == 2

    def test_model_dump_roundtrip(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="page", diff_percent=3.0, status="pass")
            ],
            summary="All checks passed",
        )
        data = ev.model_dump()
        restored = VisualEvidence.model_validate(data)
        assert restored.items[0].screen_name == "page"
        assert restored.summary == "All checks passed"


# ---------------------------------------------------------------------------
# HITLItem — visualEvidence field
# ---------------------------------------------------------------------------


class TestHITLItemVisualEvidence:
    """Tests for the visualEvidence field on HITLItem."""

    def test_default_is_none(self) -> None:
        item = HITLItem(issue=1)
        assert item.visualEvidence is None

    def test_with_visual_evidence(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="home", diff_percent=10.0, status="fail")
            ],
            summary="1 screen failed",
        )
        item = HITLItem(issue=1, visualEvidence=ev)
        assert item.visualEvidence is not None
        assert item.visualEvidence.items[0].screen_name == "home"

    def test_model_dump_includes_visual_evidence(self) -> None:
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="nav", diff_percent=2.0, status="warn")
            ],
        )
        item = HITLItem(issue=1, visualEvidence=ev)
        data = item.model_dump()
        assert data["visualEvidence"]["items"][0]["screen_name"] == "nav"

    def test_model_dump_excludes_none_visual_evidence(self) -> None:
        item = HITLItem(issue=1)
        data = item.model_dump()
        assert data["visualEvidence"] is None
