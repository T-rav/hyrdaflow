"""Tests for state -- outcomes and worker management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from state import StateTracker
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# Issue Outcome Tracking
# ---------------------------------------------------------------------------


class TestIssueOutcomeTracking:
    """Tests for record_outcome/get_outcome/get_all_outcomes."""

    def test_record_and_get_outcome(self, tmp_path: Path) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            42, IssueOutcomeType.MERGED, "PR merged", pr_number=10, phase="review"
        )
        outcome = tracker.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.reason == "PR merged"
        assert outcome.pr_number == 10
        assert outcome.phase == "review"
        assert outcome.closed_at  # should be an ISO timestamp

    def test_get_outcome_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_outcome(999) is None

    def test_get_all_outcomes(self, tmp_path: Path) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MERGED, "merged", phase="review")
        tracker.record_outcome(2, IssueOutcomeType.FAILED, "failed", phase="plan")
        outcomes = tracker.get_all_outcomes()
        assert len(outcomes) == 2
        assert "1" in outcomes
        assert "2" in outcomes

    def test_record_outcome_increments_lifetime_counter_merged(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MERGED, "merged", phase="review")
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_merged == 1

    def test_record_outcome_increments_lifetime_counter_already_satisfied(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            1, IssueOutcomeType.ALREADY_SATISFIED, "already done", phase="plan"
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_already_satisfied == 1

    def test_record_outcome_increments_lifetime_counter_hitl_closed(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.HITL_CLOSED, "dup", phase="hitl")
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_hitl_closed == 1

    def test_record_outcome_increments_lifetime_counter_hitl_skipped(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            1, IssueOutcomeType.HITL_SKIPPED, "not needed", phase="hitl"
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_hitl_skipped == 1

    def test_record_outcome_increments_lifetime_counter_failed(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.FAILED, "error", phase="plan")
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_failed == 1

    def test_record_outcome_manual_close_increments_counter(
        self, tmp_path: Path
    ) -> None:
        """MANUAL_CLOSE should increment total_outcomes_manual_close."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MANUAL_CLOSE, "manual", phase="hitl")
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_manual_close == 1
        assert stats.total_outcomes_merged == 0

    def test_record_outcome_hitl_approved_increments_counter(
        self, tmp_path: Path
    ) -> None:
        """HITL_APPROVED should increment total_outcomes_hitl_approved."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            1, IssueOutcomeType.HITL_APPROVED, "approved", phase="hitl"
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_hitl_approved == 1
        assert stats.total_outcomes_merged == 0

    def test_outcome_persists_across_reload(self, tmp_path: Path) -> None:
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            42, IssueOutcomeType.MERGED, "merged", pr_number=5, phase="review"
        )

        tracker2 = make_tracker(tmp_path)
        outcome = tracker2.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.pr_number == 5

    def test_overwrite_outcome_corrects_counters(self, tmp_path: Path) -> None:
        """Recording a second outcome for the same issue should decrement the
        old counter and increment the new one, keeping stats consistent."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            42, IssueOutcomeType.ALREADY_SATISFIED, "thought done", phase="plan"
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_already_satisfied == 1
        assert stats.total_outcomes_merged == 0

        # Overwrite with a different outcome
        tracker.record_outcome(
            42, IssueOutcomeType.MERGED, "actually merged", pr_number=7, phase="review"
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_already_satisfied == 0
        assert stats.total_outcomes_merged == 1

        # Only latest outcome stored
        outcome = tracker.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome == IssueOutcomeType.MERGED

    def test_record_outcome_verify_pending_increments_counter(
        self, tmp_path: Path
    ) -> None:
        """VERIFY_PENDING should increment total_outcomes_verify_pending."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            1,
            IssueOutcomeType.VERIFY_PENDING,
            "verification issue created",
            pr_number=10,
            phase="review",
            verification_issue_number=50,
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_verify_pending == 1

    def test_record_outcome_stores_verification_issue_number(
        self, tmp_path: Path
    ) -> None:
        """record_outcome should persist verification_issue_number on the outcome."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            42,
            IssueOutcomeType.VERIFY_PENDING,
            "verify",
            pr_number=5,
            phase="review",
            verification_issue_number=99,
        )
        outcome = tracker.get_outcome(42)
        assert outcome is not None
        assert outcome.verification_issue_number == 99

    def test_record_outcome_verify_resolved_increments_counter(
        self, tmp_path: Path
    ) -> None:
        """VERIFY_RESOLVED should increment total_outcomes_verify_resolved."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            1,
            IssueOutcomeType.VERIFY_RESOLVED,
            "verification issue closed",
            phase="verify",
            verification_issue_number=50,
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_verify_resolved == 1

    def test_verify_pending_transitions_to_resolved(self, tmp_path: Path) -> None:
        """Overwriting VERIFY_PENDING with VERIFY_RESOLVED corrects counters."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            42,
            IssueOutcomeType.VERIFY_PENDING,
            "pending",
            phase="review",
            verification_issue_number=99,
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_verify_pending == 1
        assert stats.total_outcomes_verify_resolved == 0

        tracker.record_outcome(
            42,
            IssueOutcomeType.VERIFY_RESOLVED,
            "resolved",
            phase="verify",
            verification_issue_number=99,
        )
        stats = tracker.get_lifetime_stats()
        assert stats.total_outcomes_verify_pending == 0
        assert stats.total_outcomes_verify_resolved == 1


