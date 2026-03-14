"""Tests for StateTracker mixin decomposition (#2604).

Validates that the domain-based mixin split preserves the public API,
that the facade class composes all mixins correctly, and that each
mixin's methods work through the unified StateTracker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from state import StateTracker
from state._epic import EpicStateMixin
from state._hitl import HITLStateMixin
from state._issue import IssueStateMixin
from state._lifetime import LifetimeStatsMixin
from state._report import ReportStateMixin
from state._review import ReviewStateMixin
from state._session import SessionStateMixin
from state._worker import WorkerStateMixin
from state._worktree import WorktreeStateMixin
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# Facade composition
# ---------------------------------------------------------------------------


class TestFacadeComposition:
    """StateTracker must inherit from all domain mixins."""

    @pytest.mark.parametrize(
        "mixin",
        [
            IssueStateMixin,
            WorktreeStateMixin,
            HITLStateMixin,
            ReviewStateMixin,
            EpicStateMixin,
            LifetimeStatsMixin,
            SessionStateMixin,
            WorkerStateMixin,
            ReportStateMixin,
        ],
    )
    def test_state_tracker_inherits_mixin(self, mixin: type) -> None:
        assert issubclass(StateTracker, mixin)

    def test_mro_contains_all_mixins(self) -> None:
        mixin_names = {
            "IssueStateMixin",
            "WorktreeStateMixin",
            "HITLStateMixin",
            "ReviewStateMixin",
            "EpicStateMixin",
            "LifetimeStatsMixin",
            "SessionStateMixin",
            "WorkerStateMixin",
            "ReportStateMixin",
        }
        mro_names = {c.__name__ for c in StateTracker.__mro__}
        assert mixin_names.issubset(mro_names)

    def test_import_path_unchanged(self) -> None:
        """The public import path 'from state import StateTracker' must work."""
        from state import StateTracker as ST  # noqa: PLC0415

        assert ST is StateTracker


# ---------------------------------------------------------------------------
# Cross-mixin persistence: changes via one domain are visible after reload
# ---------------------------------------------------------------------------


class TestCrossMixinPersistence:
    def test_all_domains_persist_and_reload(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)

        # Issue domain
        tracker.mark_issue(1, "planned")
        tracker.increment_issue_attempts(1)

        # Worktree domain
        tracker.set_worktree(1, "/wt/1")
        tracker.set_branch(1, "agent/issue-1")

        # HITL domain
        tracker.set_hitl_origin(1, "review")
        tracker.set_hitl_cause(1, "ci_failure")

        # Review domain
        tracker.increment_review_attempts(1)
        tracker.set_review_feedback(1, "needs tests")

        # Epic domain
        from models import EpicState  # noqa: PLC0415

        tracker.upsert_epic_state(EpicState(epic_number=10, child_issues=[1, 2]))

        # Lifetime domain
        tracker.record_issue_completed()

        # Session domain
        tracker.increment_session_counter("triaged")

        # Worker domain
        tracker.set_worker_intervals({"loop_a": 30})

        # Report domain
        tracker.update_memory_state([1, 2], "abc123")

        # Reload and verify all domains
        tracker2 = make_tracker(tmp_path)

        assert tracker2.to_dict()["processed_issues"]["1"] == "planned"
        assert tracker2.get_issue_attempts(1) == 1
        assert tracker2.get_active_worktrees() == {1: "/wt/1"}
        assert tracker2.get_branch(1) == "agent/issue-1"
        assert tracker2.get_hitl_origin(1) == "review"
        assert tracker2.get_hitl_cause(1) == "ci_failure"
        assert tracker2.get_review_attempts(1) == 1
        assert tracker2.get_review_feedback(1) == "needs tests"
        assert tracker2.get_epic_state(10) is not None
        assert tracker2.get_lifetime_stats().issues_completed == 1
        assert tracker2.get_session_counters().triaged == 1
        assert tracker2.get_worker_intervals() == {"loop_a": 30}
        ids, digest, _ = tracker2.get_memory_state()
        assert ids == [1, 2]
        assert digest == "abc123"


# ---------------------------------------------------------------------------
# Each mixin domain: targeted method tests
# ---------------------------------------------------------------------------


class TestIssueStateMixin:
    def test_mark_issue(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.mark_issue(42, "triaged")
        assert t.to_dict()["processed_issues"]["42"] == "triaged"

    def test_issue_attempts_lifecycle(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_issue_attempts(1) == 0
        assert t.increment_issue_attempts(1) == 1
        assert t.increment_issue_attempts(1) == 2
        t.reset_issue_attempts(1)
        assert t.get_issue_attempts(1) == 0

    def test_active_issue_numbers(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_active_issue_numbers([10, 20])
        assert t.get_active_issue_numbers() == [10, 20]

    def test_interrupted_issues(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_interrupted_issues({1: "plan", 2: "review"})
        result = t.get_interrupted_issues()
        assert result == {1: "plan", 2: "review"}
        t.clear_interrupted_issues()
        assert t.get_interrupted_issues() == {}

    def test_verification_issues(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_verification_issue(1, 100)
        assert t.get_verification_issue(1) == 100
        assert t.get_all_verification_issues() == {1: 100}
        t.clear_verification_issue(1)
        assert t.get_verification_issue(1) is None

    def test_crate_number(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_active_crate_number() is None
        t.set_active_crate_number(5)
        assert t.get_active_crate_number() == 5
        t.set_active_crate_number(None)
        assert t.get_active_crate_number() is None

    def test_mark_pr(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.mark_pr(101, "approved")
        assert t.to_dict()["reviewed_prs"]["101"] == "approved"

    def test_worker_result_meta(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_worker_result_meta(1) == {}
        t.set_worker_result_meta(1, {"exit_code": 0, "duration": 12.5})
        assert t.get_worker_result_meta(1) == {"exit_code": 0, "duration": 12.5}

    def test_record_outcome_records_and_increments_counter(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType  # noqa: PLC0415

        t = make_tracker(tmp_path)
        t.record_outcome(1, IssueOutcomeType.MERGED, "pr merged", pr_number=42)
        outcome = t.get_outcome(1)
        assert outcome is not None
        assert outcome.outcome == IssueOutcomeType.MERGED
        assert outcome.pr_number == 42
        assert t.get_lifetime_stats().total_outcomes_merged == 1

    def test_record_outcome_replaces_previous_and_adjusts_counter(
        self, tmp_path: Path
    ) -> None:
        from models import IssueOutcomeType  # noqa: PLC0415

        t = make_tracker(tmp_path)
        t.record_outcome(1, IssueOutcomeType.FAILED, "first attempt failed")
        assert t.get_lifetime_stats().total_outcomes_failed == 1

        # Replace with MERGED — FAILED counter must decrement back to 0
        t.record_outcome(1, IssueOutcomeType.MERGED, "recovered", pr_number=10)
        stats = t.get_lifetime_stats()
        assert stats.total_outcomes_failed == 0
        assert stats.total_outcomes_merged == 1

    def test_get_all_outcomes(self, tmp_path: Path) -> None:
        from models import IssueOutcomeType  # noqa: PLC0415

        t = make_tracker(tmp_path)
        t.record_outcome(1, IssueOutcomeType.MERGED, "done")
        t.record_outcome(2, IssueOutcomeType.HITL_CLOSED, "escalated")
        all_outcomes = t.get_all_outcomes()
        assert set(all_outcomes.keys()) == {"1", "2"}

    def test_record_hook_failure_and_retrieve(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_hook_failures(1) == []
        t.record_hook_failure(1, "pre-commit", "lint failed")
        failures = t.get_hook_failures(1)
        assert len(failures) == 1
        assert failures[0].hook_name == "pre-commit"
        assert failures[0].error == "lint failed"
        assert failures[0].timestamp is not None

    def test_record_hook_failure_caps_at_max(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        for i in range(510):
            t.record_hook_failure(1, "hook", f"error {i}")
        assert len(t.get_hook_failures(1)) == 500


class TestWorktreeStateMixin:
    def test_worktree_lifecycle(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_worktree(1, "/wt/1")
        assert t.get_active_worktrees() == {1: "/wt/1"}
        t.remove_worktree(1)
        assert t.get_active_worktrees() == {}

    def test_remove_absent_worktree_is_noop(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.remove_worktree(999)  # should not raise

    def test_branch_tracking(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_branch(1) is None
        t.set_branch(1, "fix/issue-1")
        assert t.get_branch(1) == "fix/issue-1"


class TestHITLStateMixin:
    def test_hitl_origin(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_hitl_origin(1, "implement")
        assert t.get_hitl_origin(1) == "implement"
        t.remove_hitl_origin(1)
        assert t.get_hitl_origin(1) is None

    def test_hitl_cause(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_hitl_cause(1, "ci_failure")
        assert t.get_hitl_cause(1) == "ci_failure"
        t.remove_hitl_cause(1)
        assert t.get_hitl_cause(1) is None

    def test_hitl_summary(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_hitl_summary(1, "Test summary")
        assert t.get_hitl_summary(1) == "Test summary"
        assert t.get_hitl_summary_updated_at(1) is not None
        t.remove_hitl_summary(1)
        assert t.get_hitl_summary(1) is None

    def test_hitl_summary_empty_returns_none(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_hitl_summary(999) is None
        assert t.get_hitl_summary_updated_at(999) is None

    def test_hitl_summary_failure(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_hitl_summary_failure(1, "timeout error")
        failed_at, error = t.get_hitl_summary_failure(1)
        assert failed_at is not None
        assert error == "timeout error"
        t.clear_hitl_summary_failure(1)
        failed_at2, error2 = t.get_hitl_summary_failure(1)
        assert failed_at2 is None
        assert error2 == ""

    def test_hitl_visual_evidence(self, tmp_path: Path) -> None:
        from models import VisualEvidence  # noqa: PLC0415

        t = make_tracker(tmp_path)
        ev = VisualEvidence(screenshots=["s1.png"])
        t.set_hitl_visual_evidence(1, ev)
        assert t.get_hitl_visual_evidence(1) is not None
        t.remove_hitl_visual_evidence(1)
        assert t.get_hitl_visual_evidence(1) is None


class TestReviewStateMixin:
    def test_review_attempts_lifecycle(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_review_attempts(1) == 0
        assert t.increment_review_attempts(1) == 1
        t.reset_review_attempts(1)
        assert t.get_review_attempts(1) == 0

    def test_review_feedback(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_review_feedback(1, "LGTM")
        assert t.get_review_feedback(1) == "LGTM"
        t.clear_review_feedback(1)
        assert t.get_review_feedback(1) is None

    def test_last_reviewed_sha(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_last_reviewed_sha(1, "abc123")
        assert t.get_last_reviewed_sha(1) == "abc123"
        t.clear_last_reviewed_sha(1)
        assert t.get_last_reviewed_sha(1) is None


class TestEpicStateMixin:
    def test_epic_lifecycle(self, tmp_path: Path) -> None:
        from models import EpicState  # noqa: PLC0415

        t = make_tracker(tmp_path)
        es = EpicState(epic_number=10, child_issues=[1, 2, 3])
        t.upsert_epic_state(es)
        loaded = t.get_epic_state(10)
        assert loaded is not None
        assert loaded.child_issues == [1, 2, 3]

    def test_epic_child_complete(self, tmp_path: Path) -> None:
        from models import EpicState  # noqa: PLC0415

        t = make_tracker(tmp_path)
        t.upsert_epic_state(EpicState(epic_number=10, child_issues=[1, 2]))
        t.mark_epic_child_complete(10, 1)
        progress = t.get_epic_progress(10)
        assert progress["merged"] == 1

    def test_epic_progress_empty(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_epic_progress(999) == {}

    def test_release_lifecycle(self, tmp_path: Path) -> None:
        from models import Release  # noqa: PLC0415

        t = make_tracker(tmp_path)
        r = Release(epic_number=10, version="1.0.0", tag="v1.0")
        t.upsert_release(r)
        loaded = t.get_release(10)
        assert loaded is not None
        assert loaded.tag == "v1.0"
        assert loaded.version == "1.0.0"


class TestLifetimeStatsMixin:
    def test_record_counters(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.record_issue_completed()
        t.record_pr_merged()
        t.record_issue_created()
        stats = t.get_lifetime_stats()
        assert stats.issues_completed == 1
        assert stats.prs_merged == 1
        assert stats.issues_created == 1

    def test_merge_duration_stats(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_merge_duration_stats() == {}
        t.record_merge_duration(100.0)
        t.record_merge_duration(200.0)
        stats = t.get_merge_duration_stats()
        assert "avg" in stats
        assert "p50" in stats
        assert "p90" in stats

    def test_retries_summary(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.record_stage_retry(1, "implement")
        t.record_stage_retry(2, "implement")
        t.record_stage_retry(1, "review")
        summary = t.get_retries_summary()
        assert summary["implement"] == 2
        assert summary["review"] == 1

    def test_threshold_fired(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_fired_thresholds() == []
        t.mark_threshold_fired("quality_fix_rate")
        assert "quality_fix_rate" in t.get_fired_thresholds()
        t.clear_threshold_fired("quality_fix_rate")
        assert t.get_fired_thresholds() == []


class TestSessionStateMixin:
    def test_session_counter_lifecycle(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.increment_session_counter("triaged")
        t.increment_session_counter("triaged")
        assert t.get_session_counters().triaged == 2
        t.reset_session_counters("2025-01-01T00:00:00Z")
        assert t.get_session_counters().triaged == 0

    def test_unknown_stage_ignored(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.increment_session_counter("nonexistent")  # should not raise

    def test_session_persistence(self, tmp_path: Path) -> None:
        from models import SessionLog  # noqa: PLC0415

        t = make_tracker(tmp_path)
        s = SessionLog(id="s1", repo="test/repo", started_at="2025-01-01T00:00:00Z")
        t.save_session(s)
        loaded = t.load_sessions()
        assert len(loaded) == 1
        assert loaded[0].id == "s1"

    def test_session_get_by_id(self, tmp_path: Path) -> None:
        from models import SessionLog  # noqa: PLC0415

        t = make_tracker(tmp_path)
        s = SessionLog(id="s2", repo="test/repo", started_at="2025-01-01T00:00:00Z")
        t.save_session(s)
        found = t.get_session("s2")
        assert found is not None
        assert found.id == "s2"
        assert t.get_session("nonexistent") is None


class TestWorkerStateMixin:
    def test_worker_intervals(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_worker_intervals({"loop_a": 30, "loop_b": 60})
        assert t.get_worker_intervals() == {"loop_a": 30, "loop_b": 60}

    def test_disabled_workers(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_disabled_workers({"loop_a", "loop_b"})
        assert t.get_disabled_workers() == {"loop_a", "loop_b"}

    def test_worker_heartbeat(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_worker_heartbeat(
            "loop_a",
            {
                "status": "running",
                "last_run": "2025-01-01T00:00:00Z",
                "details": {},
            },
        )
        heartbeats = t.get_worker_heartbeats()
        assert "loop_a" in heartbeats
        assert heartbeats["loop_a"]["status"] == "running"

    def test_remove_bg_worker_state(self, tmp_path: Path) -> None:
        from models import BackgroundWorkerState  # noqa: PLC0415

        t = make_tracker(tmp_path)
        t.set_bg_worker_state(
            "loop_a", BackgroundWorkerState(name="loop_a", status="running")
        )
        assert "loop_a" in t.get_bg_worker_states()
        t.remove_bg_worker_state("loop_a")
        assert "loop_a" not in t.get_bg_worker_states()

    def test_maybe_migrate_worker_states_populates_heartbeats(
        self, tmp_path: Path
    ) -> None:
        """Legacy bg_worker_states (no worker_heartbeats) must be migrated on load."""
        import json  # noqa: PLC0415

        state_file = tmp_path / "state" / "state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_state = {
            "bg_worker_states": {
                "triage_loop": {
                    "name": "triage_loop",
                    "status": "running",
                    "last_run": "2025-01-01T00:00:00Z",
                    "details": {},
                }
            },
            "worker_heartbeats": {},
        }
        state_file.write_text(json.dumps(legacy_state))

        t = StateTracker(state_file)

        heartbeats = t.get_worker_heartbeats()
        assert "triage_loop" in heartbeats
        assert heartbeats["triage_loop"]["status"] == "running"
        assert heartbeats["triage_loop"]["last_run"] == "2025-01-01T00:00:00Z"

    def test_no_migration_when_heartbeats_already_present(self, tmp_path: Path) -> None:
        """If worker_heartbeats already has entries, migration must not run."""
        import json  # noqa: PLC0415

        state_file = tmp_path / "state" / "state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_with_both = {
            "bg_worker_states": {
                "old_loop": {
                    "name": "old_loop",
                    "status": "disabled",
                    "last_run": None,
                    "details": {},
                }
            },
            "worker_heartbeats": {
                "new_loop": {
                    "status": "running",
                    "last_run": "2025-06-01T00:00:00Z",
                    "details": {},
                }
            },
        }
        state_file.write_text(json.dumps(state_with_both))

        t = StateTracker(state_file)

        heartbeats = t.get_worker_heartbeats()
        assert "new_loop" in heartbeats
        assert "old_loop" not in heartbeats


class TestReportStateMixin:
    def test_pending_report_lifecycle(self, tmp_path: Path) -> None:
        from models import PendingReport  # noqa: PLC0415

        t = make_tracker(tmp_path)
        r = PendingReport(id="r1", description="test bug report")
        t.enqueue_report(r)
        assert t.peek_report() is not None
        assert t.peek_report().id == "r1"
        dequeued = t.dequeue_report()
        assert dequeued is not None
        assert dequeued.id == "r1"
        assert t.peek_report() is None

    def test_metrics_state(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.set_metrics_issue_number(42)
        assert t.get_metrics_issue_number() == 42
        t.update_metrics_state("hash123")
        num, snap_hash, synced = t.get_metrics_state()
        assert num == 42
        assert snap_hash == "hash123"
        assert synced is not None

    def test_manifest_state(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.update_manifest_state("mhash")
        mhash, updated = t.get_manifest_state()
        assert mhash == "mhash"
        assert updated is not None
        t.set_manifest_issue_number(10)
        assert t.get_manifest_issue_number() == 10
        t.set_manifest_snapshot_hash("snap1")
        assert t.get_manifest_snapshot_hash() == "snap1"

    def test_memory_state(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.update_memory_state([1, 2, 3], "digest")
        ids, digest, synced = t.get_memory_state()
        assert ids == [1, 2, 3]
        assert digest == "digest"
        assert synced is not None

    def test_baseline_audit(self, tmp_path: Path) -> None:
        from models import BaselineAuditRecord  # noqa: PLC0415

        t = make_tracker(tmp_path)
        record = BaselineAuditRecord(
            pr_number=1,
            issue_number=10,
            changed_files=["a.py"],
        )
        t.record_baseline_change(10, record)
        assert len(t.get_baseline_audit(10)) == 1
        latest = t.get_latest_baseline_record(10)
        assert latest is not None
        assert latest.pr_number == 1

    def test_baseline_audit_empty(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        assert t.get_baseline_audit(999) == []
        assert t.get_latest_baseline_record(999) is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_reset_preserves_lifetime_stats(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        t.record_issue_completed()
        t.mark_issue(1, "done")
        t.reset()
        assert t.get_lifetime_stats().issues_completed == 1
        assert t.to_dict()["processed_issues"] == {}

    def test_empty_state_file_handled(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        sf.write_text("")
        t = StateTracker(sf)
        assert t.to_dict()["processed_issues"] == {}

    def test_corrupt_json_handled(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        sf.write_text("not json{{{")
        t = StateTracker(sf)
        assert t.to_dict()["processed_issues"] == {}

    def test_non_dict_json_handled(self, tmp_path: Path) -> None:
        sf = tmp_path / "state.json"
        sf.write_text("[1, 2, 3]")
        t = StateTracker(sf)
        assert t.to_dict()["processed_issues"] == {}

    def test_to_dict_returns_copy(self, tmp_path: Path) -> None:
        t = make_tracker(tmp_path)
        d = t.to_dict()
        d["processed_issues"]["999"] = "hacked"
        assert "999" not in t.to_dict()["processed_issues"]
