"""Tests for state -- counters and metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from state import StateTracker
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# New recording methods
# ---------------------------------------------------------------------------


class TestRecordingMethods:
    def test_record_quality_fix_rounds(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_quality_fix_rounds(3)
        assert tracker.get_lifetime_stats().total_quality_fix_rounds == 3

    def test_record_quality_fix_rounds_accumulates(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_quality_fix_rounds(2)
        tracker.record_quality_fix_rounds(1)
        assert tracker.get_lifetime_stats().total_quality_fix_rounds == 3

    def test_record_ci_fix_rounds(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_ci_fix_rounds(2)
        assert tracker.get_lifetime_stats().total_ci_fix_rounds == 2

    def test_record_ci_fix_rounds_accumulates(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_ci_fix_rounds(1)
        tracker.record_ci_fix_rounds(3)
        assert tracker.get_lifetime_stats().total_ci_fix_rounds == 4

    def test_record_hitl_escalation(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_hitl_escalation()
        assert tracker.get_lifetime_stats().total_hitl_escalations == 1

    def test_record_hitl_escalation_increments(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_hitl_escalation()
        tracker.record_hitl_escalation()
        assert tracker.get_lifetime_stats().total_hitl_escalations == 2

    def test_record_review_verdict_approve(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_review_verdict("approve", fixes_made=False)
        stats = tracker.get_lifetime_stats()
        assert stats.total_review_approvals == 1
        assert stats.total_review_request_changes == 0
        assert stats.total_reviewer_fixes == 0

    def test_record_review_verdict_request_changes(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_review_verdict("request-changes", fixes_made=False)
        stats = tracker.get_lifetime_stats()
        assert stats.total_review_approvals == 0
        assert stats.total_review_request_changes == 1
        assert stats.total_reviewer_fixes == 0

    def test_record_review_verdict_with_fixes(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_review_verdict("approve", fixes_made=True)
        stats = tracker.get_lifetime_stats()
        assert stats.total_review_approvals == 1
        assert stats.total_reviewer_fixes == 1

    def test_record_review_verdict_comment_does_not_affect_counts(
        self, tmp_path: Path
    ) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_review_verdict("comment", fixes_made=False)
        stats = tracker.get_lifetime_stats()
        assert stats.total_review_approvals == 0
        assert stats.total_review_request_changes == 0

    def test_record_implementation_duration(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_implementation_duration(45.5)
        assert (
            tracker.get_lifetime_stats().total_implementation_seconds
            == pytest.approx(45.5)
        )

    def test_record_implementation_duration_accumulates(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_implementation_duration(10.0)
        tracker.record_implementation_duration(20.5)
        assert (
            tracker.get_lifetime_stats().total_implementation_seconds
            == pytest.approx(30.5)
        )

    def test_record_review_duration(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_review_duration(30.0)
        assert tracker.get_lifetime_stats().total_review_seconds == pytest.approx(30.0)

    def test_record_review_duration_accumulates(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_review_duration(15.0)
        tracker.record_review_duration(25.0)
        assert tracker.get_lifetime_stats().total_review_seconds == pytest.approx(40.0)

    def test_new_stats_persist_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.record_quality_fix_rounds(2)
        tracker.record_ci_fix_rounds(1)
        tracker.record_hitl_escalation()
        tracker.record_review_verdict("approve", fixes_made=True)
        tracker.record_implementation_duration(60.0)
        tracker.record_review_duration(30.0)

        tracker2 = StateTracker(state_file)
        stats = tracker2.get_lifetime_stats()
        assert stats.total_quality_fix_rounds == 2
        assert stats.total_ci_fix_rounds == 1
        assert stats.total_hitl_escalations == 1
        assert stats.total_review_approvals == 1
        assert stats.total_reviewer_fixes == 1
        assert stats.total_implementation_seconds == pytest.approx(60.0)
        assert stats.total_review_seconds == pytest.approx(30.0)

    def test_new_stats_preserved_across_reset(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_quality_fix_rounds(3)
        tracker.record_hitl_escalation()
        tracker.record_implementation_duration(100.0)
        tracker.mark_issue(1, "success")

        tracker.reset()

        assert tracker.to_dict()["processed_issues"].get(str(1)) is None
        stats = tracker.get_lifetime_stats()
        assert stats.total_quality_fix_rounds == 3
        assert stats.total_hitl_escalations == 1
        assert stats.total_implementation_seconds == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Metrics state
# ---------------------------------------------------------------------------


class TestMetricsState:
    def test_get_metrics_state_default(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        hash_val, synced = tracker.get_metrics_state()
        assert hash_val == ""
        assert synced is None

    def test_update_metrics_state(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_metrics_state("abc123")
        hash_val, synced = tracker.get_metrics_state()
        assert hash_val == "abc123"
        assert synced is not None

    def test_metrics_state_persists_across_reloads(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_metrics_state("def456")

        tracker2 = make_tracker(tmp_path)
        hash_val, synced = tracker2.get_metrics_state()
        assert hash_val == "def456"
        assert synced is not None


# ---------------------------------------------------------------------------
# Threshold tracking
# ---------------------------------------------------------------------------


class TestThresholdTracking:
    def test_mark_threshold_fired(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_threshold_fired("quality_fix_rate")
        assert "quality_fix_rate" in tracker.get_fired_thresholds()

    def test_mark_threshold_fired_idempotent(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_threshold_fired("quality_fix_rate")
        tracker.mark_threshold_fired("quality_fix_rate")
        assert tracker.get_fired_thresholds().count("quality_fix_rate") == 1

    def test_clear_threshold_fired(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_threshold_fired("quality_fix_rate")
        tracker.clear_threshold_fired("quality_fix_rate")
        assert "quality_fix_rate" not in tracker.get_fired_thresholds()

    def test_clear_threshold_fired_noop_if_not_present(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.clear_threshold_fired("nonexistent")
        assert tracker.get_fired_thresholds() == []

    def test_fired_thresholds_persist_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_threshold_fired("quality_fix_rate")
        tracker.mark_threshold_fired("hitl_rate")

        tracker2 = StateTracker(state_file)
        fired = tracker2.get_fired_thresholds()
        assert "quality_fix_rate" in fired
        assert "hitl_rate" in fired

    def test_fired_thresholds_preserved_across_reset(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_threshold_fired("approval_rate")
        tracker.reset()
        assert "approval_rate" in tracker.get_fired_thresholds()

    def test_check_thresholds_returns_empty_below_minimum_issues(
        self, tmp_path: Path
    ) -> None:
        """Thresholds require at least 5 completed issues to activate."""
        tracker = make_tracker(tmp_path)
        for _ in range(4):
            tracker.record_issue_completed()
        tracker.record_quality_fix_rounds(10)  # high rate
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        assert proposals == []

    def test_check_thresholds_quality_fix_rate_crossed(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        for _ in range(5):
            tracker.record_issue_completed()
        tracker.record_quality_fix_rounds(4)  # rate = 4/5 = 0.8 > 0.5
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        names = [p["name"] for p in proposals]
        assert "quality_fix_rate" in names

    def test_check_thresholds_approval_rate_crossed(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        for _ in range(5):
            tracker.record_issue_completed()
        # 1 approval, 4 request-changes -> rate = 1/5 = 0.2 < 0.5
        tracker.record_review_verdict("approve", fixes_made=False)
        for _ in range(4):
            tracker.record_review_verdict("request-changes", fixes_made=False)
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        names = [p["name"] for p in proposals]
        assert "approval_rate" in names

    def test_check_thresholds_hitl_rate_crossed(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        for _ in range(5):
            tracker.record_issue_completed()
        for _ in range(2):
            tracker.record_hitl_escalation()  # rate = 2/5 = 0.4 > 0.2
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        names = [p["name"] for p in proposals]
        assert "hitl_rate" in names

    def test_check_thresholds_does_not_re_fire(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        for _ in range(5):
            tracker.record_issue_completed()
        tracker.record_quality_fix_rounds(4)
        proposals1 = tracker.check_thresholds(0.5, 0.5, 0.2)
        assert len(proposals1) == 1
        tracker.mark_threshold_fired("quality_fix_rate")
        proposals2 = tracker.check_thresholds(0.5, 0.5, 0.2)
        assert not any(p["name"] == "quality_fix_rate" for p in proposals2)

    def test_check_thresholds_clears_recovered(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_threshold_fired("quality_fix_rate")
        for _ in range(5):
            tracker.record_issue_completed()
        # rate = 0/5 = 0.0 < 0.5 -> recovered
        tracker.check_thresholds(0.5, 0.5, 0.2)
        assert "quality_fix_rate" not in tracker.get_fired_thresholds()

    def test_check_thresholds_no_issues_returns_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        assert proposals == []

    def test_check_thresholds_all_three_crossed(self, tmp_path: Path) -> None:
        """All three thresholds can fire simultaneously."""
        tracker = make_tracker(tmp_path)
        for _ in range(5):
            tracker.record_issue_completed()
        tracker.record_quality_fix_rounds(4)  # qf rate 0.8 > 0.5
        for _ in range(4):
            tracker.record_review_verdict("request-changes", fixes_made=False)
        tracker.record_review_verdict("approve", fixes_made=False)  # approval 0.2 < 0.5
        for _ in range(2):
            tracker.record_hitl_escalation()  # hitl 0.4 > 0.2
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        names = {p["name"] for p in proposals}
        assert names == {"quality_fix_rate", "approval_rate", "hitl_rate"}

    def test_check_thresholds_returns_correct_values(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        for _ in range(10):
            tracker.record_issue_completed()
        tracker.record_quality_fix_rounds(8)  # rate = 0.8
        proposals = tracker.check_thresholds(0.5, 0.5, 0.2)
        qf_proposal = next(p for p in proposals if p["name"] == "quality_fix_rate")
        assert qf_proposal["threshold"] == 0.5
        assert qf_proposal["value"] == pytest.approx(0.8)
        assert "action" in qf_proposal


# ---------------------------------------------------------------------------
# Verification Issue Tracking
# ---------------------------------------------------------------------------


class TestVerificationIssueTracking:
    def test_set_and_get_verification_issue(self, tmp_path: Path) -> None:
        """Round-trip: set then get returns the verification issue number."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(42, 500)
        assert tracker.get_verification_issue(42) == 500

    def test_get_returns_none_when_not_set(self, tmp_path: Path) -> None:
        """Returns None when no verification issue is tracked."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_verification_issue(42) is None

    def test_persists_across_reload(self, tmp_path: Path) -> None:
        """Verification issue mapping survives reload from disk."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(42, 500)

        tracker2 = make_tracker(tmp_path)
        assert tracker2.get_verification_issue(42) == 500

    def test_multiple_issues_tracked(self, tmp_path: Path) -> None:
        """Multiple original issues can each have verification issues."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(42, 500)
        tracker.set_verification_issue(99, 501)

        assert tracker.get_verification_issue(42) == 500
        assert tracker.get_verification_issue(99) == 501

    def test_clear_verification_issue_removes_entry(self, tmp_path: Path) -> None:
        """clear_verification_issue removes the mapping for the given issue."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(42, 500)
        tracker.clear_verification_issue(42)
        assert tracker.get_verification_issue(42) is None

    def test_clear_verification_issue_no_op_when_absent(self, tmp_path: Path) -> None:
        """clear_verification_issue is a no-op when the issue has no mapping."""
        tracker = make_tracker(tmp_path)
        tracker.clear_verification_issue(99)  # should not raise
        assert tracker.get_verification_issue(99) is None

    def test_clear_verification_issue_persists(self, tmp_path: Path) -> None:
        """Cleared mapping is not present after reload."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(42, 500)
        tracker.clear_verification_issue(42)

        tracker2 = make_tracker(tmp_path)
        assert tracker2.get_verification_issue(42) is None

    def test_get_all_verification_issues_returns_all(self, tmp_path: Path) -> None:
        """get_all_verification_issues returns all pending mappings."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(10, 100)
        tracker.set_verification_issue(20, 200)
        result = tracker.get_all_verification_issues()
        assert result == {10: 100, 20: 200}

    def test_get_all_verification_issues_empty(self, tmp_path: Path) -> None:
        """Returns empty dict when no verification issues are tracked."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_all_verification_issues() == {}

    def test_get_all_verification_issues_after_clear(self, tmp_path: Path) -> None:
        """Cleared entries are absent from get_all_verification_issues."""
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(10, 100)
        tracker.set_verification_issue(20, 200)
        tracker.clear_verification_issue(10)
        result = tracker.get_all_verification_issues()
        assert result == {20: 200}


# ---------------------------------------------------------------------------
# Issue attempt tracking
# ---------------------------------------------------------------------------


class TestIssueAttemptTracking:
    def test_get_issue_attempts_defaults_to_zero(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_issue_attempts(42) == 0

    def test_increment_issue_attempts_returns_new_count(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.increment_issue_attempts(42) == 1
        assert tracker.increment_issue_attempts(42) == 2

    def test_reset_issue_attempts_clears_counter(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_issue_attempts(42)
        tracker.increment_issue_attempts(42)
        tracker.reset_issue_attempts(42)
        assert tracker.get_issue_attempts(42) == 0

    def test_reset_issue_attempts_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.reset_issue_attempts(999)
        assert tracker.get_issue_attempts(999) == 0

    def test_multiple_issues_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_issue_attempts(1)
        tracker.increment_issue_attempts(1)
        tracker.increment_issue_attempts(2)
        assert tracker.get_issue_attempts(1) == 2
        assert tracker.get_issue_attempts(2) == 1

    def test_issue_attempts_persist_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.increment_issue_attempts(42)
        tracker.increment_issue_attempts(42)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_issue_attempts(42) == 2

    def test_reset_clears_issue_attempts(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_issue_attempts(42)
        tracker.reset()
        assert tracker.get_issue_attempts(42) == 0

    def test_migration_adds_issue_attempts_to_old_file(self, tmp_path: Path) -> None:
        """Loading a state file without issue_attempts should default to {}."""
        state_file = tmp_path / "state.json"
        old_data = {
            "processed_issues": {"1": "success"},
            "active_workspaces": {},
            "active_branches": {},
            "reviewed_prs": {},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(old_data))

        tracker = StateTracker(state_file)
        assert tracker.get_issue_attempts(1) == 0
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"


# ---------------------------------------------------------------------------
# Active issue numbers tracking
# ---------------------------------------------------------------------------


class TestActiveIssueNumbersTracking:
    def test_get_returns_empty_default(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_active_issue_numbers() == []

    def test_set_and_get_active_issues(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_active_issue_numbers([1, 2, 3])
        assert tracker.get_active_issue_numbers() == [1, 2, 3]

    def test_set_overwrites_previous(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_active_issue_numbers([1, 2])
        tracker.set_active_issue_numbers([3, 4])
        assert tracker.get_active_issue_numbers() == [3, 4]

    def test_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_active_issue_numbers([10, 20])

        tracker2 = StateTracker(state_file)
        assert tracker2.get_active_issue_numbers() == [10, 20]

    def test_reset_clears_active_issues(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_active_issue_numbers([1, 2])
        tracker.reset()
        assert tracker.get_active_issue_numbers() == []

    def test_get_returns_copy(self, tmp_path: Path) -> None:
        """Mutating the returned list must not affect internal state."""
        tracker = make_tracker(tmp_path)
        tracker.set_active_issue_numbers([1, 2])
        result = tracker.get_active_issue_numbers()
        result.append(99)
        assert tracker.get_active_issue_numbers() == [1, 2]

    def test_migration_adds_active_issue_numbers_to_old_file(
        self, tmp_path: Path
    ) -> None:
        """Loading a state file without active_issue_numbers should default to []."""
        state_file = tmp_path / "state.json"
        old_data = {
            "processed_issues": {"1": "success"},
            "active_workspaces": {},
            "active_branches": {},
            "reviewed_prs": {},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(old_data))

        tracker = StateTracker(state_file)
        assert tracker.get_active_issue_numbers() == []
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"


class TestWorkerIntervals:
    def test_get_returns_empty_dict_initially(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_worker_intervals() == {}

    def test_set_and_get_round_trip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worker_intervals({"memory_sync": 1800, "metrics": 7200})
        assert tracker.get_worker_intervals() == {"memory_sync": 1800, "metrics": 7200}

    def test_persists_across_instances(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker1 = StateTracker(state_file)
        tracker1.set_worker_intervals({"memory_sync": 3600})

        tracker2 = StateTracker(state_file)
        assert tracker2.get_worker_intervals() == {"memory_sync": 3600}

    def test_get_returns_copy(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worker_intervals({"memory_sync": 1800})
        result1 = tracker.get_worker_intervals()
        result2 = tracker.get_worker_intervals()
        assert result1 == result2
        assert result1 is not result2


# ---------------------------------------------------------------------------
# Time-to-Merge Tracking
# ---------------------------------------------------------------------------


class TestMergeDurationTracking:
    def test_record_merge_duration_stores_value(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_merge_duration(3600.5)
        stats = tracker.get_lifetime_stats()
        assert 3600.5 in stats.merge_durations

    def test_get_merge_duration_stats_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_merge_duration_stats() == {}

    def test_get_merge_duration_stats_computes_percentiles(
        self, tmp_path: Path
    ) -> None:
        tracker = make_tracker(tmp_path)
        durations = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        for d in durations:
            tracker.record_merge_duration(float(d))
        stats = tracker.get_merge_duration_stats()
        assert stats["avg"] == 550.0
        assert stats["p50"] == 600.0  # median of 10 items
        assert stats["p90"] == 1000.0  # 90th percentile

    def test_merge_durations_persist(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_merge_duration(42.0)
        tracker2 = StateTracker(tracker._path)
        assert 42.0 in tracker2.get_lifetime_stats().merge_durations


# ---------------------------------------------------------------------------
# Retries Per Stage
# ---------------------------------------------------------------------------


class TestRetriesPerStage:
    def test_record_stage_retry_increments(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_stage_retry(42, "quality_fix")
        tracker.record_stage_retry(42, "quality_fix")
        tracker.record_stage_retry(42, "ci_fix")
        summary = tracker.get_retries_summary()
        assert summary["quality_fix"] == 2
        assert summary["ci_fix"] == 1

    def test_get_retries_summary_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_retries_summary() == {}

    def test_retries_across_issues(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_stage_retry(1, "quality_fix")
        tracker.record_stage_retry(2, "quality_fix")
        tracker.record_stage_retry(2, "ci_fix")
        summary = tracker.get_retries_summary()
        assert summary["quality_fix"] == 2
        assert summary["ci_fix"] == 1

    def test_retries_persist(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_stage_retry(42, "quality_fix")
        tracker2 = StateTracker(tracker._path)
        assert tracker2.get_retries_summary() == {"quality_fix": 1}


# ---------------------------------------------------------------------------
# Last reviewed SHA tracking (issue #853)
# ---------------------------------------------------------------------------


class TestLastReviewedSha:
    def test_set_and_get(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_last_reviewed_sha(42, "abc123def456")
        assert tracker.get_last_reviewed_sha(42) == "abc123def456"

    def test_get_returns_none_when_unset(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_last_reviewed_sha(999) is None

    def test_clear_removes_entry(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_last_reviewed_sha(42, "abc123")
        tracker.clear_last_reviewed_sha(42)
        assert tracker.get_last_reviewed_sha(42) is None

    def test_clear_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Should not raise
        tracker.clear_last_reviewed_sha(999)
        assert tracker.get_last_reviewed_sha(999) is None

    def test_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_last_reviewed_sha(42, "deadbeef1234")

        tracker2 = StateTracker(state_file)
        assert tracker2.get_last_reviewed_sha(42) == "deadbeef1234"

    def test_overwrite_updates(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_last_reviewed_sha(42, "sha-v1")
        tracker.set_last_reviewed_sha(42, "sha-v2")
        assert tracker.get_last_reviewed_sha(42) == "sha-v2"

    def test_multiple_issues_independent(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_last_reviewed_sha(1, "sha-issue-1")
        tracker.set_last_reviewed_sha(2, "sha-issue-2")
        assert tracker.get_last_reviewed_sha(1) == "sha-issue-1"
        assert tracker.get_last_reviewed_sha(2) == "sha-issue-2"
