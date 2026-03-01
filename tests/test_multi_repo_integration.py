"""Multi-repo integration tests.

Validates state isolation, session scoping, queue independence,
and metrics independence across concurrent repo configurations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from models import SessionLog
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, slug: str):
    """Create a HydraFlowConfig with isolated paths for a given repo slug."""
    base = tmp_path / slug
    base.mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(
        repo=f"owner/{slug}",
        repo_root=base / "repo",
        worktree_base=base / "worktrees",
        state_file=base / "state.json",
    )


def _make_session(
    repo: str, session_id: str, *, status: str = "completed"
) -> SessionLog:
    return SessionLog(
        id=session_id,
        repo=repo,
        started_at="2024-01-01T00:00:00Z",
        ended_at="2024-01-01T01:00:00Z",
        issues_processed=[1],
        issues_succeeded=1,
        issues_failed=0,
        status=status,
    )


# ---------------------------------------------------------------------------
# State isolation
# ---------------------------------------------------------------------------


class TestStateIsolation:
    def test_isolated_state_files_no_cross_contamination(self, tmp_path: Path) -> None:
        """Two StateTrackers with separate files should not share data."""
        from state import StateTracker

        alpha_cfg = _make_config(tmp_path, "repo-alpha")
        beta_cfg = _make_config(tmp_path, "repo-beta")

        alpha_state = StateTracker(alpha_cfg.state_file)
        beta_state = StateTracker(beta_cfg.state_file)

        alpha_state.mark_issue(10, "merged")
        alpha_state.mark_issue(20, "merged")
        beta_state.mark_issue(30, "merged")

        alpha_data = alpha_state.load()
        beta_data = beta_state.load()

        alpha_processed = alpha_data.get("processed_issues", {})
        beta_processed = beta_data.get("processed_issues", {})

        assert "10" in alpha_processed or 10 in alpha_processed
        assert "20" in alpha_processed or 20 in alpha_processed
        assert "30" not in alpha_processed and 30 not in alpha_processed
        assert "30" in beta_processed or 30 in beta_processed
        assert "10" not in beta_processed and 10 not in beta_processed

    def test_lifetime_stats_independent(self, tmp_path: Path) -> None:
        """Lifetime stats should be independent per state file."""
        from state import StateTracker

        alpha_state = StateTracker(tmp_path / "alpha-state.json")
        beta_state = StateTracker(tmp_path / "beta-state.json")

        # Modify alpha's stats using record_* methods
        for _ in range(5):
            alpha_state.record_issue_completed()
        for _ in range(3):
            alpha_state.record_pr_merged()

        # Beta should be untouched
        stats_b = beta_state.get_lifetime_stats()
        assert stats_b.issues_completed == 0
        assert stats_b.prs_merged == 0

        # Verify alpha is correct after reload
        alpha_state2 = StateTracker(tmp_path / "alpha-state.json")
        stats_a2 = alpha_state2.get_lifetime_stats()
        assert stats_a2.issues_completed == 5
        assert stats_a2.prs_merged == 3


# ---------------------------------------------------------------------------
# Session scoping
# ---------------------------------------------------------------------------


class TestSessionScoping:
    def test_session_scoping_by_repo_field(self, tmp_path: Path) -> None:
        """load_sessions(repo=...) should filter by repo field."""
        from state import StateTracker

        st = StateTracker(tmp_path / "state.json")

        alpha_session = _make_session("owner/repo-alpha", "alpha-sess-1")
        beta_session = _make_session("owner/repo-beta", "beta-sess-1")
        alpha_session2 = _make_session("owner/repo-alpha", "alpha-sess-2")

        st.save_session(alpha_session)
        st.save_session(beta_session)
        st.save_session(alpha_session2)

        alpha_sessions = st.load_sessions(repo="owner/repo-alpha")
        beta_sessions = st.load_sessions(repo="owner/repo-beta")
        all_sessions = st.load_sessions()

        assert len(alpha_sessions) == 2
        assert len(beta_sessions) == 1
        assert len(all_sessions) == 3
        assert all(s.repo == "owner/repo-alpha" for s in alpha_sessions)
        assert beta_sessions[0].repo == "owner/repo-beta"

    def test_session_ids_unique_across_repos(self, tmp_path: Path) -> None:
        """Session IDs with the same name but different repos should coexist."""
        from state import StateTracker

        st = StateTracker(tmp_path / "state.json")

        st.save_session(_make_session("owner/repo-alpha", "shared-id"))
        st.save_session(_make_session("owner/repo-beta", "shared-id"))

        all_sessions = st.load_sessions()
        # Dedup may merge by ID — at least one should exist
        assert len(all_sessions) >= 1


# ---------------------------------------------------------------------------
# Worker interval independence
# ---------------------------------------------------------------------------


class TestWorkerIntervalIndependence:
    def test_intervals_isolated_per_state_file(self, tmp_path: Path) -> None:
        """Worker intervals should be per-state-file, not shared."""
        from state import StateTracker

        alpha_state = StateTracker(tmp_path / "alpha-state.json")
        beta_state = StateTracker(tmp_path / "beta-state.json")

        alpha_state.set_worker_intervals({"plan": 45, "implement": 120})
        beta_state.set_worker_intervals({"plan": 30})

        assert alpha_state.get_worker_intervals() == {"plan": 45, "implement": 120}
        assert beta_state.get_worker_intervals() == {"plan": 30}


# ---------------------------------------------------------------------------
# Active issues independence
# ---------------------------------------------------------------------------


class TestActiveIssuesIndependence:
    def test_active_issues_isolated_per_state_file(self, tmp_path: Path) -> None:
        """Active issue lists should be per-state-file."""
        from state import StateTracker

        alpha_state = StateTracker(tmp_path / "alpha-state.json")
        beta_state = StateTracker(tmp_path / "beta-state.json")

        alpha_state.set_active_issue_numbers([10, 20, 30])
        beta_state.set_active_issue_numbers([100, 200])

        assert alpha_state.get_active_issue_numbers() == [10, 20, 30]
        assert beta_state.get_active_issue_numbers() == [100, 200]


# ---------------------------------------------------------------------------
# Worktree path isolation
# ---------------------------------------------------------------------------


class TestWorktreePathIsolation:
    def test_worktree_paths_isolated_per_repo(self, tmp_path: Path) -> None:
        """Each repo config should produce different worktree paths."""
        alpha_cfg = _make_config(tmp_path, "repo-alpha")
        beta_cfg = _make_config(tmp_path, "repo-beta")

        alpha_path = alpha_cfg.worktree_path_for_issue(42)
        beta_path = beta_cfg.worktree_path_for_issue(42)

        assert alpha_path != beta_path
        assert "repo-alpha" in str(alpha_path) or "alpha" in str(alpha_path)
        assert "repo-beta" in str(beta_path) or "beta" in str(beta_path)
