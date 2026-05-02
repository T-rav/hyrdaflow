"""Tests for enriched domain models and consolidated state mutations (#5923)."""

from __future__ import annotations

from pathlib import Path

import pytest

from models import EpicState, TrackedReport
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# EpicState enrichment
# ---------------------------------------------------------------------------


class TestEpicStateProgress:
    def test_empty_epic_progress(self) -> None:
        epic = EpicState(epic_number=1)
        p = epic.progress
        assert p == {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "excluded": 0,
            "approved": 0,
            "remaining": 0,
        }

    def test_progress_with_children(self) -> None:
        epic = EpicState(
            epic_number=1,
            child_issues=[10, 20, 30, 40],
            completed_children=[10],
            failed_children=[20],
            excluded_children=[30],
            approved_children=[10],
        )
        p = epic.progress
        assert p["total"] == 4
        assert p["completed"] == 1
        assert p["failed"] == 1
        assert p["excluded"] == 1
        assert p["approved"] == 1
        # remaining = not completed and not excluded (20 is failed but not resolved, 40 is active)
        assert p["remaining"] == 2

    def test_total_children(self) -> None:
        epic = EpicState(epic_number=1, child_issues=[1, 2, 3])
        assert epic.total_children == 3

    def test_resolved_children(self) -> None:
        epic = EpicState(
            epic_number=1,
            child_issues=[1, 2, 3, 4],
            completed_children=[1, 2],
            excluded_children=[3],
        )
        assert epic.resolved_children == {1, 2, 3}

    def test_remaining_children(self) -> None:
        epic = EpicState(
            epic_number=1,
            child_issues=[1, 2, 3, 4],
            completed_children=[1],
            excluded_children=[2],
        )
        assert epic.remaining_children == [3, 4]

    def test_remaining_preserves_order(self) -> None:
        epic = EpicState(
            epic_number=1,
            child_issues=[40, 10, 30, 20],
            completed_children=[10, 30],
        )
        assert epic.remaining_children == [40, 20]

    def test_is_child_resolved_completed(self) -> None:
        epic = EpicState(
            epic_number=1,
            child_issues=[1, 2],
            completed_children=[1],
        )
        assert epic.is_child_resolved(1) is True
        assert epic.is_child_resolved(2) is False

    def test_is_child_resolved_excluded(self) -> None:
        epic = EpicState(
            epic_number=1,
            child_issues=[1, 2],
            excluded_children=[2],
        )
        assert epic.is_child_resolved(2) is True

    def test_is_child_resolved_not_in_epic(self) -> None:
        epic = EpicState(epic_number=1, child_issues=[1])
        assert epic.is_child_resolved(999) is False


# ---------------------------------------------------------------------------
# TrackedReport.transition
# ---------------------------------------------------------------------------


class TestTrackedReportTransition:
    def _make_report(self, status: str = "queued") -> TrackedReport:
        report = TrackedReport(
            reporter_id="user1",
            description="bug",
            status=status,  # type: ignore[arg-type]
        )
        report.history.clear()
        return report

    def test_valid_transition_queued_to_in_progress(self) -> None:
        report = self._make_report("queued")
        report.transition("in-progress", action="processing", detail="Started")
        assert report.status == "in-progress"
        assert len(report.history) == 1
        assert report.history[0].action == "processing"
        assert report.history[0].detail == "Started"

    def test_valid_transition_in_progress_to_filed(self) -> None:
        report = self._make_report("in-progress")
        report.transition("filed", action="filed")
        assert report.status == "filed"

    def test_valid_transition_filed_to_fixed(self) -> None:
        report = self._make_report("filed")
        report.transition("fixed", action="fixed")
        assert report.status == "fixed"

    def test_valid_transition_fixed_to_closed(self) -> None:
        report = self._make_report("fixed")
        report.transition("closed", action="confirm_fixed")
        assert report.status == "closed"

    def test_valid_transition_closed_to_reopened(self) -> None:
        report = self._make_report("closed")
        report.transition("reopened", action="reopen")
        assert report.status == "reopened"

    def test_valid_transition_reopened_to_in_progress(self) -> None:
        report = self._make_report("reopened")
        report.transition("in-progress", action="processing")
        assert report.status == "in-progress"

    def test_valid_transition_in_progress_to_queued_retry(self) -> None:
        report = self._make_report("in-progress")
        report.transition("queued", action="retry", detail="Attempt 1/3 failed")
        assert report.status == "queued"

    def test_invalid_transition_queued_to_fixed(self) -> None:
        report = self._make_report("queued")
        with pytest.raises(ValueError, match="Invalid transition: queued -> fixed"):
            report.transition("fixed", action="fixed")

    def test_invalid_transition_closed_to_filed(self) -> None:
        report = self._make_report("closed")
        with pytest.raises(ValueError, match="Invalid transition: closed -> filed"):
            report.transition("filed", action="filed")

    def test_invalid_transition_fixed_to_queued(self) -> None:
        report = self._make_report("fixed")
        with pytest.raises(ValueError, match="Invalid transition: fixed -> queued"):
            report.transition("queued", action="retry")

    def test_transition_updates_timestamp(self) -> None:
        report = self._make_report("queued")
        old_updated = report.updated_at
        report.transition("in-progress", action="processing")
        assert report.updated_at >= old_updated

    def test_transition_appends_history(self) -> None:
        report = self._make_report("queued")
        report.transition("in-progress", action="processing", detail="d1")
        report.transition("filed", action="filed", detail="d2")
        assert len(report.history) == 2
        assert report.history[0].action == "processing"
        assert report.history[1].action == "filed"

    def test_transition_default_empty_detail(self) -> None:
        report = self._make_report("queued")
        report.transition("in-progress", action="processing")
        assert report.history[0].detail == ""


