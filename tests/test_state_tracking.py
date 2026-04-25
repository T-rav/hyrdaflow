"""Tests for state -- core tracking operations."""

from __future__ import annotations

import json
from pathlib import Path

from models import BackgroundWorkerState, LifetimeStats
from state import StateTracker
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_fresh_tracker_has_no_active_workspaces(self, tmp_path: Path) -> None:
        """A fresh tracker with no backing file should have no active worktrees."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_active_workspaces() == {}

    def test_fresh_tracker_has_no_processed_issues(self, tmp_path: Path) -> None:
        """A fresh tracker with no backing file should have no processed issues."""
        tracker = make_tracker(tmp_path)
        assert tracker.to_dict()["processed_issues"] == {}

    def test_fresh_tracker_has_no_branches(self, tmp_path: Path) -> None:
        """A fresh tracker with no backing file should have no branches."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_branch(1) is None

    def test_fresh_tracker_has_no_reviewed_prs(self, tmp_path: Path) -> None:
        """A fresh tracker with no backing file should have no reviewed PRs."""
        tracker = make_tracker(tmp_path)
        assert tracker.to_dict()["reviewed_prs"] == {}

    def test_defaults_structure_matches_expected_keys(self, tmp_path: Path) -> None:
        """A fresh tracker should expose exactly the known set of state keys."""
        tracker = make_tracker(tmp_path)
        d = tracker.to_dict()
        expected_keys = {
            "active_branches",
            "active_crate_number",
            "bead_mappings",
            "active_issue_numbers",
            "active_workspaces",
            "baseline_audit",
            "bg_worker_states",
            "dependabot_merge_processed",
            "dependabot_merge_settings",
            "ci_monitor_settings",
            "ci_monitor_tracked_failures",
            "code_grooming_filed",
            "code_grooming_settings",
            "disabled_workers",
            "epic_states",
            "hitl_causes",
            "hitl_origins",
            "hitl_summaries",
            "hitl_summary_failures",
            "hitl_visual_evidence",
            "hook_failures",
            "interrupted_issues",
            "issue_attempts",
            "issue_outcomes",
            "last_reviewed_shas",
            "last_updated",
            "lifetime_stats",
            "memory_digest_hash",
            "memory_issue_ids",
            "memory_last_synced",
            "metrics_last_snapshot_hash",
            "metrics_last_synced",
            "pending_reports",
            "tracked_reports",
            "processed_issues",
            "releases",
            "review_attempts",
            "review_feedback",
            "completed_timelines",
            "digest_hashes",
            "reviewed_prs",
            "schema_version",
            "shape_conversations",
            "shape_responses",
            "security_patch_processed",
            "security_patch_settings",
            "stale_issue_closed",
            "stale_issue_settings",
            "session_counters",
            "verification_issues",
            "worker_heartbeats",
            "worker_intervals",
            "worker_result_meta",
            "escalation_contexts",
            "diagnostic_attempts",
            "diagnosis_severities",
            "sentry_creation_attempts",
            "trace_runs",
            "route_back_counts",
            # Trust-arch-hardening mixins (spec §4.1–§4.9 + §12.1)
            "auto_reverts_in_cycle",
            "auto_reverts_successful",
            "fake_coverage_attempts",
            "fake_coverage_last_known",
            "flake_attempts",
            "flake_counts",
            "flake_reruns_total",
            "last_green_audit",
            "last_green_rc_sha",
            "last_rc_red_sha",
            "managed_repos_onboarding_status",
            "principles_drift_attempts",
            "corpus_learning_validation_attempts",
            "retry_lineage_attempts",
            "retry_lineage_pr_chains",
            "rc_budget_attempts",
            "rc_budget_duration_history",
            "rc_cycle_id",
            "skill_prompt_attempts",
            "skill_prompt_last_green",
            "trust_fleet_sanity_attempts",
            "trust_fleet_sanity_last_run",
            "trust_fleet_sanity_last_seen_counts",
            "wiki_rot_attempts",
            "contract_refresh_attempts",
        }
        assert set(d.keys()) == expected_keys

    def test_loads_legacy_file_with_current_batch_field(self, tmp_path: Path) -> None:
        """Old state files containing current_batch should load without error."""
        state_file = tmp_path / "state.json"
        legacy_data = {
            "current_batch": 7,
            "processed_issues": {"3": "success"},
            "active_workspaces": {},
            "active_branches": {},
            "reviewed_prs": {"42": "approve"},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(legacy_data))

        tracker = StateTracker(state_file)
        # Existing data is preserved; current_batch is silently dropped
        assert tracker.to_dict()["processed_issues"].get(str(3)) == "success"
        assert tracker.to_dict()["reviewed_prs"].get(str(42)) == "approve"
        assert "current_batch" not in tracker.to_dict()

    def test_loads_existing_file_on_init(self, tmp_path: Path) -> None:
        """If a state file already exists on disk it should be loaded."""
        state_file = tmp_path / "state.json"
        initial_data = {
            "processed_issues": {"7": "success"},
            "active_workspaces": {},
            "active_branches": {},
            "reviewed_prs": {},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(initial_data))

        tracker = StateTracker(state_file)
        assert tracker.to_dict()["processed_issues"].get(str(7)) == "success"


