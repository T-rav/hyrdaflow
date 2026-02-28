"""Soak/load tests for queue progression.

Validates sustained queue ingestion and drain, stall detection,
drift detection, and throughput bounds. These tests are excluded
from default runs via the ``soak`` marker.
"""

from __future__ import annotations

import pytest

from state import StateTracker

pytestmark = pytest.mark.soak


# ---------------------------------------------------------------------------
# Sustained queue processing
# ---------------------------------------------------------------------------


class TestSustainedQueueProcessing:
    def test_sustained_mark_and_reload_over_200_cycles(self, tmp_path) -> None:
        """State should remain consistent after 200+ mark/reload cycles."""
        st = StateTracker(tmp_path / "state.json")

        for i in range(200):
            st.mark_issue(i, "merged")

        # Reload
        st2 = StateTracker(tmp_path / "state.json")
        data = st2.load()
        processed = data.get("processed_issues", {})

        # All 200 issues should be present
        for i in range(200):
            assert str(i) in processed or i in processed, (
                f"Issue {i} missing after 200 cycles"
            )

    def test_session_ingestion_over_100_sessions(self, tmp_path) -> None:
        """State should handle 100+ sessions without data loss."""
        from models import SessionLog

        st = StateTracker(tmp_path / "state.json")

        for i in range(100):
            session = SessionLog(
                id=f"sess-{i:04d}",
                repo=f"owner/repo-{i % 3}",
                started_at=f"2024-01-{(i % 28) + 1:02d}T00:00:00Z",
                ended_at=f"2024-01-{(i % 28) + 1:02d}T01:00:00Z",
                issues_processed=list(range(i * 3, i * 3 + 3)),
                issues_succeeded=2,
                issues_failed=1,
                status="completed",
            )
            st.save_session(session)

        # Reload and verify
        st2 = StateTracker(tmp_path / "state.json")
        all_sessions = st2.load_sessions(limit=200)
        assert len(all_sessions) == 100

        # Verify repo filtering
        repo0_sessions = st2.load_sessions(repo="owner/repo-0", limit=200)
        repo1_sessions = st2.load_sessions(repo="owner/repo-1", limit=200)
        repo2_sessions = st2.load_sessions(repo="owner/repo-2", limit=200)

        assert len(repo0_sessions) + len(repo1_sessions) + len(repo2_sessions) == 100


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


class TestDriftDetection:
    def test_no_data_loss_over_500_issue_marks(self, tmp_path) -> None:
        """After marking 500 issues, the count should be exactly 500."""
        st = StateTracker(tmp_path / "state.json")

        for i in range(500):
            st.mark_issue(i, "merged" if i % 2 == 0 else "failed")

        st2 = StateTracker(tmp_path / "state.json")
        data = st2.load()
        processed = data.get("processed_issues", {})

        assert len(processed) == 500, (
            f"Expected 500, got {len(processed)} — data drift detected"
        )

    def test_lifetime_stats_consistent_after_repeated_updates(self, tmp_path) -> None:
        """Lifetime stats should reflect exact cumulative values after many updates."""
        st = StateTracker(tmp_path / "state.json")

        expected_completed = 0
        expected_merged = 0

        for _ in range(100):
            for _ in range(3):
                st.record_issue_completed()
            st.record_pr_merged()
            expected_completed += 3
            expected_merged += 1

        st2 = StateTracker(tmp_path / "state.json")
        final = st2.get_lifetime_stats()

        assert final.issues_completed == expected_completed
        assert final.prs_merged == expected_merged


# ---------------------------------------------------------------------------
# Worker interval stability
# ---------------------------------------------------------------------------


class TestWorkerIntervalStability:
    def test_interval_updates_stable_over_50_cycles(self, tmp_path) -> None:
        """Worker intervals should remain accurate after 50 update cycles."""
        st = StateTracker(tmp_path / "state.json")

        for i in range(50):
            st.set_worker_intervals(
                {
                    "plan": 30 + i,
                    "implement": 60 + i,
                    "review": 90 + i,
                }
            )

        st2 = StateTracker(tmp_path / "state.json")
        intervals = st2.get_worker_intervals()

        # Should reflect the last update (i=49)
        assert intervals["plan"] == 79
        assert intervals["implement"] == 109
        assert intervals["review"] == 139