# ---------------------------------------------------------------------------
# StateTracker.record_successful_merge
# ---------------------------------------------------------------------------


class TestRecordSuccessfulMerge:
    def test_basic_merge_records_all_state(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        proposals = tracker.record_successful_merge(
            issue_number=42,
            pr_number=100,
        )
        assert proposals == []
        assert tracker._data.processed_issues.get("42") == "merged"
        stats = tracker.get_lifetime_stats()
        assert stats.prs_merged == 1
        assert stats.issues_completed == 1
        outcome = tracker.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome.value == "merged"
        assert outcome.pr_number == 100
        assert outcome.phase == "review"
        assert tracker.get_review_attempts(42) == 0
        assert tracker.get_issue_attempts(42) == 0
        assert tracker.get_review_feedback(42) is None

    def test_merge_with_ci_fix_attempts(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_successful_merge(
            issue_number=42,
            pr_number=100,
            ci_fix_attempts=3,
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_ci_fix_rounds == 3
        retries = tracker.get_retries_summary()
        assert retries.get("ci_fix", 0) == 3

    def test_merge_with_duration(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_successful_merge(
            issue_number=42,
            pr_number=100,
            merge_duration_seconds=120.5,
        )
        duration_stats = tracker.get_merge_duration_stats()
        assert duration_stats["avg"] == 120.5

    def test_merge_clears_existing_attempts(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Set up prior state
        tracker.increment_review_attempts(42)
        tracker.increment_review_attempts(42)
        tracker.increment_issue_attempts(42)
        tracker.set_review_feedback(42, "needs changes")
        assert tracker.get_review_attempts(42) == 2
        assert tracker.get_issue_attempts(42) == 1
        assert tracker.get_review_feedback(42) == "needs changes"

        tracker.record_successful_merge(issue_number=42, pr_number=100)

        assert tracker.get_review_attempts(42) == 0
        assert tracker.get_issue_attempts(42) == 0
        assert tracker.get_review_feedback(42) is None

    def test_merge_increments_session_counter(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_successful_merge(issue_number=42, pr_number=100)
        counters = tracker.get_session_counters()
        assert counters.merged == 1

    def test_merge_no_ci_fix_no_duration(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_successful_merge(
            issue_number=42,
            pr_number=100,
            ci_fix_attempts=0,
            merge_duration_seconds=0.0,
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_ci_fix_rounds == 0
        assert tracker.get_merge_duration_stats() == {}


# ---------------------------------------------------------------------------
# StateTracker.clear_hitl_state
# ---------------------------------------------------------------------------


class TestClearHITLState:
    def test_clears_all_hitl_data(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(42, "hydraflow-review")
        tracker.set_hitl_cause(42, "CI failure")
        tracker.set_hitl_summary(42, "Summary text")

        assert tracker.get_hitl_origin(42) == "hydraflow-review"
        assert tracker.get_hitl_cause(42) == "CI failure"
        assert tracker.get_hitl_summary(42) == "Summary text"

        tracker.clear_hitl_state(42)

        assert tracker.get_hitl_origin(42) is None
        assert tracker.get_hitl_cause(42) is None
        assert tracker.get_hitl_summary(42) is None

    def test_clears_summary_failures_too(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_summary_failure(42, "timeout")
        failed_at, error = tracker.get_hitl_summary_failure(42)
        assert error == "timeout"

        tracker.clear_hitl_state(42)

        failed_at, error = tracker.get_hitl_summary_failure(42)
        assert failed_at is None
        assert error == ""

    def test_noop_when_no_data(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Should not raise
        tracker.clear_hitl_state(999)
        assert tracker.get_hitl_origin(999) is None

    def test_does_not_affect_other_issues(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(42, "hydraflow-review")
        tracker.set_hitl_origin(43, "hydraflow-plan")

        tracker.clear_hitl_state(42)

        assert tracker.get_hitl_origin(42) is None
        assert tracker.get_hitl_origin(43) == "hydraflow-plan"