# ---------------------------------------------------------------------------
# Persistence (load / save round-trip)
# ---------------------------------------------------------------------------


class TestLoadSave:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        state_file = tmp_path / "state.json"
        assert not state_file.exists()
        tracker.save()
        assert state_file.exists()

    def test_save_writes_valid_json(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.save()
        raw = (tmp_path / "state.json").read_text()
        data = json.loads(raw)  # must not raise
        assert isinstance(data, dict)

    def test_save_sets_last_updated_is_present(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.save()
        assert tracker.to_dict()["last_updated"] is not None

    def test_save_sets_last_updated_is_iso_format(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.save()
        assert "T" in tracker.to_dict()["last_updated"]

    def test_round_trip_preserves_issue_status(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(10, "success")
        tracker2 = StateTracker(state_file)
        assert tracker2.to_dict()["processed_issues"].get(str(10)) == "success"

    def test_round_trip_preserves_worktree(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_workspace(10, "/tmp/wt-10")
        tracker2 = StateTracker(state_file)
        assert tracker2.get_active_workspaces() == {10: "/tmp/wt-10"}

    def test_round_trip_preserves_branch(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_branch(10, "agent/issue-10")
        tracker2 = StateTracker(state_file)
        assert tracker2.get_branch(10) == "agent/issue-10"

    def test_round_trip_preserves_pr(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_pr(99, "merged")
        tracker2 = StateTracker(state_file)
        assert tracker2.to_dict()["reviewed_prs"].get(str(99)) == "merged"

    def test_explicit_load_returns_none(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.load() is None


class TestBackgroundWorkerStatePersistence:
    def test_defaults_empty_states(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_bg_worker_states() == {}

    def test_set_and_get_worker_state(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_bg_worker_state(
            "memory_sync",
            BackgroundWorkerState(
                name="memory_sync",
                status="ok",
                last_run="2026-02-20T10:30:00Z",
                details={"count": 5},
            ),
        )
        states = tracker.get_bg_worker_states()
        assert "memory_sync" in states
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["details"]["count"] == 5

    def test_remove_worker_state(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_bg_worker_state(
            "metrics",
            BackgroundWorkerState(
                name="metrics", status="error", last_run=None, details={}
            ),
        )
        tracker.remove_bg_worker_state("metrics")
        assert tracker.get_bg_worker_states() == {}


class TestWorkerHeartbeatPersistence:
    def test_worker_heartbeats_initially_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_worker_heartbeats() == {}

    def test_set_worker_heartbeat_round_trip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worker_heartbeat(
            "memory_sync",
            {
                "status": "ok",
                "last_run": "2026-02-20T10:30:00Z",
                "details": {"count": 2},
            },
        )
        beats = tracker.get_worker_heartbeats()
        assert beats["memory_sync"]["status"] == "ok"
        assert beats["memory_sync"]["details"]["count"] == 2

        states = tracker.get_bg_worker_states()
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["details"]["count"] == 2

    def test_set_bg_worker_state_populates_worker_heartbeats(
        self, tmp_path: Path
    ) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_bg_worker_state(
            "metrics",
            BackgroundWorkerState(
                name="metrics",
                status="error",
                last_run="2026-02-20T12:00:00Z",
                details={"synced": 0},
            ),
        )
        beats = tracker.get_worker_heartbeats()
        assert beats["metrics"]["status"] == "error"
        assert beats["metrics"]["details"]["synced"] == 0

    def test_legacy_state_file_migrates_bg_worker_states_to_heartbeats(
        self, tmp_path: Path
    ) -> None:
        """Loading a legacy state file with only bg_worker_states populates worker_heartbeats."""
        state_file = tmp_path / "state.json"
        # Write a legacy state file: bg_worker_states populated, worker_heartbeats absent
        state_file.write_text(
            json.dumps(
                {
                    "bg_worker_states": {
                        "memory_sync": {
                            "name": "memory_sync",
                            "status": "ok",
                            "last_run": "2025-01-01T00:00:00Z",
                            "details": {"count": 3},
                        }
                    }
                }
            )
        )
        tracker = StateTracker(state_file)
        beats = tracker.get_worker_heartbeats()
        assert "memory_sync" in beats
        assert beats["memory_sync"]["status"] == "ok"
        assert beats["memory_sync"]["last_run"] == "2025-01-01T00:00:00Z"
        assert beats["memory_sync"]["details"]["count"] == 3


# ---------------------------------------------------------------------------
# Issue tracking
# ---------------------------------------------------------------------------


class TestIssueTracking:
    def test_mark_issue_stores_status(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(42, "in_progress")
        assert tracker.to_dict()["processed_issues"].get(str(42)) == "in_progress"

    def test_mark_issue_overwrites_previous_status(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(42, "in_progress")
        tracker.mark_issue(42, "success")
        assert tracker.to_dict()["processed_issues"].get(str(42)) == "success"

    def test_mark_issue_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(5, "success")
        # File must exist after mark_issue
        assert state_file.exists()

    def test_multiple_issues_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(1, "success")
        tracker.mark_issue(2, "failed")
        tracker.mark_issue(3, "in_progress")

        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"
        assert tracker.to_dict()["processed_issues"].get(str(2)) == "failed"
        assert tracker.to_dict()["processed_issues"].get(str(3)) == "in_progress"


# ---------------------------------------------------------------------------
# Worktree tracking
# ---------------------------------------------------------------------------


class TestWorktreeTracking:
    def test_set_workspace_stores_path(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(7, "/tmp/wt-7")
        assert tracker.get_active_workspaces() == {7: "/tmp/wt-7"}

    def test_set_workspace_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_workspace(7, "/tmp/wt-7")
        assert state_file.exists()

    def test_remove_workspace_deletes_entry(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(7, "/tmp/wt-7")
        tracker.remove_workspace(7)
        assert 7 not in tracker.get_active_workspaces()

    def test_remove_workspace_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Should not raise
        tracker.remove_workspace(999)
        assert tracker.get_active_workspaces() == {}

    def test_get_active_workspaces_returns_int_keys(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(10, "/wt/10")
        tracker.set_workspace(20, "/wt/20")
        wt = tracker.get_active_workspaces()
        assert all(isinstance(k, int) for k in wt)

    def test_multiple_worktrees(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(1, "/wt/1")
        tracker.set_workspace(2, "/wt/2")
        assert tracker.get_active_workspaces() == {1: "/wt/1", 2: "/wt/2"}

    def test_remove_one_worktree_leaves_others(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(1, "/wt/1")
        tracker.set_workspace(2, "/wt/2")
        tracker.remove_workspace(1)
        assert tracker.get_active_workspaces() == {2: "/wt/2"}


# ---------------------------------------------------------------------------
# Branch tracking
# ---------------------------------------------------------------------------


class TestBranchTracking:
    def test_set_and_get_branch(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(42, "agent/issue-42")
        assert tracker.get_branch(42) == "agent/issue-42"

    def test_get_branch_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_branch(999) is None

    def test_set_branch_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_branch(1, "agent/issue-1")
        assert state_file.exists()

    def test_set_branch_overwrites(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(5, "branch-v1")
        tracker.set_branch(5, "branch-v2")
        assert tracker.get_branch(5) == "branch-v2"

    def test_multiple_branches_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(1, "agent/issue-1")
        tracker.set_branch(2, "agent/issue-2")
        assert tracker.get_branch(1) == "agent/issue-1"
        assert tracker.get_branch(2) == "agent/issue-2"


# ---------------------------------------------------------------------------
# PR tracking
# ---------------------------------------------------------------------------


class TestPRTracking:
    def test_mark_pr_stores_status(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_pr(101, "open")
        assert tracker.to_dict()["reviewed_prs"].get(str(101)) == "open"

    def test_mark_pr_overwrites_status(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_pr(101, "open")
        tracker.mark_pr(101, "merged")
        assert tracker.to_dict()["reviewed_prs"].get(str(101)) == "merged"

    def test_get_pr_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.to_dict()["reviewed_prs"].get(str(999)) is None

    def test_mark_pr_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_pr(50, "open")
        assert state_file.exists()

    def test_multiple_prs_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_pr(1, "open")
        tracker.mark_pr(2, "closed")
        assert tracker.to_dict()["reviewed_prs"].get(str(1)) == "open"
        assert tracker.to_dict()["reviewed_prs"].get(str(2)) == "closed"


# ---------------------------------------------------------------------------
# HITL origin tracking
# ---------------------------------------------------------------------------


class TestHITLOriginTracking:
    def test_set_hitl_origin_stores_label(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(42, "hydraflow-review")
        assert tracker.get_hitl_origin(42) == "hydraflow-review"

    def test_get_hitl_origin_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_hitl_origin(999) is None

    def test_set_hitl_origin_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_hitl_origin(42, "hydraflow-review")
        assert state_file.exists()

    def test_set_hitl_origin_overwrites(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(42, "hydraflow-find")
        tracker.set_hitl_origin(42, "hydraflow-review")
        assert tracker.get_hitl_origin(42) == "hydraflow-review"

    def test_remove_hitl_origin_deletes_entry(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(42, "hydraflow-review")
        tracker.remove_hitl_origin(42)
        assert tracker.get_hitl_origin(42) is None

    def test_remove_hitl_origin_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Should not raise
        tracker.remove_hitl_origin(999)
        assert tracker.get_hitl_origin(999) is None

    def test_multiple_origins_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(1, "hydraflow-find")
        tracker.set_hitl_origin(2, "hydraflow-review")
        assert tracker.get_hitl_origin(1) == "hydraflow-find"
        assert tracker.get_hitl_origin(2) == "hydraflow-review"

    def test_hitl_origin_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_hitl_origin(42, "hydraflow-review")

        tracker2 = StateTracker(state_file)
        assert tracker2.get_hitl_origin(42) == "hydraflow-review"

    def test_reset_clears_hitl_origins(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(42, "hydraflow-review")
        tracker.reset()
        assert tracker.get_hitl_origin(42) is None

    def test_migration_adds_hitl_origins_to_old_file(self, tmp_path: Path) -> None:
        """Loading a state file without hitl_origins should default to {}."""
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
        assert tracker.get_hitl_origin(1) is None
        # Existing data is preserved
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"


# ---------------------------------------------------------------------------
# HITL cause tracking
# ---------------------------------------------------------------------------


class TestHITLCauseTracking:
    def test_set_hitl_cause_stores_cause(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_cause(42, "CI failed after 2 fix attempts")
        assert tracker.get_hitl_cause(42) == "CI failed after 2 fix attempts"

    def test_get_hitl_cause_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_hitl_cause(999) is None

    def test_set_hitl_cause_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_hitl_cause(42, "Merge conflict with main branch")
        assert state_file.exists()

    def test_set_hitl_cause_overwrites(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_cause(42, "First cause")
        tracker.set_hitl_cause(42, "Second cause")
        assert tracker.get_hitl_cause(42) == "Second cause"

    def test_remove_hitl_cause_deletes_entry(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_cause(42, "Some cause")
        tracker.remove_hitl_cause(42)
        assert tracker.get_hitl_cause(42) is None

    def test_remove_hitl_cause_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Should not raise
        tracker.remove_hitl_cause(999)
        assert tracker.get_hitl_cause(999) is None

    def test_multiple_causes_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_cause(1, "CI failed after 2 fix attempts")
        tracker.set_hitl_cause(2, "Merge conflict with main branch")
        assert tracker.get_hitl_cause(1) == "CI failed after 2 fix attempts"
        assert tracker.get_hitl_cause(2) == "Merge conflict with main branch"

    def test_hitl_cause_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_hitl_cause(42, "PR merge failed on GitHub")

        tracker2 = StateTracker(state_file)
        assert tracker2.get_hitl_cause(42) == "PR merge failed on GitHub"

    def test_reset_clears_hitl_causes(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_cause(42, "Some cause")
        tracker.reset()
        assert tracker.get_hitl_cause(42) is None

    def test_migration_adds_hitl_causes_to_old_file(self, tmp_path: Path) -> None:
        """Loading a state file without hitl_causes should default to {}."""
        state_file = tmp_path / "state.json"
        old_data = {
            "processed_issues": {"1": "success"},
            "active_workspaces": {},
            "active_branches": {},
            "reviewed_prs": {},
            "hitl_origins": {"42": "hydraflow-review"},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(old_data))

        tracker = StateTracker(state_file)
        assert tracker.get_hitl_cause(42) is None
        # Existing data is preserved
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"


# ---------------------------------------------------------------------------
# HITL visual evidence tracking
# ---------------------------------------------------------------------------


class TestHITLVisualEvidence:
    def test_set_and_get_visual_evidence(self, tmp_path: Path) -> None:
        from models import VisualEvidence, VisualEvidenceItem

        tracker = make_tracker(tmp_path)
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="login", diff_percent=5.0, status="fail")
            ],
            summary="1 screen failed",
        )
        tracker.set_hitl_visual_evidence(42, ev)
        result = tracker.get_hitl_visual_evidence(42)
        assert result is not None
        assert len(result.items) == 1
        assert result.items[0].screen_name == "login"
        assert result.summary == "1 screen failed"

    def test_get_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_hitl_visual_evidence(999) is None

    def test_set_triggers_save(self, tmp_path: Path) -> None:
        from models import VisualEvidence

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_hitl_visual_evidence(42, VisualEvidence())
        assert state_file.exists()

    def test_set_overwrites_existing(self, tmp_path: Path) -> None:
        from models import VisualEvidence, VisualEvidenceItem

        tracker = make_tracker(tmp_path)
        ev1 = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="page1", diff_percent=1.0, status="pass")
            ],
        )
        ev2 = VisualEvidence(
            items=[
                VisualEvidenceItem(
                    screen_name="page2", diff_percent=10.0, status="fail"
                )
            ],
            attempt=2,
        )
        tracker.set_hitl_visual_evidence(42, ev1)
        tracker.set_hitl_visual_evidence(42, ev2)
        result = tracker.get_hitl_visual_evidence(42)
        assert result is not None
        assert result.items[0].screen_name == "page2"
        assert result.attempt == 2

    def test_remove_deletes_entry(self, tmp_path: Path) -> None:
        from models import VisualEvidence

        tracker = make_tracker(tmp_path)
        tracker.set_hitl_visual_evidence(42, VisualEvidence())
        tracker.remove_hitl_visual_evidence(42)
        assert tracker.get_hitl_visual_evidence(42) is None

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.remove_hitl_visual_evidence(999)
        assert tracker.get_hitl_visual_evidence(999) is None

    def test_persists_across_reload(self, tmp_path: Path) -> None:
        from models import VisualEvidence, VisualEvidenceItem

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        ev = VisualEvidence(
            items=[
                VisualEvidenceItem(screen_name="dash", diff_percent=8.0, status="warn")
            ],
            summary="warn threshold",
            attempt=3,
        )
        tracker.set_hitl_visual_evidence(42, ev)

        tracker2 = StateTracker(state_file)
        result = tracker2.get_hitl_visual_evidence(42)
        assert result is not None
        assert result.items[0].screen_name == "dash"
        assert result.attempt == 3

    def test_multiple_issues_tracked_independently(self, tmp_path: Path) -> None:
        from models import VisualEvidence, VisualEvidenceItem

        tracker = make_tracker(tmp_path)
        tracker.set_hitl_visual_evidence(
            1,
            VisualEvidence(
                items=[
                    VisualEvidenceItem(screen_name="a", diff_percent=1.0, status="pass")
                ]
            ),
        )
        tracker.set_hitl_visual_evidence(
            2,
            VisualEvidence(
                items=[
                    VisualEvidenceItem(screen_name="b", diff_percent=2.0, status="pass")
                ]
            ),
        )
        assert tracker.get_hitl_visual_evidence(1).items[0].screen_name == "a"
        assert tracker.get_hitl_visual_evidence(2).items[0].screen_name == "b"


# ---------------------------------------------------------------------------
# HITL summary failure tracking
# ---------------------------------------------------------------------------


class TestHITLSummaryFailure:
    def test_get_returns_empty_when_nothing_set(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        last_failed_at, error = tracker.get_hitl_summary_failure(42)
        assert last_failed_at is None
        assert error == ""

    def test_set_and_get_failure_metadata(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_summary_failure(7, "LLM timeout")
        last_failed_at, error = tracker.get_hitl_summary_failure(7)
        assert last_failed_at is not None
        assert error == "LLM timeout"

    def test_error_is_truncated_to_300_chars(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        message = "X" * 400
        tracker.set_hitl_summary_failure(12, message)
        _, error = tracker.get_hitl_summary_failure(12)
        assert len(error) == 300

    def test_clear_removes_failure_entry(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_summary_failure(99, "network blip")
        tracker.clear_hitl_summary_failure(99)
        last_failed_at, error = tracker.get_hitl_summary_failure(99)
        assert last_failed_at is None
        assert error == ""


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_processed_issues(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(1, "success")
        tracker.reset()
        assert tracker.to_dict()["processed_issues"].get(str(1)) is None

    def test_reset_clears_active_workspaces(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_workspace(1, "/wt/1")
        tracker.reset()
        assert tracker.get_active_workspaces() == {}

    def test_reset_clears_active_branches(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(1, "agent/issue-1")
        tracker.reset()
        assert tracker.get_branch(1) is None

    def test_reset_clears_reviewed_prs(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_pr(99, "merged")
        tracker.reset()
        assert tracker.to_dict()["reviewed_prs"].get(str(99)) is None

    def test_reset_persists_to_disk(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")
        tracker.reset()

        tracker2 = StateTracker(state_file)
        assert tracker2.to_dict()["processed_issues"].get(str(1)) is None

    def test_reset_clears_all_state_at_once(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(1, "success")
        tracker.set_workspace(1, "/wt/1")
        tracker.set_branch(1, "agent/issue-1")
        tracker.mark_pr(10, "open")
        tracker.set_hitl_origin(1, "hydraflow-review")
        tracker.set_hitl_cause(1, "CI failed after 2 fix attempts")
        tracker.increment_issue_attempts(1)
        tracker.set_active_issue_numbers([1, 2])

        tracker.reset()

        assert tracker.get_active_workspaces() == {}
        assert tracker.to_dict()["processed_issues"].get(str(1)) is None
        assert tracker.get_branch(1) is None
        assert tracker.to_dict()["reviewed_prs"].get(str(10)) is None
        assert tracker.get_hitl_origin(1) is None
        assert tracker.get_hitl_cause(1) is None
        assert tracker.get_issue_attempts(1) == 0
        assert tracker.get_active_issue_numbers() == []


# ---------------------------------------------------------------------------
# Corrupt file handling
# ---------------------------------------------------------------------------


class TestCorruptFileHandling:
    def test_corrupt_json_falls_back_to_defaults(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("{ this is not valid JSON }")

        # Should not raise; should silently reset to defaults
        tracker = StateTracker(state_file)
        assert tracker.get_active_workspaces() == {}

    def test_empty_file_falls_back_to_defaults(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("")

        tracker = StateTracker(state_file)
        assert tracker.get_active_workspaces() == {}

    def test_load_with_corrupt_file_falls_back_to_defaults(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "state.json"
        # Start with a valid tracker then corrupt it
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")

        state_file.write_text("{ bad json !!!")
        tracker.load()

        assert tracker.to_dict().get("processed_issues") == {}

    def test_null_state_file_returns_empty_state(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("null")

        # A state file containing 'null' (valid JSON but unexpected) should
        # not raise and should behave as if the state is empty.
        tracker = StateTracker(state_file)
        worktrees = tracker.get_active_workspaces()
        assert worktrees == {}
        assert tracker.to_dict().get("processed_issues") == {}


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_to_dict_returns_dict(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert isinstance(tracker.to_dict(), dict)

    def test_to_dict_contains_all_default_keys(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        d = tracker.to_dict()
        expected_keys = {
            "processed_issues",
            "active_workspaces",
            "active_branches",
            "reviewed_prs",
            "hitl_origins",
            "hitl_causes",
            "review_attempts",
            "review_feedback",
            "worker_result_meta",
            "issue_attempts",
            "active_issue_numbers",
            "lifetime_stats",
            "last_updated",
        }
        assert expected_keys.issubset(d.keys())

    def test_to_dict_returns_copy_not_reference(self, tmp_path: Path) -> None:
        """Mutating the returned dict must not affect the tracker's internal state."""
        tracker = make_tracker(tmp_path)
        d = tracker.to_dict()
        d["processed_issues"]["999"] = "hacked"
        assert tracker.to_dict()["processed_issues"].get("999") is None

    def test_to_dict_contains_lifetime_stats_key(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        d = tracker.to_dict()
        assert "lifetime_stats" in d

    def test_to_dict_reflects_current_state(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(7, "success")
        d = tracker.to_dict()
        assert d["processed_issues"]["7"] == "success"


# ---------------------------------------------------------------------------
# Lifetime stats
# ---------------------------------------------------------------------------


class TestLifetimeStats:
    def test_defaults_include_lifetime_stats(self, tmp_path: Path) -> None:
        """A fresh tracker should include zeroed lifetime_stats."""
        tracker = make_tracker(tmp_path)
        stats = tracker.get_lifetime_stats()
        assert stats.issues_completed == 0
        assert stats.prs_merged == 0
        assert stats.issues_created == 0
        assert stats.total_quality_fix_rounds == 0
        assert stats.total_ci_fix_rounds == 0
        assert stats.total_hitl_escalations == 0
        assert stats.total_review_request_changes == 0
        assert stats.total_review_approvals == 0
        assert stats.total_reviewer_fixes == 0
        assert stats.total_implementation_seconds == 0.0
        assert stats.total_review_seconds == 0.0

    def test_record_issue_completed_increments(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_issue_completed()
        assert tracker.get_lifetime_stats().issues_completed == 1

    def test_record_pr_merged_increments(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_pr_merged()
        assert tracker.get_lifetime_stats().prs_merged == 1

    def test_record_issue_created_increments(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_issue_created()
        assert tracker.get_lifetime_stats().issues_created == 1

    def test_multiple_increments_accumulate(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        for _ in range(3):
            tracker.record_pr_merged()
        assert tracker.get_lifetime_stats().prs_merged == 3

    def test_get_lifetime_stats_returns_copy(self, tmp_path: Path) -> None:
        """Mutating the returned model must not affect internal state."""
        tracker = make_tracker(tmp_path)
        tracker.record_issue_completed()
        stats = tracker.get_lifetime_stats()
        stats.issues_completed = 999
        assert tracker.get_lifetime_stats().issues_completed == 1

    def test_get_lifetime_stats_returns_lifetime_stats_instance(
        self, tmp_path: Path
    ) -> None:
        """get_lifetime_stats should return a LifetimeStats model instance."""
        tracker = make_tracker(tmp_path)
        result = tracker.get_lifetime_stats()
        assert isinstance(result, LifetimeStats)

    def test_lifetime_stats_persist_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.record_pr_merged()
        tracker.record_issue_created()
        tracker.record_issue_created()

        tracker2 = StateTracker(state_file)
        stats = tracker2.get_lifetime_stats()
        assert stats.prs_merged == 1
        assert stats.issues_created == 2

    def test_reset_preserves_lifetime_stats(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.record_pr_merged()
        tracker.record_issue_completed()
        tracker.record_issue_created()
        tracker.mark_issue(1, "success")

        tracker.reset()

        # Issues should be cleared
        assert tracker.to_dict()["processed_issues"].get(str(1)) is None
        # Lifetime stats should survive
        stats = tracker.get_lifetime_stats()
        assert stats.prs_merged == 1
        assert stats.issues_completed == 1
        assert stats.issues_created == 1

    def test_migration_adds_lifetime_stats_to_old_file(self, tmp_path: Path) -> None:
        """Loading a state file without lifetime_stats should inject zero defaults."""
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
        stats = tracker.get_lifetime_stats()
        assert stats.issues_completed == 0
        assert stats.prs_merged == 0
        assert stats.issues_created == 0
        assert stats.total_quality_fix_rounds == 0
        assert stats.total_hitl_escalations == 0
        # Existing data is preserved
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"
