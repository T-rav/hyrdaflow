"""Restart/resume tests for per-repo state persistence.

Validates that worker intervals, active issues, sessions,
lifetime stats, and processed issue records survive across
simulated stop/start cycles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from models import SessionLog

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(repo: str, session_id: str, *, succeeded: int = 1) -> SessionLog:
    return SessionLog(
        id=session_id,
        repo=repo,
        started_at="2024-03-15T14:00:00Z",
        ended_at="2024-03-15T15:00:00Z",
        issues_processed=[1, 2, 3],
        issues_succeeded=succeeded,
        issues_failed=0,
        status="completed",
    )


# ---------------------------------------------------------------------------
# Worker interval persistence
# ---------------------------------------------------------------------------


class TestWorkerIntervalPersistence:
    def test_worker_intervals_survive_restart(self, tmp_path: Path) -> None:
        """Custom worker intervals should persist across StateTracker recreation."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)
        st1.set_worker_intervals({"plan": 45, "implement": 120, "review": 60})

        # Simulate restart: create new StateTracker on same file
        st2 = StateTracker(state_file)
        intervals = st2.get_worker_intervals()

        assert intervals["plan"] == 45
        assert intervals["implement"] == 120
        assert intervals["review"] == 60


# ---------------------------------------------------------------------------
# Active issue crash recovery
# ---------------------------------------------------------------------------


class TestActiveIssueCrashRecovery:
    def test_active_issues_survive_restart(self, tmp_path: Path) -> None:
        """Active issue numbers should persist across restarts."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)
        st1.set_active_issue_numbers([10, 20, 30])

        st2 = StateTracker(state_file)
        numbers = st2.get_active_issue_numbers()

        assert set(numbers) == {10, 20, 30}

    def test_empty_active_issues_preserved(self, tmp_path: Path) -> None:
        """An explicitly empty active list should stay empty after restart."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)
        st1.set_active_issue_numbers([10, 20])
        st1.set_active_issue_numbers([])

        st2 = StateTracker(state_file)
        assert st2.get_active_issue_numbers() == []


# ---------------------------------------------------------------------------
# Session continuity
# ---------------------------------------------------------------------------


class TestSessionContinuity:
    def test_sessions_survive_restart(self, tmp_path: Path) -> None:
        """Sessions saved before restart should be loadable after restart."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)

        st1.save_session(_make_session("owner/repo-alpha", "sess-1", succeeded=3))
        st1.save_session(_make_session("owner/repo-alpha", "sess-2", succeeded=5))
        st1.save_session(_make_session("owner/repo-beta", "sess-3", succeeded=2))

        # Simulate restart
        st2 = StateTracker(state_file)

        alpha_sessions = st2.load_sessions(repo="owner/repo-alpha")
        beta_sessions = st2.load_sessions(repo="owner/repo-beta")
        all_sessions = st2.load_sessions()

        assert len(alpha_sessions) == 2
        assert len(beta_sessions) == 1
        assert len(all_sessions) == 3

    def test_session_metadata_preserved(self, tmp_path: Path) -> None:
        """Session fields should be preserved exactly across restart."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        original = _make_session("owner/repo-alpha", "detailed-sess", succeeded=7)
        original.issues_processed = [10, 20, 30, 40, 50, 60, 70]
        original.issues_failed = 2

        st1 = StateTracker(state_file)
        st1.save_session(original)

        st2 = StateTracker(state_file)
        loaded = st2.load_sessions(repo="owner/repo-alpha")

        assert len(loaded) == 1
        sess = loaded[0]
        assert sess.id == "detailed-sess"
        assert sess.issues_succeeded == 7
        assert sess.issues_failed == 2
        assert len(sess.issues_processed) == 7


# ---------------------------------------------------------------------------
# Lifetime stats persistence
# ---------------------------------------------------------------------------


class TestLifetimeStatsPersistence:
    def test_per_repo_counters_accurate_after_recovery(self, tmp_path: Path) -> None:
        """Lifetime stats should survive restart with exact values."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)

        for _ in range(15):
            st1.record_issue_completed()
        for _ in range(8):
            st1.record_pr_merged()
        for _ in range(3):
            st1.record_hitl_escalation()

        # Simulate restart
        st2 = StateTracker(state_file)
        restored = st2.get_lifetime_stats()

        assert restored.issues_completed == 15
        assert restored.prs_merged == 8
        assert restored.total_hitl_escalations == 3

    def test_zero_stats_preserved(self, tmp_path: Path) -> None:
        """A fresh state should have all-zero lifetime stats after restart."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)
        # Force a save by marking an issue
        st1.mark_issue(9999, "merged")

        st2 = StateTracker(state_file)
        stats = st2.get_lifetime_stats()

        assert stats.issues_completed == 0
        assert stats.prs_merged == 0


# ---------------------------------------------------------------------------
# Processed issues persistence
# ---------------------------------------------------------------------------


class TestProcessedIssuesPersistence:
    def test_processed_issues_survive_restart(self, tmp_path: Path) -> None:
        """Processed issue records should persist across restarts."""
        from state import StateTracker

        state_file = tmp_path / "state.json"
        st1 = StateTracker(state_file)
        st1.mark_issue(42, "merged")
        st1.mark_issue(99, "failed")

        st2 = StateTracker(state_file)
        data = st2.load()
        processed = data.get("processed_issues", {})

        assert str(42) in processed or 42 in processed
        assert str(99) in processed or 99 in processed
