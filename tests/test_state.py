"""Tests for dx/hydraflow/state.py - StateTracker class."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from models import (
    BackgroundWorkerState,
    LifetimeStats,
    PendingReport,
    SessionLog,
    SessionStatus,
    StateData,
)
from state import StateTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tracker(tmp_path: Path, *, filename: str = "state.json") -> StateTracker:
    """Return a StateTracker backed by a temp file."""
    return StateTracker(tmp_path / filename)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    def test_defaults_when_no_file_exists(self, tmp_path: Path) -> None:
        """A fresh tracker with no backing file should start from defaults."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_active_worktrees() == {}
        assert tracker.to_dict()["processed_issues"].get(str(1)) is None
        assert tracker.get_branch(1) is None
        assert tracker.to_dict()["reviewed_prs"].get(str(1)) is None

    def test_defaults_structure_matches_expected_keys(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        d = tracker.to_dict()
        assert "processed_issues" in d
        assert "active_worktrees" in d
        assert "active_branches" in d
        assert "reviewed_prs" in d
        assert "last_updated" in d
        assert "bg_worker_states" in d
        assert "current_batch" not in d

    def test_loads_legacy_file_with_current_batch_field(self, tmp_path: Path) -> None:
        """Old state files containing current_batch should load without error."""
        state_file = tmp_path / "state.json"
        legacy_data = {
            "current_batch": 7,
            "processed_issues": {"3": "success"},
            "active_worktrees": {},
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
            "active_worktrees": {},
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

    def test_save_sets_last_updated(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.save()
        d = tracker.to_dict()
        assert d["last_updated"] is not None
        # Should be a valid ISO string
        assert "T" in d["last_updated"]

    def test_round_trip_preserves_data(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(10, "success")
        tracker.set_worktree(10, "/tmp/wt-10")
        tracker.set_branch(10, "agent/issue-10")
        tracker.mark_pr(99, "merged")

        # Load a second tracker from the same file
        tracker2 = StateTracker(state_file)
        assert tracker2.to_dict()["processed_issues"].get(str(10)) == "success"
        assert tracker2.get_active_worktrees() == {10: "/tmp/wt-10"}
        assert tracker2.get_branch(10) == "agent/issue-10"
        assert tracker2.to_dict()["reviewed_prs"].get(str(99)) == "merged"

    def test_explicit_load_returns_dict(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        result = tracker.load()
        assert isinstance(result, dict)


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
    def test_set_worktree_stores_path(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(7, "/tmp/wt-7")
        assert tracker.get_active_worktrees() == {7: "/tmp/wt-7"}

    def test_set_worktree_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_worktree(7, "/tmp/wt-7")
        assert state_file.exists()

    def test_remove_worktree_deletes_entry(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(7, "/tmp/wt-7")
        tracker.remove_worktree(7)
        assert 7 not in tracker.get_active_worktrees()

    def test_remove_worktree_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        # Should not raise
        tracker.remove_worktree(999)
        assert tracker.get_active_worktrees() == {}

    def test_get_active_worktrees_returns_int_keys(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(10, "/wt/10")
        tracker.set_worktree(20, "/wt/20")
        wt = tracker.get_active_worktrees()
        assert all(isinstance(k, int) for k in wt)

    def test_multiple_worktrees(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(1, "/wt/1")
        tracker.set_worktree(2, "/wt/2")
        assert tracker.get_active_worktrees() == {1: "/wt/1", 2: "/wt/2"}

    def test_remove_one_worktree_leaves_others(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(1, "/wt/1")
        tracker.set_worktree(2, "/wt/2")
        tracker.remove_worktree(1)
        assert tracker.get_active_worktrees() == {2: "/wt/2"}


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
            "active_worktrees": {},
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
            "active_worktrees": {},
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
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_processed_issues(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(1, "success")
        tracker.reset()
        assert tracker.to_dict()["processed_issues"].get(str(1)) is None

    def test_reset_clears_active_worktrees(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(1, "/wt/1")
        tracker.reset()
        assert tracker.get_active_worktrees() == {}

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
        tracker.set_worktree(1, "/wt/1")
        tracker.set_branch(1, "agent/issue-1")
        tracker.mark_pr(10, "open")
        tracker.set_hitl_origin(1, "hydraflow-review")
        tracker.set_hitl_cause(1, "CI failed after 2 fix attempts")
        tracker.increment_issue_attempts(1)
        tracker.set_active_issue_numbers([1, 2])

        tracker.reset()

        assert tracker.get_active_worktrees() == {}
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
        assert tracker.get_active_worktrees() == {}

    def test_empty_file_falls_back_to_defaults(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("")

        tracker = StateTracker(state_file)
        assert tracker.get_active_worktrees() == {}

    def test_load_with_corrupt_file_falls_back_to_defaults(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "state.json"
        # Start with a valid tracker then corrupt it
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")

        state_file.write_text("{ bad json !!!")
        result = tracker.load()

        assert isinstance(result, dict)
        assert result.get("processed_issues") == {}

    def test_corrupt_file_does_not_raise(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("null")

        # Constructing a tracker on a file containing 'null' should not raise
        try:
            tracker = StateTracker(state_file)
            _ = tracker.get_active_worktrees()
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Unexpected exception for corrupt file: {exc}")


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
            "active_worktrees",
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
            "active_worktrees": {},
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


# ---------------------------------------------------------------------------
# Atomic save
# ---------------------------------------------------------------------------


class TestAtomicSave:
    def test_save_uses_atomic_replace(self, tmp_path: Path) -> None:
        """save() should write to a temp file then atomically replace."""
        tracker = make_tracker(tmp_path)
        with patch("file_util.os.replace", wraps=os.replace) as mock_replace:
            tracker.save()
            mock_replace.assert_called_once()
            args = mock_replace.call_args[0]
            # Second arg should be the state file path
            assert str(args[1]) == str(tmp_path / "state.json")
            # First arg (temp file) should no longer exist after replace
            assert not Path(args[0]).exists()

    def test_save_cleans_up_temp_on_write_failure(self, tmp_path: Path) -> None:
        """If writing to the temp file fails, the temp file should be removed."""
        tracker = make_tracker(tmp_path)
        state_dir = tmp_path

        with (
            patch("file_util.os.fdopen", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            tracker.save()

        # No leftover temp files
        temps = list(state_dir.glob(".state-*.tmp"))
        assert temps == []

    def test_save_cleans_up_temp_on_fsync_failure(self, tmp_path: Path) -> None:
        """If fsync fails, the temp file should be cleaned up."""
        tracker = make_tracker(tmp_path)

        with (
            patch("file_util.os.fsync", side_effect=OSError("fsync failed")),
            pytest.raises(OSError, match="fsync failed"),
        ):
            tracker.save()

        temps = list(tmp_path.glob(".state-*.tmp"))
        assert temps == []

    def test_save_does_not_corrupt_existing_file_on_failure(
        self, tmp_path: Path
    ) -> None:
        """A failed save must leave the original state file intact."""
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")

        original_content = state_file.read_text()

        with (
            patch("file_util.os.fsync", side_effect=OSError("fsync failed")),
            pytest.raises(OSError),
        ):
            tracker.save()

        # Original file should be unchanged
        assert state_file.read_text() == original_content
        data = json.loads(state_file.read_text())
        assert data["processed_issues"]["1"] == "success"

    def test_no_temp_files_left_after_successful_save(self, tmp_path: Path) -> None:
        """After a normal save, no temp files should remain."""
        tracker = make_tracker(tmp_path)
        tracker.save()

        temps = list(tmp_path.glob(".state-*.tmp"))
        assert temps == []

    def test_save_temp_file_in_same_directory(self, tmp_path: Path) -> None:
        """The temp file must be created in the same dir as the state file."""
        tracker = make_tracker(tmp_path)
        with patch(
            "file_util.tempfile.mkstemp", wraps=__import__("tempfile").mkstemp
        ) as mock_mkstemp:
            tracker.save()
            mock_mkstemp.assert_called_once()
            kwargs = mock_mkstemp.call_args[1]
            assert str(kwargs["dir"]) == str(tmp_path)


# ---------------------------------------------------------------------------
# Review attempt tracking
# ---------------------------------------------------------------------------


class TestReviewAttemptTracking:
    def test_get_review_attempts_defaults_to_zero(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_review_attempts(42) == 0

    def test_increment_review_attempts_returns_new_count(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.increment_review_attempts(42) == 1
        assert tracker.increment_review_attempts(42) == 2

    def test_reset_review_attempts_clears_counter(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_review_attempts(42)
        tracker.increment_review_attempts(42)
        tracker.reset_review_attempts(42)
        assert tracker.get_review_attempts(42) == 0

    def test_reset_review_attempts_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.reset_review_attempts(999)
        assert tracker.get_review_attempts(999) == 0

    def test_multiple_issues_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_review_attempts(1)
        tracker.increment_review_attempts(1)
        tracker.increment_review_attempts(2)
        assert tracker.get_review_attempts(1) == 2
        assert tracker.get_review_attempts(2) == 1

    def test_review_attempts_persist_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.increment_review_attempts(42)
        tracker.increment_review_attempts(42)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_review_attempts(42) == 2

    def test_reset_clears_review_attempts(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.increment_review_attempts(42)
        tracker.reset()
        assert tracker.get_review_attempts(42) == 0


# ---------------------------------------------------------------------------
# Review feedback storage
# ---------------------------------------------------------------------------


class TestReviewFeedbackStorage:
    def test_set_and_get_review_feedback(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_review_feedback(42, "Fix the error handling")
        assert tracker.get_review_feedback(42) == "Fix the error handling"

    def test_get_review_feedback_returns_none_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_review_feedback(999) is None

    def test_clear_review_feedback(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_review_feedback(42, "Some feedback")
        tracker.clear_review_feedback(42)
        assert tracker.get_review_feedback(42) is None

    def test_clear_review_feedback_nonexistent_is_noop(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.clear_review_feedback(999)
        assert tracker.get_review_feedback(999) is None

    def test_review_feedback_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_review_feedback(42, "Needs more tests")

        tracker2 = StateTracker(state_file)
        assert tracker2.get_review_feedback(42) == "Needs more tests"

    def test_set_review_feedback_overwrites(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_review_feedback(42, "First feedback")
        tracker.set_review_feedback(42, "Updated feedback")
        assert tracker.get_review_feedback(42) == "Updated feedback"

    def test_reset_clears_review_feedback(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_review_feedback(42, "Some feedback")
        tracker.reset()
        assert tracker.get_review_feedback(42) is None


# ---------------------------------------------------------------------------
# StateData / LifetimeStats Pydantic models
# ---------------------------------------------------------------------------


class TestStateDataModel:
    def test_state_data_initializes_with_empty_collections_and_zero_counters(
        self,
    ) -> None:
        """StateData() should have correct zero/empty defaults."""
        data = StateData()
        assert data.processed_issues == {}
        assert data.active_worktrees == {}
        assert data.active_branches == {}
        assert data.reviewed_prs == {}
        assert data.hitl_origins == {}
        assert data.hitl_causes == {}
        assert data.review_attempts == {}
        assert data.review_feedback == {}
        assert data.worker_result_meta == {}
        assert data.issue_attempts == {}
        assert data.active_issue_numbers == []
        assert data.lifetime_stats == LifetimeStats()
        assert data.last_updated is None

    def test_validates_correct_data(self) -> None:
        """model_validate should accept a well-formed dict."""
        raw = {
            "processed_issues": {"1": "success"},
            "active_worktrees": {"2": "/wt/2"},
            "active_branches": {"2": "agent/issue-2"},
            "reviewed_prs": {"10": "merged"},
            "hitl_origins": {"42": "hydraflow-review"},
            "hitl_causes": {"42": "CI failed after 2 fix attempts"},
            "lifetime_stats": {
                "issues_completed": 3,
                "prs_merged": 1,
                "issues_created": 2,
            },
            "last_updated": "2025-01-01T00:00:00",
        }
        data = StateData.model_validate(raw)
        assert data.processed_issues["1"] == "success"
        assert data.hitl_causes["42"] == "CI failed after 2 fix attempts"
        assert data.lifetime_stats.prs_merged == 1

    def test_handles_partial_data(self) -> None:
        """Missing keys should get defaults — enables migration from old files."""
        data = StateData.model_validate({"processed_issues": {"1": "success"}})
        assert data.processed_issues == {"1": "success"}
        assert data.active_worktrees == {}
        assert data.lifetime_stats.issues_completed == 0

    def test_rejects_wrong_types(self) -> None:
        """Pydantic should reject structurally invalid data."""
        with pytest.raises(ValidationError):
            StateData.model_validate({"processed_issues": "not_a_dict"})

    def test_model_dump_roundtrip(self) -> None:
        """model_dump_json → model_validate_json should round-trip."""
        original = StateData(
            processed_issues={"1": "success"},
            lifetime_stats=LifetimeStats(issues_completed=5),
        )
        json_str = original.model_dump_json()
        restored = StateData.model_validate_json(json_str)
        assert restored == original

    def test_save_writes_model_dump_json(self, tmp_path: Path) -> None:
        """The saved file should be parseable by StateData.model_validate_json."""
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(1, "success")
        tracker.record_pr_merged()

        raw = (tmp_path / "state.json").read_text()
        restored = StateData.model_validate_json(raw)
        assert restored.processed_issues["1"] == "success"
        assert restored.lifetime_stats.prs_merged == 1


class TestWorkerResultMeta:
    """Tests for worker result metadata tracking."""

    def test_set_and_get_worker_result_meta(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        meta = {"quality_fix_attempts": 2, "duration_seconds": 120.5, "error": None}
        tracker.set_worker_result_meta(42, meta)
        assert tracker.get_worker_result_meta(42) == meta

    def test_get_returns_empty_for_unknown(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_worker_result_meta(999) == {}

    def test_set_triggers_save(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.set_worker_result_meta(42, {"quality_fix_attempts": 1})
        assert state_file.exists()

    def test_persists_across_reload(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        meta = {"quality_fix_attempts": 3, "duration_seconds": 200.0}
        tracker.set_worker_result_meta(42, meta)

        tracker2 = StateTracker(state_file)
        assert tracker2.get_worker_result_meta(42) == meta

    def test_multiple_issues_tracked_independently(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worker_result_meta(1, {"quality_fix_attempts": 0})
        tracker.set_worker_result_meta(2, {"quality_fix_attempts": 3})
        assert tracker.get_worker_result_meta(1) == {"quality_fix_attempts": 0}
        assert tracker.get_worker_result_meta(2) == {"quality_fix_attempts": 3}

    def test_overwrites_previous_meta(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worker_result_meta(42, {"quality_fix_attempts": 1})
        tracker.set_worker_result_meta(42, {"quality_fix_attempts": 5})
        assert tracker.get_worker_result_meta(42) == {"quality_fix_attempts": 5}

    def test_migration_adds_worker_result_meta_to_old_file(
        self, tmp_path: Path
    ) -> None:
        """Loading a state file without worker_result_meta should default to {}."""
        state_file = tmp_path / "state.json"
        old_data = {
            "processed_issues": {"1": "success"},
            "active_worktrees": {},
            "active_branches": {},
            "reviewed_prs": {},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(old_data))

        tracker = StateTracker(state_file)
        assert tracker.get_worker_result_meta(42) == {}
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"


class TestLifetimeStatsModel:
    def test_lifetime_stats_initializes_all_counters_to_zero(self) -> None:
        stats = LifetimeStats()
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
        assert stats.fired_thresholds == []

    def test_model_copy_is_independent(self) -> None:
        """model_copy should produce an independent instance."""
        stats = LifetimeStats(issues_completed=5)
        copy = stats.model_copy()
        copy.issues_completed = 99
        assert stats.issues_completed == 5


# ---------------------------------------------------------------------------
# New recording methods
# ---------------------------------------------------------------------------


class TestRecordingMethods:
    """Tests for the new lifetime stats recording methods."""

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
    """Tests for metrics state tracking methods."""

    def test_get_metrics_issue_number_default(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_metrics_issue_number() is None

    def test_set_and_get_metrics_issue_number(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_metrics_issue_number(42)
        assert tracker.get_metrics_issue_number() == 42

    def test_get_metrics_state_default(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        issue_num, hash_val, synced = tracker.get_metrics_state()
        assert issue_num is None
        assert hash_val == ""
        assert synced is None

    def test_update_metrics_state(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_metrics_issue_number(99)
        tracker.update_metrics_state("abc123")
        issue_num, hash_val, synced = tracker.get_metrics_state()
        assert issue_num == 99
        assert hash_val == "abc123"
        assert synced is not None

    def test_metrics_state_persists_across_reloads(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_metrics_issue_number(77)
        tracker.update_metrics_state("def456")

        tracker2 = make_tracker(tmp_path)
        issue_num, hash_val, synced = tracker2.get_metrics_state()
        assert issue_num == 77
        assert hash_val == "def456"
        assert synced is not None


# ---------------------------------------------------------------------------
# Threshold tracking
# ---------------------------------------------------------------------------


class TestThresholdTracking:
    """Tests for threshold-based improvement proposal logic."""

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
        # 1 approval, 4 request-changes → rate = 1/5 = 0.2 < 0.5
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
        # rate = 0/5 = 0.0 < 0.5 → recovered
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
    """Tests for verification issue state tracking."""

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
            "active_worktrees": {},
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
            "active_worktrees": {},
            "active_branches": {},
            "reviewed_prs": {},
            "last_updated": None,
        }
        state_file.write_text(json.dumps(old_data))

        tracker = StateTracker(state_file)
        assert tracker.get_active_issue_numbers() == []
        assert tracker.to_dict()["processed_issues"].get(str(1)) == "success"


class TestWorkerIntervals:
    """Tests for worker interval override persistence."""

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
    """Tests for time-to-merge tracking."""

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
    """Tests for retry-per-stage tracking."""

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
    """Tests for set/get/clear_last_reviewed_sha."""

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


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


def _make_session(session_id: str, repo: str = "org/repo") -> SessionLog:
    return SessionLog(
        id=session_id,
        repo=repo,
        started_at="2024-01-01T00:00:00",
        status=SessionStatus.COMPLETED,
    )


def _write_sessions(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


class TestLoadSessionsCorruptLines:
    """Verify load_sessions skips corrupt JSONL lines with warning+exc_info."""

    def test_skips_corrupt_lines_returns_valid(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt lines are skipped; valid sessions are still returned."""
        import logging

        tracker = make_tracker(tmp_path)
        session = _make_session("sess-1")
        sessions_path = tracker._sessions_path
        _write_sessions(
            sessions_path,
            [session.model_dump_json(), "corrupt garbage", session.model_dump_json()],
        )

        with caplog.at_level(logging.WARNING, logger="hydraflow.state"):
            result = tracker.load_sessions()

        assert len(result) == 1
        assert result[0].id == "sess-1"
        assert "Skipping corrupt session line" in caplog.text
        warning_records = [r for r in caplog.records if r.exc_info is not None]
        assert len(warning_records) >= 1

    def test_corrupt_only_returns_empty(self, tmp_path: Path) -> None:
        """A sessions file with only corrupt lines returns an empty list."""
        tracker = make_tracker(tmp_path)
        _write_sessions(tracker._sessions_path, ["bad line", "also bad"])

        result = tracker.load_sessions()
        assert result == []


class TestGetSessionCorruptLines:
    """Verify get_session skips corrupt JSONL lines with debug logging."""

    def test_skips_corrupt_line_finds_valid(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt lines are skipped; the target session is still found."""
        import logging

        tracker = make_tracker(tmp_path)
        session = _make_session("sess-2")
        sessions_path = tracker._sessions_path
        _write_sessions(
            sessions_path,
            ["corrupt garbage", session.model_dump_json()],
        )

        with caplog.at_level(logging.DEBUG, logger="hydraflow.state"):
            result = tracker.get_session("sess-2")

        assert result is not None
        assert result.id == "sess-2"
        assert "Skipping corrupt session line" in caplog.text

    def test_corrupt_only_returns_none(self, tmp_path: Path) -> None:
        """A sessions file with only corrupt lines returns None."""
        tracker = make_tracker(tmp_path)
        _write_sessions(tracker._sessions_path, ["bad", "worse"])

        assert tracker.get_session("any-id") is None


class TestDeleteSessionCorruptLines:
    """Verify delete_session skips corrupt JSONL lines with debug logging."""

    def test_skips_corrupt_line_deletes_target(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt lines are skipped; the target session is still deleted."""
        import logging

        tracker = make_tracker(tmp_path)
        session = _make_session("sess-3")
        sessions_path = tracker._sessions_path
        _write_sessions(
            sessions_path,
            ["corrupt garbage", session.model_dump_json()],
        )

        with caplog.at_level(logging.DEBUG, logger="hydraflow.state"):
            deleted = tracker.delete_session("sess-3")

        assert deleted is True
        assert "Skipping corrupt session line" in caplog.text


class TestPruneSessionsCorruptLines:
    """Verify prune_sessions skips corrupt JSONL lines with debug logging."""

    def test_skips_corrupt_lines_preserves_valid(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt lines are skipped; valid sessions are preserved."""
        import logging

        tracker = make_tracker(tmp_path)
        session = _make_session("sess-4")
        sessions_path = tracker._sessions_path
        _write_sessions(
            sessions_path,
            ["corrupt garbage", session.model_dump_json()],
        )

        with caplog.at_level(logging.DEBUG, logger="hydraflow.state"):
            tracker.prune_sessions("org/repo", max_keep=10)

        assert "Skipping corrupt session line" in caplog.text
        # Valid session should survive pruning
        result = tracker.load_sessions()
        assert any(s.id == "sess-4" for s in result)


# ---------------------------------------------------------------------------
# UnicodeDecodeError handling in load() (issue #1038)
# ---------------------------------------------------------------------------


class TestLoadUnicodeDecodeError:
    """Verify load() catches UnicodeDecodeError from binary-corrupted state files."""

    def test_load_recovers_from_binary_corrupted_state_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Binary data in state file should reset to defaults with a warning."""
        import logging

        state_file = tmp_path / "state.json"
        state_file.write_bytes(b"\x80\x81\x82\xff\xfe")

        with caplog.at_level(logging.WARNING, logger="hydraflow.state"):
            tracker = make_tracker(tmp_path)

        assert "Corrupt state file, resetting" in caplog.text
        # Should have default state
        assert tracker.get_active_worktrees() == {}
        assert tracker.to_dict()["processed_issues"] == {}


# ---------------------------------------------------------------------------
# OSError handling in save_session / _load_sessions_deduped (issue #1038)
# ---------------------------------------------------------------------------


class TestSaveSessionOSError:
    """Verify save_session catches OSError gracefully."""

    def test_save_session_logs_warning_on_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the sessions file can't be written, log warning and don't raise."""
        import logging

        tracker = make_tracker(tmp_path)
        session = _make_session("sess-err")

        with (
            patch("builtins.open", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.state"),
        ):
            tracker.save_session(session)  # should not raise

        assert "Could not save session to" in caplog.text

    def test_save_session_handles_mkdir_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When mkdir fails with PermissionError, log warning and don't raise."""
        import logging

        tracker = make_tracker(tmp_path)
        session = _make_session("sess-err")

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("not allowed")),
            caplog.at_level(logging.WARNING, logger="hydraflow.state"),
        ):
            tracker.save_session(session)  # should not raise

        assert "Could not save session to" in caplog.text


class TestLoadSessionsDedupedOSError:
    """Verify _load_sessions_deduped catches OSError and UnicodeDecodeError gracefully."""

    def test_load_sessions_deduped_returns_empty_on_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When sessions file can't be opened, return empty dict with warning."""
        import logging

        tracker = make_tracker(tmp_path)
        # Create the file so exists() check passes (_sessions_path is sibling to state.json)
        sessions_path = tracker._sessions_path
        sessions_path.parent.mkdir(parents=True, exist_ok=True)
        sessions_path.write_text("")

        with (
            patch("builtins.open", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.state"),
        ):
            result = tracker._load_sessions_deduped()

        assert result == {}
        assert "Could not open sessions file" in caplog.text

    def test_load_sessions_deduped_returns_empty_on_unicode_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When sessions file contains binary data, return empty dict with warning."""
        import logging

        tracker = make_tracker(tmp_path)
        sessions_path = tracker._sessions_path
        sessions_path.parent.mkdir(parents=True, exist_ok=True)
        sessions_path.write_bytes(b"\x80\x81\x82\xff\xfe")

        with caplog.at_level(logging.WARNING, logger="hydraflow.state"):
            result = tracker._load_sessions_deduped()

        assert result == {}
        assert "Could not open sessions file" in caplog.text


# --- save_session ---


class TestSaveSession:
    """Tests for StateTracker.save_session."""

    def test_save_session_creates_file(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        session = SessionLog(
            id="s1", repo="test-org/test-repo", started_at="2024-01-01T00:00:00Z"
        )
        tracker.save_session(session)
        assert tracker._sessions_path.exists()

    def test_save_session_appends_json(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        s1 = SessionLog(
            id="s1", repo="test-org/test-repo", started_at="2024-01-01T00:00:00Z"
        )
        s2 = SessionLog(
            id="s2", repo="test-org/test-repo", started_at="2024-01-01T00:01:00Z"
        )
        tracker.save_session(s1)
        tracker.save_session(s2)
        lines = tracker._sessions_path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_save_session_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "state.json"
        tracker = StateTracker(nested)
        session = SessionLog(
            id="s1", repo="test-org/test-repo", started_at="2024-01-01T00:00:00Z"
        )
        tracker.save_session(session)
        assert tracker._sessions_path.exists()

    def test_save_session_roundtrip_with_load(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        session = SessionLog(
            id="s1", repo="test-org/test-repo", started_at="2024-01-01T00:00:00Z"
        )
        tracker.save_session(session)
        loaded = tracker.load_sessions()
        assert len(loaded) == 1
        assert loaded[0].id == "s1"


# --- Memory State ---


class TestMemoryState:
    """Tests for get_memory_state / update_memory_state."""

    def test_get_memory_state_defaults(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        issue_ids, digest_hash, last_synced = tracker.get_memory_state()
        assert issue_ids == []
        assert digest_hash == ""
        assert last_synced is None

    def test_update_memory_state_persists(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_memory_state([1, 2, 3], "abc123")
        issue_ids, digest_hash, last_synced = tracker.get_memory_state()
        assert issue_ids == [1, 2, 3]
        assert digest_hash == "abc123"

    def test_update_memory_state_sets_timestamp(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_memory_state([1], "hash")
        _, _, last_synced = tracker.get_memory_state()
        assert last_synced is not None
        assert "T" in last_synced  # ISO format

    def test_get_memory_state_returns_copy(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_memory_state([1, 2], "hash")
        ids1, _, _ = tracker.get_memory_state()
        ids2, _, _ = tracker.get_memory_state()
        ids1.append(99)
        assert 99 not in ids2

    def test_update_memory_state_overwrites(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_memory_state([1], "first")
        tracker.update_memory_state([2, 3], "second")
        issue_ids, digest_hash, _ = tracker.get_memory_state()
        assert issue_ids == [2, 3]
        assert digest_hash == "second"


# --- Manifest State ---


class TestManifestState:
    """Tests for get_manifest_state / update_manifest_state."""

    def test_get_manifest_state_defaults(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        manifest_hash, last_updated = tracker.get_manifest_state()
        assert manifest_hash == ""
        assert last_updated is None

    def test_update_manifest_state_persists(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_manifest_state("hash123")
        manifest_hash, last_updated = tracker.get_manifest_state()
        assert manifest_hash == "hash123"

    def test_update_manifest_state_sets_timestamp(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_manifest_state("hash")
        _, last_updated = tracker.get_manifest_state()
        assert last_updated is not None
        assert "T" in last_updated

    def test_update_manifest_state_overwrites(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.update_manifest_state("first")
        tracker.update_manifest_state("second")
        manifest_hash, _ = tracker.get_manifest_state()
        assert manifest_hash == "second"


# --- Interrupted Issues ---


class TestInterruptedIssues:
    """Tests for get/set/clear_interrupted_issues."""

    def test_get_interrupted_issues_defaults_empty(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_interrupted_issues() == {}

    def test_set_and_get_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({42: "plan", 99: "review"})
        result = tracker.get_interrupted_issues()
        assert result == {42: "plan", 99: "review"}

    def test_int_keys_serialized_as_strings(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({42: "plan"})
        # Check raw state data has string keys
        assert "42" in tracker._data.interrupted_issues

    def test_get_converts_back_to_int_keys(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({42: "plan"})
        result = tracker.get_interrupted_issues()
        assert 42 in result
        assert isinstance(list(result.keys())[0], int)

    def test_clear_removes_all(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({42: "plan", 99: "review"})
        tracker.clear_interrupted_issues()
        assert tracker.get_interrupted_issues() == {}

    def test_persist_across_reload(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({42: "implement"})
        # Reload from disk
        tracker2 = make_tracker(tmp_path)
        result = tracker2.get_interrupted_issues()
        assert result == {42: "implement"}

    def test_set_overwrites_previous(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({42: "plan"})
        tracker.set_interrupted_issues({99: "review"})
        result = tracker.get_interrupted_issues()
        assert result == {99: "review"}
        assert 42 not in result


class TestPendingReports:
    """Tests for pending report queue operations."""

    def test_enqueue_appends_report(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        report = PendingReport(description="Bug A")
        tracker.enqueue_report(report)
        reports = tracker.get_pending_reports()
        assert len(reports) == 1
        assert reports[0].description == "Bug A"

    def test_dequeue_returns_fifo_order(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        r1 = PendingReport(description="First")
        r2 = PendingReport(description="Second")
        tracker.enqueue_report(r1)
        tracker.enqueue_report(r2)

        dequeued = tracker.dequeue_report()
        assert dequeued is not None
        assert dequeued.description == "First"

        dequeued2 = tracker.dequeue_report()
        assert dequeued2 is not None
        assert dequeued2.description == "Second"

    def test_dequeue_empty_returns_none(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.dequeue_report() is None

    def test_get_pending_reports_returns_copy(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        report = PendingReport(description="Test")
        tracker.enqueue_report(report)
        copy = tracker.get_pending_reports()
        copy.clear()
        assert len(tracker.get_pending_reports()) == 1

    def test_enqueue_persists_to_disk(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        report = PendingReport(description="Persist test")
        tracker.enqueue_report(report)

        tracker2 = make_tracker(tmp_path)
        reports = tracker2.get_pending_reports()
        assert len(reports) == 1
        assert reports[0].description == "Persist test"


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
# Outcome tracking — additional coverage
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
        # No assertion failure means success

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
        # 4 triaged / ~2 hours ≈ 2.0/hr (allow some tolerance for test timing)
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
