"""Tests for StateTracker int↔str key conversion helpers and state roundtrip."""

from __future__ import annotations

import json
from pathlib import Path

from state import StateTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tracker(tmp_path: Path) -> StateTracker:
    """Return a StateTracker backed by a temp file."""
    return StateTracker(tmp_path / "state.json")


# ---------------------------------------------------------------------------
# _key() tests
# ---------------------------------------------------------------------------


class TestKey:
    """Tests for StateTracker._key() static helper."""

    def test_converts_int_to_str(self) -> None:
        assert StateTracker._key(42) == "42"

    def test_zero(self) -> None:
        assert StateTracker._key(0) == "0"

    def test_large_number(self) -> None:
        assert StateTracker._key(999999) == "999999"

    def test_negative_number(self) -> None:
        assert StateTracker._key(-1) == "-1"

    def test_returns_str_type(self) -> None:
        result = StateTracker._key(7)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _int_keys() tests
# ---------------------------------------------------------------------------


class TestIntKeys:
    """Tests for StateTracker._int_keys() static helper."""

    def test_converts_string_keys_to_int(self) -> None:
        result = StateTracker._int_keys({"1": "a", "2": "b"})
        assert result == {1: "a", 2: "b"}

    def test_empty_dict(self) -> None:
        result = StateTracker._int_keys({})
        assert result == {}

    def test_preserves_values(self) -> None:
        result = StateTracker._int_keys({"10": 42, "20": 99})
        assert result == {10: 42, 20: 99}

    def test_returns_new_dict(self) -> None:
        original: dict[str, str] = {"1": "x"}
        result = StateTracker._int_keys(original)
        assert result is not original
        assert result == {1: "x"}

    def test_single_entry(self) -> None:
        result = StateTracker._int_keys({"5": "val"})
        assert result == {5: "val"}


# ---------------------------------------------------------------------------
# Integration: helpers are used by accessor methods
# ---------------------------------------------------------------------------