# ---------------------------------------------------------------------------
# Hook Failure Tracking
# ---------------------------------------------------------------------------


class TestHookFailureTracking:
    """Tests for record_hook_failure/get_hook_failures."""

    def test_record_and_get_hook_failure(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "AC generation", "Connection timeout")
        failures = tracker.get_hook_failures(42)
        assert len(failures) == 1
        assert failures[0].hook_name == "AC generation"
        assert failures[0].error == "Connection timeout"
        assert failures[0].timestamp  # should be an ISO timestamp

    def test_multiple_failures_for_same_issue(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "AC generation", "timeout")
        tracker.record_hook_failure(42, "retrospective", "network error")
        failures = tracker.get_hook_failures(42)
        assert len(failures) == 2

    def test_get_hook_failures_returns_empty_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_hook_failures(999) == []

    def test_hook_failure_error_truncated(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        long_error = "x" * 1000
        tracker.record_hook_failure(42, "hook", long_error)
        failures = tracker.get_hook_failures(42)
        assert len(failures[0].error) <= 500

    def test_hook_failures_persist_across_reload(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "hook", "error")

        tracker2 = make_tracker(tmp_path)
        failures = tracker2.get_hook_failures(42)
        assert len(failures) == 1

    def test_record_hook_failure_caps_at_500(self, tmp_path: Path) -> None:
        """Adding more than 500 failures should trim oldest entries."""
        tracker = make_tracker(tmp_path)
        for i in range(501):
            tracker.record_hook_failure(42, "hook", f"error-{i}")
        failures = tracker.get_hook_failures(42)
        assert len(failures) == 500
        # Oldest entry (error-0) should be trimmed, newest (error-500) kept
        assert failures[-1].error == "error-500"
        assert failures[0].error == "error-1"

    def test_record_hook_failure_appends(self, tmp_path: Path) -> None:
        """Multiple failures should accumulate for the same issue."""
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "hook_a", "first")
        tracker.record_hook_failure(42, "hook_b", "second")
        failures = tracker.get_hook_failures(42)
        assert len(failures) == 2
        assert failures[0].hook_name == "hook_a"
        assert failures[1].hook_name == "hook_b"

    def test_hook_failure_fields_round_trip(self, tmp_path: Path) -> None:
        """All HookFailureRecord fields should survive store and retrieval."""
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "AC generation", "Connection timeout")
        failures = tracker.get_hook_failures(42)
        assert len(failures) == 1
        assert failures[0].hook_name == "AC generation"
        assert failures[0].error == "Connection timeout"
        assert failures[0].timestamp  # non-empty ISO timestamp

    def test_get_hook_failures_returns_deep_copy(self, tmp_path: Path) -> None:
        """Mutating the returned list should not affect internal state."""
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "hook", "error")
        failures = tracker.get_hook_failures(42)
        failures.append(failures[0])  # mutate the returned list
        assert len(tracker.get_hook_failures(42)) == 1  # internal unchanged

    def test_reset_clears_hook_failures(self, tmp_path: Path) -> None:
        """reset() should clear all hook failure records."""
        tracker = make_tracker(tmp_path)
        tracker.record_hook_failure(42, "hook", "error")
        tracker.reset()
        assert tracker.get_hook_failures(42) == []


# ---------------------------------------------------------------------------
# Outcome tracking -- additional coverage
# ---------------------------------------------------------------------------


