"""Tests for dx/hydraflow/models.py."""

from __future__ import annotations

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from models import (
    BatchResult,
    ControlStatusConfig,
    ControlStatusResponse,
    GitHubIssue,
    HITLItem,
    JudgeResult,
    LifetimeStats,
    NewIssueSpec,
    Phase,
    PlannerStatus,
    PlanResult,
    PRInfo,
    PRListItem,
    ReviewerStatus,
    ReviewResult,
    ReviewVerdict,
    StateData,
    VerificationCriterion,
    WorkerResult,
    WorkerStatus,
)
from tests.conftest import ReviewResultFactory

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

    def test_minimal_instantiation(self) -> None:
        result = PlanResult(issue_number=10)
        assert result.issue_number == 10

    def test_success_defaults_to_false(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.success is False

    def test_plan_defaults_to_empty_string(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.plan == ""

    def test_summary_defaults_to_empty_string(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.summary == ""

    def test_error_defaults_to_none(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.error is None

    def test_transcript_defaults_to_empty_string(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.transcript == ""

    def test_duration_seconds_defaults_to_zero(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.duration_seconds == pytest.approx(0.0)

    def test_new_issues_defaults_to_empty_list(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.new_issues == []

    def test_new_issues_can_be_populated(self) -> None:
        spec = NewIssueSpec(title="Bug", body="Details")
        result = PlanResult(issue_number=1, new_issues=[spec])
        assert len(result.new_issues) == 1
        assert result.new_issues[0].title == "Bug"

    def test_validation_errors_defaults_to_empty_list(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.validation_errors == []

    def test_validation_errors_can_be_populated(self) -> None:
        result = PlanResult(
            issue_number=1,
            validation_errors=["Missing section", "Too short"],
        )
        assert len(result.validation_errors) == 2

    def test_retry_attempted_defaults_to_false(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.retry_attempted is False

    def test_retry_attempted_can_be_set(self) -> None:
        result = PlanResult(issue_number=1, retry_attempted=True)
        assert result.retry_attempted is True

    def test_already_satisfied_defaults_to_false(self) -> None:
        result = PlanResult(issue_number=1)
        assert result.already_satisfied is False

    def test_already_satisfied_can_be_set(self) -> None:
        result = PlanResult(issue_number=1, already_satisfied=True)
        assert result.already_satisfied is True

    def test_all_fields_set(self) -> None:
        result = PlanResult(
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
        result = PlanResult(
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

    def test_all_nine_members_present(self) -> None:
        # Assert
        assert len(WorkerStatus) == 9

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

    def test_duration_seconds_defaults_to_zero(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1)
        assert review.duration_seconds == pytest.approx(0.0)

    def test_duration_seconds_can_be_set(self) -> None:
        review = ReviewResult(pr_number=1, issue_number=1, duration_seconds=45.5)
        assert review.duration_seconds == pytest.approx(45.5)

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
            GitHubIssue(number=1, title="Issue 1"),
            GitHubIssue(number=2, title="Issue 2"),
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
        assert batch.issues[0].number == 1
        assert batch.issues[1].number == 2
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
            issues=[GitHubIssue(number=10, title="T")],
            merged_prs=[200, 201],
        )

        # Act
        data = batch.model_dump()

        # Assert
        assert data["batch_number"] == 2
        assert len(data["issues"]) == 1
        assert data["issues"][0]["number"] == 10
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

    def test_defaults(self) -> None:
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

    def test_defaults(self) -> None:
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
        }

    def test_serialization_defaults_include_new_fields(self) -> None:
        """model_dump includes cause, status, and isMemorySuggestion even with defaults."""
        item = HITLItem(issue=1)
        data = item.model_dump()
        assert data["cause"] == ""
        assert data["status"] == "pending"
        assert data["isMemorySuggestion"] is False


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

    def test_defaults(self) -> None:
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
