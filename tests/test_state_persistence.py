"""Tests for state -- persistence and data models."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from models import LifetimeStats, StateData
from state import StateTracker
from tests.helpers import make_tracker

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
        """Missing keys should get defaults -- enables migration from old files."""
        data = StateData.model_validate({"processed_issues": {"1": "success"}})
        assert data.processed_issues == {"1": "success"}
        assert data.active_worktrees == {}
        assert data.lifetime_stats.issues_completed == 0

    def test_rejects_wrong_types(self) -> None:
        """Pydantic should reject structurally invalid data."""
        with pytest.raises(ValidationError):
            StateData.model_validate({"processed_issues": "not_a_dict"})

    def test_model_dump_roundtrip(self) -> None:
        """model_dump_json -> model_validate_json should round-trip."""
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