class TestOutcomeTrackingAdditional:
    """Additional tests for record_outcome/get_all_outcomes."""

    def test_record_outcome_unknown_type_skips_counter(self, tmp_path: Path) -> None:
        """An outcome type not in counter_map should not crash."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        # All known types are in the map now; this just verifies no crash
        for otype in IssueOutcomeType:
            tracker.record_outcome(
                100 + hash(otype) % 1000, otype, "test", phase="test"
            )
        # Verify outcomes were recorded for all types without crashing
        outcomes = tracker.get_all_outcomes()
        assert len(outcomes) >= 1

    def test_get_all_outcomes_returns_deep_copy(self, tmp_path: Path) -> None:
        """Mutating the returned dict should not affect internal state."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MERGED, "merged", phase="review")
        outcomes = tracker.get_all_outcomes()
        # Mutate the returned dict
        outcomes.pop("1", None)
        # Internal state should be unchanged
        assert tracker.get_all_outcomes().get("1") is not None

    def test_get_all_outcomes_deep_copy_protects_objects(self, tmp_path: Path) -> None:
        """Mutating a returned IssueOutcome should not affect internal state."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MERGED, "original", phase="review")
        outcomes = tracker.get_all_outcomes()
        # Mutate the returned object's field
        outcomes["1"].reason = "mutated"
        # Internal state should still have the original value
        internal = tracker.get_outcome(1)
        assert internal is not None
        assert internal.reason == "original"

    def test_record_outcome_populates_closed_at(self, tmp_path: Path) -> None:
        """closed_at should be set to an ISO timestamp."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MERGED, "merged", phase="review")
        outcome = tracker.get_outcome(1)
        assert outcome is not None
        assert outcome.closed_at  # non-empty
        # Should be a valid ISO timestamp
        from datetime import datetime

        datetime.fromisoformat(outcome.closed_at)

    def test_record_outcome_stores_all_fields(self, tmp_path: Path) -> None:
        """All fields (outcome_type, reason, phase, pr_number) should be stored."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(
            42, IssueOutcomeType.MERGED, "PR approved", pr_number=99, phase="review"
        )
        outcome = tracker.get_outcome(42)
        assert outcome is not None
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.reason == "PR approved"
        assert outcome.pr_number == 99
        assert outcome.phase == "review"

    def test_reset_clears_outcomes(self, tmp_path: Path) -> None:
        """reset() should clear all recorded outcomes."""
        from models import IssueOutcomeType

        tracker = make_tracker(tmp_path)
        tracker.record_outcome(1, IssueOutcomeType.MERGED, "merged", phase="review")
        tracker.reset()
        assert tracker.get_outcome(1) is None
        assert tracker.get_all_outcomes() == {}


# ---------------------------------------------------------------------------
# Session Counters
# ---------------------------------------------------------------------------


class TestSessionCounters:
    def test_increment_session_counter_triaged(self, tmp_path: Path) -> None:
        """Incrementing 'triaged' should update only that counter."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("triaged")
        counters = tracker.get_session_counters()
        assert counters.triaged == 1
        assert counters.planned == 0
        assert counters.implemented == 0
        assert counters.reviewed == 0
        assert counters.merged == 0

    def test_increment_session_counter_all_stages(self, tmp_path: Path) -> None:
        """Each stage counter increments independently."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("planned")
        tracker.increment_session_counter("implemented")
        tracker.increment_session_counter("reviewed")
        tracker.increment_session_counter("merged")
        counters = tracker.get_session_counters()
        assert counters.triaged == 2
        assert counters.planned == 1
        assert counters.implemented == 1
        assert counters.reviewed == 1
        assert counters.merged == 1

    def test_increment_unknown_stage_is_noop(self, tmp_path: Path) -> None:
        """Incrementing an unknown stage should not raise or change counters."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("nonexistent")
        counters = tracker.get_session_counters()
        assert counters.triaged == 0
        assert counters.planned == 0

    def test_session_counters_persist_across_reload(self, tmp_path: Path) -> None:
        """Session counters should survive a StateTracker reload from disk."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-02-01T12:00:00+00:00")
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("planned")
        tracker.increment_session_counter("implemented")

        # Reload from disk
        tracker2 = make_tracker(tmp_path)
        counters = tracker2.get_session_counters()
        assert counters.triaged == 1
        assert counters.planned == 1
        assert counters.implemented == 1
        assert counters.session_start == "2026-02-01T12:00:00+00:00"

    def test_reset_session_counters(self, tmp_path: Path) -> None:
        """Resetting session counters should zero all counts and set new start time."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("merged")

        tracker.reset_session_counters("2026-02-01T00:00:00+00:00")
        counters = tracker.get_session_counters()
        assert counters.triaged == 0
        assert counters.merged == 0
        assert counters.session_start == "2026-02-01T00:00:00+00:00"

    def test_get_session_counters_returns_copy(self, tmp_path: Path) -> None:
        """get_session_counters should return a copy, not a reference."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("triaged")
        counters = tracker.get_session_counters()
        counters.triaged = 999
        assert tracker.get_session_counters().triaged == 1

    def test_state_reset_clears_session_counters(self, tmp_path: Path) -> None:
        """StateTracker.reset() should clear session counters."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("triaged")
        tracker.reset()
        counters = tracker.get_session_counters()
        assert counters.triaged == 0
        assert counters.session_start == ""

    def test_session_counters_in_state_data(self, tmp_path: Path) -> None:
        """session_counters should appear in to_dict() output."""
        tracker = make_tracker(tmp_path)
        tracker.reset_session_counters("2026-01-01T00:00:00+00:00")
        tracker.increment_session_counter("planned")
        d = tracker.to_dict()
        sc = d["session_counters"]
        assert sc["planned"] == 1
        assert sc["session_start"] == "2026-01-01T00:00:00+00:00"

    def test_compute_throughput(self, tmp_path: Path) -> None:
        """Throughput should be computed as count / uptime_hours."""
        tracker = make_tracker(tmp_path)
        # Set session_start to 2 hours ago
        from datetime import UTC, datetime, timedelta

        two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        tracker.reset_session_counters(two_hours_ago)
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("triaged")
        tracker.increment_session_counter("triaged")

        throughput = tracker.compute_session_throughput()
        # 4 triaged / ~2 hours ~ 2.0/hr (allow some tolerance for test timing)
        assert 1.5 <= throughput["triaged"] <= 2.5
        assert throughput["planned"] == 0.0

    def test_compute_throughput_no_session_start(self, tmp_path: Path) -> None:
        """Throughput with empty session_start should return all zeros."""
        tracker = make_tracker(tmp_path)
        throughput = tracker.compute_session_throughput()
        assert throughput["triaged"] == 0.0
        assert throughput["planned"] == 0.0
        assert throughput["implemented"] == 0.0
        assert throughput["reviewed"] == 0.0
        assert throughput["merged"] == 0.0

    def test_compute_throughput_very_short_session(self, tmp_path: Path) -> None:
        """Throughput with very short uptime should not divide by zero."""
        from datetime import UTC, datetime

        tracker = make_tracker(tmp_path)
        just_now = datetime.now(UTC).isoformat()
        tracker.reset_session_counters(just_now)
        tracker.increment_session_counter("triaged")
        throughput = tracker.compute_session_throughput()
        # Should not raise; throughput may be very high but finite
        assert throughput["triaged"] >= 0.0


