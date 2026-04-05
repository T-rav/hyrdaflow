"""Tests for state -- sessions and related state."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from models import PendingReport, SessionLog, SessionStatus
from state import StateTracker
from tests.helpers import make_tracker

# ---------------------------------------------------------------------------
# Helpers
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


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


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
        assert tracker.get_active_workspaces() == {}
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