class TestAccessorMethodsUseHelpers:
    """Verify that StateTracker accessor methods correctly use the helpers."""

    def test_mark_issue_uses_string_key(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_issue(42, "triaged")
        raw = tracker.to_dict()
        assert "42" in raw["processed_issues"]
        assert raw["processed_issues"]["42"] == "triaged"

    def test_set_and_get_worktree(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(10, "/tmp/wt-10")
        worktrees = tracker.get_active_worktrees()
        assert worktrees == {10: "/tmp/wt-10"}

    def test_remove_worktree(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(10, "/tmp/wt-10")
        tracker.remove_worktree(10)
        assert tracker.get_active_worktrees() == {}

    def test_set_and_get_branch(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_branch(5, "issue-5")
        assert tracker.get_branch(5) == "issue-5"

    def test_get_branch_missing(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_branch(999) is None

    def test_mark_pr_uses_string_key(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.mark_pr(100, "approved")
        raw = tracker.to_dict()
        assert "100" in raw["reviewed_prs"]

    def test_hitl_origin_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_origin(7, "hydraflow-review")
        assert tracker.get_hitl_origin(7) == "hydraflow-review"
        tracker.remove_hitl_origin(7)
        assert tracker.get_hitl_origin(7) is None

    def test_hitl_cause_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_hitl_cause(8, "ci_failure")
        assert tracker.get_hitl_cause(8) == "ci_failure"
        tracker.remove_hitl_cause(8)
        assert tracker.get_hitl_cause(8) is None

    def test_review_attempts_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_review_attempts(3) == 0
        count = tracker.increment_review_attempts(3)
        assert count == 1
        assert tracker.get_review_attempts(3) == 1
        tracker.reset_review_attempts(3)
        assert tracker.get_review_attempts(3) == 0

    def test_issue_attempts_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        assert tracker.get_issue_attempts(4) == 0
        count = tracker.increment_issue_attempts(4)
        assert count == 1
        assert tracker.get_issue_attempts(4) == 1
        tracker.reset_issue_attempts(4)
        assert tracker.get_issue_attempts(4) == 0

    def test_verification_issue_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_verification_issue(10, 20)
        assert tracker.get_verification_issue(10) == 20
        all_verifs = tracker.get_all_verification_issues()
        assert all_verifs == {10: 20}
        tracker.clear_verification_issue(10)
        assert tracker.get_verification_issue(10) is None

    def test_interrupted_issues_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_interrupted_issues({1: "plan", 2: "implement"})
        result = tracker.get_interrupted_issues()
        assert result == {1: "plan", 2: "implement"}
        tracker.clear_interrupted_issues()
        assert tracker.get_interrupted_issues() == {}

    def test_last_reviewed_sha_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_last_reviewed_sha(15, "abc123")
        assert tracker.get_last_reviewed_sha(15) == "abc123"
        tracker.clear_last_reviewed_sha(15)
        assert tracker.get_last_reviewed_sha(15) is None

    def test_review_feedback_roundtrip(self, tmp_path: Path) -> None:
        tracker = make_tracker(tmp_path)
        tracker.set_review_feedback(6, "needs refactor")
        assert tracker.get_review_feedback(6) == "needs refactor"
        tracker.clear_review_feedback(6)
        assert tracker.get_review_feedback(6) is None


# ---------------------------------------------------------------------------
# State roundtrip: save → load → verify
# ---------------------------------------------------------------------------


class TestStateRoundtrip:
    """Verify that state persists correctly through save/load cycles."""

    def test_full_roundtrip(self, tmp_path: Path) -> None:
        """Save state with multiple int-keyed fields, reload, and verify."""
        tracker = make_tracker(tmp_path)

        # Populate various int-keyed fields
        tracker.mark_issue(1, "triaged")
        tracker.set_worktree(2, "/tmp/wt-2")
        tracker.set_branch(3, "issue-3")
        tracker.mark_pr(4, "approved")
        tracker.set_hitl_origin(5, "hydraflow-implement")
        tracker.set_hitl_cause(6, "timeout")
        tracker.increment_review_attempts(7)
        tracker.increment_review_attempts(7)
        tracker.increment_issue_attempts(8)
        tracker.set_verification_issue(9, 19)
        tracker.set_interrupted_issues({10: "review"})
        tracker.set_last_reviewed_sha(11, "deadbeef")
        tracker.set_review_feedback(12, "looks good")

        # Reload from disk
        tracker2 = StateTracker(tmp_path / "state.json")

        # Verify all fields roundtrip correctly
        assert tracker2.to_dict()["processed_issues"]["1"] == "triaged"
        assert tracker2.get_active_worktrees() == {2: "/tmp/wt-2"}
        assert tracker2.get_branch(3) == "issue-3"
        assert tracker2.to_dict()["reviewed_prs"]["4"] == "approved"
        assert tracker2.get_hitl_origin(5) == "hydraflow-implement"
        assert tracker2.get_hitl_cause(6) == "timeout"
        assert tracker2.get_review_attempts(7) == 2
        assert tracker2.get_issue_attempts(8) == 1
        assert tracker2.get_verification_issue(9) == 19
        assert tracker2.get_interrupted_issues() == {10: "review"}
        assert tracker2.get_last_reviewed_sha(11) == "deadbeef"
        assert tracker2.get_review_feedback(12) == "looks good"

    def test_json_uses_string_keys(self, tmp_path: Path) -> None:
        """Verify the persisted JSON file uses string keys (backwards compat)."""
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(42, "/tmp/wt-42")
        tracker.increment_review_attempts(99)

        raw = json.loads((tmp_path / "state.json").read_text())
        # JSON keys must be strings
        assert "42" in raw["active_worktrees"]
        assert "99" in raw["review_attempts"]
        # int keys should NOT appear
        assert 42 not in raw["active_worktrees"]
        assert 99 not in raw["review_attempts"]

    def test_multiple_entries_roundtrip(self, tmp_path: Path) -> None:
        """Multiple entries in the same dict field survive roundtrip."""
        tracker = make_tracker(tmp_path)
        tracker.set_worktree(1, "/a")
        tracker.set_worktree(2, "/b")
        tracker.set_worktree(3, "/c")

        tracker2 = StateTracker(tmp_path / "state.json")
        wts = tracker2.get_active_worktrees()
        assert wts == {1: "/a", 2: "/b", 3: "/c"}