# ---------------------------------------------------------------------------
# Disabled workers persistence
# ---------------------------------------------------------------------------


class TestDisabledWorkersPersistence:
    def test_get_disabled_workers_empty_by_default(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_disabled_workers() == set()

    def test_set_and_get_disabled_workers(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_disabled_workers({"memory_sync", "metrics"})
        assert tracker.get_disabled_workers() == {"memory_sync", "metrics"}

    def test_disabled_workers_survive_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        t1 = StateTracker(state_file)
        t1.set_disabled_workers({"memory_sync", "pr_unsticker"})

        t2 = StateTracker(state_file)
        assert t2.get_disabled_workers() == {"memory_sync", "pr_unsticker"}

    def test_empty_disabled_workers_clears(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_disabled_workers({"memory_sync"})
        tracker.set_disabled_workers(set())
        assert tracker.get_disabled_workers() == set()

    def test_partial_corruption_missing_disabled_workers(self, tmp_path: Path) -> None:
        """State file with missing disabled_workers field loads gracefully."""
        state_file = tmp_path / "state.json"
        data = {
            "processed_issues": {},
            "active_worktrees": {},
            "active_branches": {},
            "reviewed_prs": {},
            "bg_worker_states": {
                "memory_sync": {
                    "name": "memory_sync",
                    "status": "ok",
                    "last_run": "2026-02-20T10:00:00Z",
                    "details": {},
                }
            },
        }
        state_file.write_text(json.dumps(data))

        tracker = StateTracker(state_file)
        assert tracker.get_disabled_workers() == set()
        states = tracker.get_bg_worker_states()
        assert "memory_sync" in states

    def test_partial_corruption_invalid_bg_worker_states(self, tmp_path: Path) -> None:
        """State file with corrupted bg_worker_states section but valid JSON loads gracefully."""
        state_file = tmp_path / "state.json"
        data = {
            "processed_issues": {"42": "merged"},
            "active_worktrees": {},
            "active_branches": {},
            "reviewed_prs": {},
            "bg_worker_states": "not_a_dict",
            "worker_heartbeats": {},
            "disabled_workers": ["memory_sync"],
        }
        state_file.write_text(json.dumps(data))

        # Pydantic validation will fail, resetting to defaults
        tracker = StateTracker(state_file)
        # After reset, disabled workers should be empty (defaults)
        assert tracker.get_disabled_workers() == set()
        assert tracker.get_bg_worker_states() == {}

    def test_deleted_bg_worker_states_preserves_disabled_workers(
        self, tmp_path: Path
    ) -> None:
        """Deleting bg_worker_states from state file preserves disabled_workers."""
        state_file = tmp_path / "state.json"
        data = {
            "processed_issues": {},
            "active_worktrees": {},
            "active_branches": {},
            "reviewed_prs": {},
            "disabled_workers": ["memory_sync"],
        }
        state_file.write_text(json.dumps(data))

        tracker = StateTracker(state_file)
        assert tracker.get_disabled_workers() == {"memory_sync"}
        # bg_worker_states defaults to empty when absent
        assert tracker.get_bg_worker_states() == {}


class TestActiveCrate:
    """Tests for active crate number persistence."""

    def test_defaults_to_none(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_active_crate_number() is None

    def test_set_and_get(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_active_crate_number(5)
        assert tracker.get_active_crate_number() == 5

    def test_clear_with_none(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_active_crate_number(5)
        tracker.set_active_crate_number(None)
        assert tracker.get_active_crate_number() is None

    def test_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_active_crate_number(7)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_active_crate_number() == 7

    def test_migration_from_old_state_file(self, tmp_path: Path) -> None:
        """Old state files without active_crate_number should default to None."""
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"processed_issues": {}}))

        tracker = StateTracker(state_file)
        assert tracker.get_active_crate_number() is None


# ---------------------------------------------------------------------------
# get_active_worktrees ValueError handling (issue #2576)
# ---------------------------------------------------------------------------


class TestGetActiveWorktreesValueError:
    """Verify get_active_worktrees handles non-integer keys gracefully."""

    def test_skips_non_integer_keys(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-integer worktree keys should be skipped with a warning."""
        import logging

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        # Inject corrupt data directly
        tracker._data.active_worktrees["abc"] = "/wt/abc"
        tracker._data.active_worktrees["42"] = "/wt/42"

        with caplog.at_level(logging.WARNING, logger="hydraflow.state"):
            result = tracker.get_active_worktrees()

        assert result == {42: "/wt/42"}
        assert "Skipping non-integer key" in caplog.text

    def test_returns_empty_dict_when_all_keys_invalid(self, tmp_path: Path) -> None:
        """All non-integer keys should result in an empty dict."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker._data.active_worktrees["foo"] = "/wt/foo"
        tracker._data.active_worktrees["bar"] = "/wt/bar"

        result = tracker.get_active_worktrees()
        assert result == {}

    def test_valid_keys_unaffected(self, tmp_path: Path) -> None:
        """Valid integer-string keys should still convert correctly."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_worktree(10, "/wt/10")
        tracker.set_worktree(20, "/wt/20")

        result = tracker.get_active_worktrees()
        assert result == {10: "/wt/10", 20: "/wt/20"}


class TestStateKeyHelpers:
    """Tests for the centralized _key and _int_keys helpers."""

    def test_key_converts_int_to_str(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        assert tracker._key(42) == "42"

    def test_key_passes_str_through(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        assert tracker._key("99") == "99"

    def test_int_keys_converts_str_keys_to_int(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        result = tracker._int_keys({"1": "a", "2": "b"})
        assert result == {1: "a", 2: "b"}

    def test_int_keys_skips_invalid(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        result = tracker._int_keys({"1": "a", "bad": "b", "3": "c"})
        assert result == {1: "a", 3: "c"}

    def test_int_keys_empty_dict(self, tmp_path: Path) -> None:
        tracker = StateTracker(tmp_path / "state.json")
        assert tracker._int_keys({}) == {}

    def test_roundtrip_state_preserves_all_fields(self, tmp_path: Path) -> None:
        """Save state, reload, and verify key fields survive the roundtrip."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)

        tracker.mark_issue(100, "reviewed")
        tracker.set_worktree(100, "/wt/100")
        tracker.set_branch(100, "agent/issue-100")
        tracker.increment_issue_attempts(100)
        tracker.set_hitl_origin(100, "hydraflow-review")
        tracker.increment_review_attempts(100)
        tracker.save()

        tracker2 = StateTracker(state_file)
        assert tracker2._data.processed_issues["100"] == "reviewed"
        assert tracker2.get_active_worktrees() == {100: "/wt/100"}
        assert tracker2.get_branch(100) == "agent/issue-100"
        assert tracker2.get_issue_attempts(100) == 1
        assert tracker2.get_hitl_origin(100) == "hydraflow-review"
        assert tracker2.get_review_attempts(100) == 1
