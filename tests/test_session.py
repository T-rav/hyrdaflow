"""Tests for session logging — SessionLog model and StateTracker session persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from models import SessionLog
from tests.conftest import make_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_session(
    *,
    id: str = "test-repo-20240315T142530",
    repo: str = "test-org/test-repo",
    started_at: str = "2024-03-15T14:25:30+00:00",
    ended_at: str | None = None,
    issues_processed: list[int] | None = None,
    issues_succeeded: int = 0,
    issues_failed: int = 0,
    status: str = "active",
) -> SessionLog:
    return SessionLog(
        id=id,
        repo=repo,
        started_at=started_at,
        ended_at=ended_at,
        issues_processed=issues_processed or [],
        issues_succeeded=issues_succeeded,
        issues_failed=issues_failed,
        status=status,
    )


# ---------------------------------------------------------------------------
# SessionLog Model
# ---------------------------------------------------------------------------


class TestSessionLogModel:
    def test_creation_with_all_fields(self) -> None:
        session = SessionLog(
            id="test-repo-20240315T142530",
            repo="test-org/test-repo",
            started_at="2024-03-15T14:25:30+00:00",
            ended_at="2024-03-15T15:00:00+00:00",
            issues_processed=[1, 2, 3],
            issues_succeeded=2,
            issues_failed=1,
            status="completed",
        )
        assert session.id == "test-repo-20240315T142530"
        assert session.repo == "test-org/test-repo"
        assert session.issues_processed == [1, 2, 3]
        assert session.issues_succeeded == 2
        assert session.issues_failed == 1
        assert session.status == "completed"

    def test_session_log_defaults_to_active_status_with_empty_lists(self) -> None:
        session = SessionLog(
            id="s1",
            repo="owner/repo",
            started_at="2024-01-01T00:00:00",
        )
        assert session.ended_at is None
        assert session.issues_processed == []
        assert session.issues_succeeded == 0
        assert session.issues_failed == 0
        assert session.status == "active"

    def test_serialization_roundtrip(self) -> None:
        original = make_session(
            ended_at="2024-03-15T15:00:00+00:00",
            issues_processed=[10, 20],
            issues_succeeded=1,
            issues_failed=1,
            status="completed",
        )
        json_str = original.model_dump_json()
        restored = SessionLog.model_validate_json(json_str)
        assert restored == original

    def test_model_dump_contains_all_keys(self) -> None:
        session = make_session()
        data = session.model_dump()
        assert "id" in data
        assert "repo" in data
        assert "started_at" in data
        assert "ended_at" in data
        assert "issues_processed" in data
        assert "issues_succeeded" in data
        assert "issues_failed" in data
        assert "status" in data

    def test_requires_id_and_repo(self) -> None:
        with pytest.raises(ValidationError):
            SessionLog(started_at="2024-01-01T00:00:00")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Session Persistence
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    def test_save_session_creates_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        session = make_session()
        tracker.save_session(session)
        sessions_file = tmp_path / "sessions.jsonl"
        assert sessions_file.exists()

    def test_save_session_appends_to_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        s1 = make_session(id="s1", started_at="2024-01-01T00:00:00")
        s2 = make_session(id="s2", started_at="2024-01-02T00:00:00")
        tracker.save_session(s1)
        tracker.save_session(s2)
        lines = (tmp_path / "sessions.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2

    def test_load_sessions_returns_newest_first(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        s1 = make_session(id="s1", started_at="2024-01-01T00:00:00")
        s2 = make_session(id="s2", started_at="2024-01-02T00:00:00")
        s3 = make_session(id="s3", started_at="2024-01-03T00:00:00")
        tracker.save_session(s1)
        tracker.save_session(s2)
        tracker.save_session(s3)
        sessions = tracker.load_sessions()
        assert [s.id for s in sessions] == ["s3", "s2", "s1"]

    def test_load_sessions_empty_when_no_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        sessions = tracker.load_sessions()
        assert sessions == []

    def test_load_sessions_filter_by_repo(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        s1 = make_session(id="s1", repo="org/repo-a", started_at="2024-01-01T00:00:00")
        s2 = make_session(id="s2", repo="org/repo-b", started_at="2024-01-02T00:00:00")
        s3 = make_session(id="s3", repo="org/repo-a", started_at="2024-01-03T00:00:00")
        tracker.save_session(s1)
        tracker.save_session(s2)
        tracker.save_session(s3)
        result = tracker.load_sessions(repo="org/repo-a")
        assert len(result) == 2
        assert all(s.repo == "org/repo-a" for s in result)

    def test_load_sessions_respects_limit(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        for i in range(5):
            tracker.save_session(
                make_session(id=f"s{i}", started_at=f"2024-01-0{i + 1}T00:00:00")
            )
        result = tracker.load_sessions(limit=3)
        assert len(result) == 3

    def test_get_session_returns_matching(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        s1 = make_session(id="target-session")
        tracker.save_session(s1)
        result = tracker.get_session("target-session")
        assert result is not None
        assert result.id == "target-session"

    def test_get_session_returns_none_for_nonexistent(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        tracker.save_session(make_session(id="other"))
        result = tracker.get_session("nonexistent")
        assert result is None

    def test_get_session_returns_none_when_no_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        result = tracker.get_session("anything")
        assert result is None

    def test_load_sessions_deduplicates_by_id(self, tmp_path: Path) -> None:
        """Saving a session twice (start then end) must not produce duplicate entries."""
        tracker = make_state(tmp_path)
        # Simulate orchestrator: save at start (active), then again at end (completed)
        session = make_session(id="s1", status="active")
        tracker.save_session(session)
        session.status = "completed"
        session.ended_at = "2024-03-15T15:00:00+00:00"
        tracker.save_session(session)

        result = tracker.load_sessions()
        assert len(result) == 1, (
            "Duplicate JSONL entries for same ID must be deduplicated"
        )
        assert result[0].status == "completed"
        assert result[0].ended_at == "2024-03-15T15:00:00+00:00"

    def test_get_session_returns_last_written_state(self, tmp_path: Path) -> None:
        """get_session must return the most-recently-written entry, not the first."""
        tracker = make_state(tmp_path)
        session = make_session(id="s1", status="active")
        tracker.save_session(session)
        session.status = "completed"
        session.ended_at = "2024-03-15T15:00:00+00:00"
        tracker.save_session(session)

        result = tracker.get_session("s1")
        assert result is not None
        assert result.status == "completed"
        assert result.ended_at == "2024-03-15T15:00:00+00:00"

    def test_corrupt_lines_logged_in_delete_and_prune(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt JSONL lines produce warning logs in delete/prune paths."""
        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        s1 = make_session(id="valid", status="completed")
        with open(sessions_file, "w") as f:
            f.write("{ corrupt line }\n")
            f.write(s1.model_dump_json() + "\n")
        tracker.delete_session("valid")
        assert "Skipping corrupt session line" in caplog.text

    def test_corrupt_lines_are_skipped(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        s1 = make_session(id="valid")
        with open(sessions_file, "w") as f:
            f.write("{ this is corrupt }\n")
            f.write(s1.model_dump_json() + "\n")
            f.write("also invalid\n")
        result = tracker.load_sessions()
        assert len(result) == 1
        assert result[0].id == "valid"


# ---------------------------------------------------------------------------
# Session Pruning
# ---------------------------------------------------------------------------


class TestSessionPruning:
    def test_prune_keeps_newest(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        for i in range(5):
            tracker.save_session(
                make_session(id=f"s{i}", started_at=f"2024-01-0{i + 1}T00:00:00")
            )
        tracker.prune_sessions("test-org/test-repo", max_keep=2)
        result = tracker.load_sessions()
        assert len(result) == 2
        assert result[0].id == "s4"  # newest
        assert result[1].id == "s3"

    def test_prune_preserves_other_repos(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        for i in range(3):
            tracker.save_session(
                make_session(
                    id=f"a{i}",
                    repo="org/repo-a",
                    started_at=f"2024-01-0{i + 1}T00:00:00",
                )
            )
        tracker.save_session(
            make_session(
                id="b0",
                repo="org/repo-b",
                started_at="2024-01-04T00:00:00",
            )
        )
        tracker.prune_sessions("org/repo-a", max_keep=1)
        all_sessions = tracker.load_sessions()
        repo_a = [s for s in all_sessions if s.repo == "org/repo-a"]
        repo_b = [s for s in all_sessions if s.repo == "org/repo-b"]
        assert len(repo_a) == 1
        assert repo_a[0].id == "a2"  # newest
        assert len(repo_b) == 1

    def test_prune_noop_when_below_limit(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        tracker.save_session(make_session(id="s0"))
        tracker.prune_sessions("test-org/test-repo", max_keep=10)
        result = tracker.load_sessions()
        assert len(result) == 1

    def test_prune_noop_when_no_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        # Should not raise
        tracker.prune_sessions("test-org/test-repo", max_keep=5)

    def test_prune_deduplicates_before_counting(self, tmp_path: Path) -> None:
        """Prune must count unique sessions, not raw JSONL lines.

        If each session is saved twice (start + end), max_keep=2 should keep
        2 unique sessions, not 1 session with 2 lines.
        """
        tracker = make_state(tmp_path)
        for i in range(3):
            session = make_session(
                id=f"s{i}",
                started_at=f"2024-01-0{i + 1}T00:00:00",
                status="active",
            )
            tracker.save_session(session)
            session.status = "completed"
            tracker.save_session(session)

        tracker.prune_sessions("test-org/test-repo", max_keep=2)
        result = tracker.load_sessions()
        assert len(result) == 2
        assert result[0].id == "s2"
        assert result[1].id == "s1"

    def test_prune_handles_empty_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        sessions_file.write_text("")
        tracker.prune_sessions("test-org/test-repo", max_keep=5)


# ---------------------------------------------------------------------------
# Session Deletion
# ---------------------------------------------------------------------------


class TestSessionDeletion:
    def test_delete_completed_session(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        s1 = make_session(id="s1", status="completed", started_at="2024-01-01T00:00:00")
        s2 = make_session(id="s2", status="completed", started_at="2024-01-02T00:00:00")
        tracker.save_session(s1)
        tracker.save_session(s2)
        result = tracker.delete_session("s1")
        assert result is True
        sessions = tracker.load_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == "s2"

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        tracker.save_session(make_session(id="s1", status="completed"))
        result = tracker.delete_session("nonexistent")
        assert result is False

    def test_delete_active_session_raises(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        tracker.save_session(make_session(id="s1", status="active"))
        with pytest.raises(ValueError, match="Cannot delete active session"):
            tracker.delete_session("s1")

    def test_delete_returns_false_when_no_file(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        result = tracker.delete_session("anything")
        assert result is False

    def test_delete_preserves_other_sessions(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        for i in range(3):
            tracker.save_session(
                make_session(
                    id=f"s{i}",
                    status="completed",
                    started_at=f"2024-01-0{i + 1}T00:00:00",
                )
            )
        tracker.delete_session("s1")
        sessions = tracker.load_sessions()
        assert len(sessions) == 2
        ids = {s.id for s in sessions}
        assert ids == {"s0", "s2"}

    def test_delete_deduplicates_before_removal(self, tmp_path: Path) -> None:
        """Session saved twice (start + end) should be fully removed."""
        tracker = make_state(tmp_path)
        session = make_session(id="s1", status="active")
        tracker.save_session(session)
        session.status = "completed"
        session.ended_at = "2024-03-15T15:00:00+00:00"
        tracker.save_session(session)

        result = tracker.delete_session("s1")
        assert result is True
        sessions = tracker.load_sessions()
        assert len(sessions) == 0

    def test_delete_persists_across_reload(self, tmp_path: Path) -> None:
        tracker = make_state(tmp_path)
        tracker.save_session(make_session(id="s1", status="completed"))
        tracker.save_session(
            make_session(id="s2", status="completed", started_at="2024-01-02T00:00:00")
        )
        tracker.delete_session("s1")

        # Reload from fresh tracker
        tracker2 = make_state(tmp_path)
        sessions = tracker2.load_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == "s2"


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestSessionConfig:
    def test_max_sessions_per_repo_default(self) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create()
        assert config.max_sessions_per_repo == 10

    def test_max_sessions_per_repo_bounds(self) -> None:
        from tests.helpers import ConfigFactory

        with pytest.raises(ValidationError):
            ConfigFactory.create(max_sessions_per_repo=0)
        with pytest.raises(ValidationError):
            ConfigFactory.create(max_sessions_per_repo=101)

    def test_max_sessions_per_repo_within_bounds(self) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(max_sessions_per_repo=50)
        assert config.max_sessions_per_repo == 50


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


class TestNarrowedExceptionHandling:
    """Verify that session JSONL parsing catches ValidationError (not bare Exception)
    and emits debug/warning logs for corrupt lines."""

    def test_load_sessions_logs_warning_for_corrupt_lines(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """load_sessions should log a warning for each corrupt line."""
        import logging

        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        valid = make_session(id="valid-session")
        with open(sessions_file, "w") as f:
            f.write("{ corrupt json }\n")
            f.write(valid.model_dump_json() + "\n")
            f.write("not json at all\n")

        with caplog.at_level(logging.WARNING, logger="hydraflow.state"):
            result = tracker.load_sessions()

        assert len(result) == 1
        assert result[0].id == "valid-session"
        assert caplog.text.count("Skipping corrupt session line") >= 2

    def test_load_sessions_warning_includes_exc_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """load_sessions warning logs should include exc_info for tracebacks."""
        import logging

        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(sessions_file, "w") as f:
            f.write("{ bad }\n")

        with caplog.at_level(logging.WARNING, logger="hydraflow.state"):
            tracker.load_sessions()

        assert len(caplog.records) >= 1
        assert caplog.records[0].exc_info is not None

    def test_get_session_logs_debug_for_corrupt_lines(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """get_session should log debug for corrupt lines."""
        import logging

        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        valid = make_session(id="target")
        with open(sessions_file, "w") as f:
            f.write("corrupt line\n")
            f.write(valid.model_dump_json() + "\n")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.state"):
            result = tracker.get_session("target")

        assert result is not None
        assert result.id == "target"
        assert "Skipping corrupt session line" in caplog.text

    def test_delete_session_logs_debug_for_corrupt_lines(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """delete_session should log debug for corrupt lines."""
        import logging

        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        valid = make_session(id="s1", status="completed")
        with open(sessions_file, "w") as f:
            f.write("corrupt\n")
            f.write(valid.model_dump_json() + "\n")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.state"):
            result = tracker.delete_session("s1")

        assert result is True
        assert "Skipping corrupt session line" in caplog.text

    def test_prune_sessions_logs_debug_for_corrupt_lines(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """prune_sessions should log debug for corrupt lines."""
        import logging

        tracker = make_state(tmp_path)
        sessions_file = tmp_path / "sessions.jsonl"
        sessions_file.parent.mkdir(parents=True, exist_ok=True)
        valid = make_session(id="s1")
        with open(sessions_file, "w") as f:
            f.write("corrupt\n")
            f.write(valid.model_dump_json() + "\n")

        with caplog.at_level(logging.DEBUG, logger="hydraflow.state"):
            tracker.prune_sessions("test-org/test-repo", max_keep=10)

        assert "Skipping corrupt session line" in caplog.text


# ---------------------------------------------------------------------------
# Session I/O error handling (issue #1038)
# ---------------------------------------------------------------------------


class TestSessionIOErrors:
    """Verify session file I/O handles OSError gracefully."""

    def test_load_sessions_deduped_returns_empty_on_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the sessions file can't be opened, return empty list."""
        import logging
        from unittest.mock import patch

        tracker = make_state(tmp_path)
        # Create a valid sessions file first
        tracker.save_session(make_session(id="s1"))

        with (
            patch("builtins.open", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.state"),
        ):
            result = tracker.load_sessions()

        assert result == []
        assert "Could not open sessions file" in caplog.text

    def test_save_session_logs_warning_on_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the sessions file can't be written, log warning and don't raise."""
        import logging
        from unittest.mock import patch

        tracker = make_state(tmp_path)

        with (
            patch("builtins.open", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.state"),
        ):
            tracker.save_session(make_session(id="s1"))  # should not raise

        assert "Could not save session" in caplog.text

    def test_save_session_handles_mkdir_permission_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When mkdir fails with PermissionError, log warning and don't raise."""
        import logging
        from unittest.mock import patch

        tracker = make_state(tmp_path)

        with (
            patch.object(Path, "mkdir", side_effect=PermissionError("not allowed")),
            caplog.at_level(logging.WARNING, logger="hydraflow.state"),
        ):
            tracker.save_session(make_session(id="s1"))  # should not raise

        assert "Could not save session" in caplog.text
