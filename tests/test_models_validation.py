"""Tests for models — validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import (
    BackgroundWorkerStatus,
    BGWorkerHealth,
    CIStatus,
    ControlStatusResponse,
    EpicChildInfo,
    EpicChildPRState,
    EpicChildState,
    EpicChildStatus,
    EpicDetail,
    EpicProgress,
    EpicState,
    EpicStatus,
    GitHubIssue,
    HITLItem,
    HITLItemStatus,
    IntentResponse,
    IssueTimeline,
    IssueType,
    MergeStrategy,
    MetricsSnapshot,
    PipelineIssue,
    PipelineIssueStatus,
    PipelineStage,
    PRListItem,
    ReportIssueResponse,
    ReviewStatus,
    ReviewVerdict,
    SessionLog,
    SessionStatus,
    StageStatus,
    TimelineStage,
    TriageResult,
    VerificationCriteria,
)
from tests.conftest import IssueFactory, PRInfoFactory

# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------


class TestUrlValidation:
    """Tests for HttpUrl validation on URL fields."""

    def test_valid_https_url_accepted_on_github_issue(self) -> None:
        issue = IssueFactory.create(
            number=1, title="t", url="https://github.com/org/repo/issues/1"
        )
        assert issue.url == "https://github.com/org/repo/issues/1"

    def test_valid_http_url_accepted(self) -> None:
        issue = IssueFactory.create(number=1, title="t", url="http://example.com")
        assert issue.url == "http://example.com"

    def test_empty_string_accepted(self) -> None:
        issue = GitHubIssue(number=1, title="t")
        assert issue.url == ""

    def test_invalid_url_plain_string_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            IssueFactory.create(number=1, title="t", url="not-a-url")

    def test_invalid_url_missing_scheme_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            IssueFactory.create(number=1, title="t", url="github.com/org/repo")

    def test_ftp_scheme_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            IssueFactory.create(number=1, title="t", url="ftp://example.com/file")

    def test_url_validation_on_pr_info(self) -> None:
        pr = PRInfoFactory.create(
            number=1, issue_number=42, branch="main", url="https://github.com/pr/1"
        )
        assert pr.url == "https://github.com/pr/1"

    def test_pr_info_rejects_invalid_url(self) -> None:
        with pytest.raises(
            ValidationError, match="URL must be empty or start with http"
        ):
            PRInfoFactory.create(
                number=1, issue_number=42, branch="main", url="bad-url"
            )

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
# Enum Validation
# ---------------------------------------------------------------------------


class TestEnumValidation:
    """Tests enforcing Literal/StrEnum constraints."""

    def test_github_issue_rejects_invalid_state(self) -> None:
        with pytest.raises(ValidationError, match="state"):
            IssueFactory.create(number=1, title="t", state="pending")

    def test_epic_state_merge_strategy_rejects_invalid_value(self) -> None:
        with pytest.raises(ValidationError, match="merge_strategy"):
            EpicState(epic_number=1, merge_strategy="fast_track")  # type: ignore[arg-type]

    def test_epic_progress_accepts_valid_status_and_strategy(self) -> None:
        progress = EpicProgress(
            epic_number=100,
            status="completed",
            merge_strategy="ordered",
        )
        assert progress.status == EpicStatus.COMPLETED
        assert progress.merge_strategy == MergeStrategy.ORDERED

    def test_epic_progress_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            EpicProgress(epic_number=100, status="paused")  # type: ignore[arg-type]

    def test_epic_detail_rejects_invalid_merge_strategy(self) -> None:
        with pytest.raises(ValidationError, match="merge_strategy"):
            EpicDetail(epic_number=5, merge_strategy="parallel")  # type: ignore[arg-type]

    def test_epic_child_info_accepts_enum_fields(self) -> None:
        child = EpicChildInfo(
            issue_number=55,
            state="closed",
            status="done",
            pr_state="draft",
            ci_status="pending",
            review_status="approved",
        )
        assert child.state == EpicChildState.CLOSED
        assert child.status == EpicChildStatus.DONE
        assert child.pr_state == EpicChildPRState.DRAFT
        assert child.ci_status == CIStatus.PENDING
        assert child.review_status == ReviewStatus.APPROVED

    def test_epic_child_info_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            EpicChildInfo(issue_number=55, status="sleeping")  # type: ignore[arg-type]

    def test_hitl_item_rejects_invalid_status(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            HITLItem(issue=1, status="queued")  # type: ignore[arg-type]

    def test_hitl_item_accepts_all_valid_statuses(self) -> None:
        for status in (
            HITLItemStatus.PENDING,
            HITLItemStatus.PROCESSING,
            HITLItemStatus.RESOLVED,
        ):
            item = HITLItem(issue=1, status=status)
            assert item.status == status

    def test_triage_result_coerces_valid_issue_type_string(self) -> None:
        result = TriageResult(issue_number=1, issue_type="bug")
        assert result.issue_type == IssueType.BUG

    def test_triage_result_coerces_issue_type_enum_passthrough(self) -> None:
        result = TriageResult(issue_number=1, issue_type=IssueType.EPIC)
        assert result.issue_type == IssueType.EPIC

    def test_triage_result_coerces_unknown_issue_type_to_feature(self) -> None:
        result = TriageResult(issue_number=1, issue_type="unknown_type")
        assert result.issue_type == IssueType.FEATURE

    def test_intent_response_status_literal_enforced(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            IntentResponse(issue_number=1, title="t", status="queued")  # type: ignore[arg-type]

    def test_report_issue_response_status_supports_queued_and_rejects_invalid(
        self,
    ) -> None:
        response = ReportIssueResponse(issue_number=1, title="t", status="queued")
        assert response.status == "queued"
        with pytest.raises(ValidationError, match="status"):
            ReportIssueResponse(issue_number=1, title="t", status="pending")  # type: ignore[arg-type]

    def test_control_status_response_rejects_unknown_status(self) -> None:
        with pytest.raises(ValidationError, match="status"):
            ControlStatusResponse(status="paused")  # type: ignore[arg-type]


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
            (PipelineIssueStatus.PROCESSING, "processing"),
            (PipelineIssueStatus.HITL, "hitl"),
            (PipelineIssueStatus.MERGED, "merged"),
        ],
        ids=[m.name for m in PipelineIssueStatus],
    )
    def test_member_values(self, member: PipelineIssueStatus, expected: str) -> None:
        assert member == expected

    def test_member_count(self) -> None:
        assert len(PipelineIssueStatus) == 5


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
