"""Tests for dolt_backend.py — embedded Dolt state persistence."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from dolt_backend import DoltBackend


@pytest.fixture
def dolt_dir() -> Path:
    """Return a temp directory for a Dolt repo (outside git worktrees)."""
    base = Path(tempfile.mkdtemp())
    return base / "test-dolt"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestDoltBackendInit:
    """Tests for DoltBackend initialization."""

    def test_raises_when_dolt_not_installed(self, dolt_dir: Path) -> None:
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(FileNotFoundError, match="dolt CLI not found"),
        ):
            DoltBackend(dolt_dir)

    @pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
    def test_initializes_repo(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        assert (dolt_dir / ".dolt").is_dir()
        # Should be able to run SQL
        result = backend._run("status", check=False)
        assert result.returncode == 0

    @pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
    def test_idempotent_init(self, dolt_dir: Path) -> None:
        """Calling init twice doesn't fail."""
        DoltBackend(dolt_dir)
        DoltBackend(dolt_dir)  # should not raise


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
class TestDoltStateReadWrite:
    """Tests for state read/write via Dolt."""

    def test_save_and_load_state(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        state = {"processed_issues": {"42": "merged"}, "last_updated": "2026-01-01"}
        backend.save_state(json.dumps(state))

        loaded = backend.load_state()
        assert loaded is not None
        assert loaded["processed_issues"]["42"] == "merged"

    def test_load_empty_returns_none(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        assert backend.load_state() is None

    def test_save_overwrites(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.save_state(json.dumps({"version": 1}))
        backend.save_state(json.dumps({"version": 2}))

        loaded = backend.load_state()
        assert loaded["version"] == 2

    def test_commit_creates_version(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.save_state(json.dumps({"v": 1}))
        backend.commit("first state")

        log = backend.log(limit=5)
        assert any("first state" in entry.get("message", "") for entry in log)

    def test_state_with_special_chars(self, dolt_dir: Path) -> None:
        """State containing single quotes doesn't break SQL."""
        backend = DoltBackend(dolt_dir)
        state = {"note": "it's a test with 'quotes'"}
        backend.save_state(json.dumps(state))

        loaded = backend.load_state()
        assert loaded["note"] == "it's a test with 'quotes'"


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
class TestDoltSessions:
    """Tests for session read/write via Dolt."""

    def test_save_and_load_session(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        session = {"id": "s1", "repo": "org/repo", "status": "active"}
        backend.save_session("s1", "org/repo", json.dumps(session), "active")

        loaded = backend.load_sessions("org/repo")
        assert len(loaded) == 1
        assert loaded[0]["id"] == "s1"

    def test_get_session_by_id(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.save_session("s2", "org/repo", json.dumps({"id": "s2"}), "active")

        result = backend.get_session("s2")
        assert result is not None
        assert result["id"] == "s2"

    def test_get_missing_session_returns_none(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        assert backend.get_session("nonexistent") is None

    def test_delete_session(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.save_session("s3", "org/repo", json.dumps({"id": "s3"}), "active")
        assert backend.delete_session("s3") is True
        assert backend.get_session("s3") is None


# ---------------------------------------------------------------------------
# Dedup sets
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
class TestDoltDedupSets:
    """Tests for dedup set operations via Dolt."""

    def test_add_and_get(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.add_to_dedup_set("proposed_categories", "missing_tests")
        backend.add_to_dedup_set("proposed_categories", "lint_format")

        result = backend.get_dedup_set("proposed_categories")
        assert result == {"missing_tests", "lint_format"}

    def test_dedup_ignores_duplicates(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.add_to_dedup_set("cats", "a")
        backend.add_to_dedup_set("cats", "a")

        assert backend.get_dedup_set("cats") == {"a"}

    def test_set_replaces_all(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        backend.set_dedup_set("cats", {"a", "b", "c"})
        assert backend.get_dedup_set("cats") == {"a", "b", "c"}

        backend.set_dedup_set("cats", {"x"})
        assert backend.get_dedup_set("cats") == {"x"}

    def test_empty_set(self, dolt_dir: Path) -> None:
        backend = DoltBackend(dolt_dir)
        assert backend.get_dedup_set("empty") == set()


# ---------------------------------------------------------------------------
# StateTracker integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
class TestDoltStateTrackerIntegration:
    """Tests for StateTracker with Dolt backend."""

    def test_state_tracker_save_and_load(self, dolt_dir: Path, tmp_path: Path) -> None:
        from state import StateTracker

        backend = DoltBackend(dolt_dir)
        state_file = tmp_path / "state.json"

        tracker = StateTracker(state_file, dolt=backend)
        tracker.mark_issue(42, "in_progress")

        # Create a new tracker from same Dolt repo — should load the state
        tracker2 = StateTracker(state_file, dolt=backend)
        issues = tracker2.to_dict()["processed_issues"]
        assert issues.get("42") == "in_progress"

    def test_state_tracker_falls_back_to_file_without_dolt(
        self, tmp_path: Path
    ) -> None:
        from state import StateTracker

        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(99, "merged")

        # File should exist
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["processed_issues"]["99"] == "merged"

    def test_build_state_tracker_always_uses_dolt(self, dolt_dir: Path) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create()
        # Patch the dolt_dir to use our temp dir
        with patch("state.Path", return_value=dolt_dir):
            from state import build_state_tracker

            tracker = build_state_tracker(cfg)
            assert tracker._dolt is not None

    def test_build_state_tracker_raises_without_dolt_cli(self) -> None:
        from tests.helpers import ConfigFactory

        cfg = ConfigFactory.create()
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(FileNotFoundError, match="dolt CLI not found"),
        ):
            from state import build_state_tracker

            build_state_tracker(cfg)


# ---------------------------------------------------------------------------
# SQL injection safety
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("dolt"), reason="dolt CLI not installed")
class TestDoltSQLInjection:
    """Tests that user-supplied strings are properly escaped."""

    def test_load_sessions_escapes_repo_with_single_quotes(
        self, dolt_dir: Path
    ) -> None:
        """A repo name containing single quotes must not break the SQL query."""
        backend = DoltBackend(dolt_dir)
        # Save a session with a normal repo name
        backend.save_session("s1", "org/repo", json.dumps({"id": "s1"}), "active")

        # Query with a repo name that contains a single quote — should not raise
        result = backend.load_sessions("org/repo'; DROP TABLE sessions; --")
        assert result == []  # no match, but no crash

    def test_save_state_escapes_single_quotes(self, dolt_dir: Path) -> None:
        """State data containing single quotes uses SQL-standard '' escaping."""
        backend = DoltBackend(dolt_dir)
        data_with_quotes = json.dumps({"note": "it's got 'quotes'"})
        backend.save_state(data_with_quotes)

        loaded = backend.load_state()
        assert loaded is not None
        assert loaded["note"] == "it's got 'quotes'"
