"""Tests for file_util helpers: atomic_write, append_jsonl, file_lock, rotate_backups."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from file_util import append_jsonl, atomic_write, file_lock


class TestAtomicWrite:
    """Tests for the atomic_write() utility."""

    def test_writes_data_to_path(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        atomic_write(target, '{"key": "value"}')
        assert target.read_text() == '{"key": "value"}'

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "out.txt"
        atomic_write(target, "hello")
        assert target.read_text() == "hello"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("old data")
        atomic_write(target, "new data")
        assert target.read_text() == "new data"

    def test_atomic_replace_used(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with patch("file_util.os.replace", wraps=os.replace) as mock_replace:
            atomic_write(target, "data")
            mock_replace.assert_called_once()
            args = mock_replace.call_args[0]
            assert str(args[1]) == str(target)

    def test_cleans_up_temp_on_write_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with (
            patch("file_util.os.fdopen", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            atomic_write(target, "data")

        temps = list(tmp_path.glob(".out-*.tmp"))
        assert temps == []

    def test_cleans_up_temp_on_fsync_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with (
            patch("file_util.os.fsync", side_effect=OSError("fsync failed")),
            pytest.raises(OSError, match="fsync failed"),
        ):
            atomic_write(target, "data")

        temps = list(tmp_path.glob(".out-*.tmp"))
        assert temps == []

    def test_original_file_intact_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        target.write_text("original")
        with (
            patch("file_util.os.fsync", side_effect=OSError("fail")),
            pytest.raises(OSError),
        ):
            atomic_write(target, "replacement")

        assert target.read_text() == "original"

    def test_no_temp_files_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        atomic_write(target, "data")
        temps = list(tmp_path.glob(".out-*.tmp"))
        assert temps == []

    def test_temp_file_in_same_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "out.txt"
        with patch(
            "file_util.tempfile.mkstemp", wraps=__import__("tempfile").mkstemp
        ) as mock_mkstemp:
            atomic_write(target, "data")
            mock_mkstemp.assert_called_once()
            kwargs = mock_mkstemp.call_args[1]
            assert str(kwargs["dir"]) == str(tmp_path)

    def test_writes_empty_string(self, tmp_path: Path) -> None:
        """atomic_write("") should create an empty file without error.

        This is the code path triggered by events.py _rotate_sync when all
        event lines are expired during log rotation.
        """
        target = tmp_path / "out.txt"
        atomic_write(target, "")
        assert target.exists()
        assert target.read_text() == ""


class TestAppendJsonl:
    """Tests for the append_jsonl() utility."""

    def test_appends_line_with_newline(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        append_jsonl(target, '{"a":1}')
        append_jsonl(target, '{"b":2}')
        lines = target.read_text().splitlines()
        assert lines == ['{"a":1}', '{"b":2}']

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "log.jsonl"
        append_jsonl(target, '{"x":1}')
        assert target.read_text() == '{"x":1}\n'

    def test_calls_fsync(self, tmp_path: Path) -> None:
        target = tmp_path / "log.jsonl"
        with patch("file_util.os.fsync", wraps=os.fsync) as mock_fsync:
            append_jsonl(target, '{"synced":true}')
            mock_fsync.assert_called_once()


class TestFileLock:
    """Tests for file_lock()."""

    def test_creates_parent_directory_and_lock_file(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "locks" / "hydra.lock"
        with file_lock(lock_path):
            assert lock_path.exists()

    def test_acquires_and_releases_exclusive_lock(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "hydra.lock"
        calls: list[tuple[int, int]] = []

        def _record(fd: int, op: int) -> None:
            calls.append((fd, op))

        with patch("file_util.fcntl.flock", side_effect=_record), file_lock(lock_path):
            pass

        assert len(calls) == 2
        assert calls[0][1] == fcntl.LOCK_EX
        assert calls[1][1] == fcntl.LOCK_UN


class TestRotateBackups:
    """Tests for the rotate_backups() utility."""

    def test_creates_bak_from_source(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert Path(f"{target}.bak").read_text() == "v1"

    def test_shifts_existing_bak_to_bak_1(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v2")
        bak = Path(f"{target}.bak")
        bak.write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert bak.read_text() == "v2"
        assert Path(f"{target}.bak.1").read_text() == "v1"

    def test_rotates_full_chain(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v4")
        Path(f"{target}.bak").write_text("v3")
        Path(f"{target}.bak.1").write_text("v2")
        Path(f"{target}.bak.2").write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert Path(f"{target}.bak").read_text() == "v4"
        assert Path(f"{target}.bak.1").read_text() == "v3"
        assert Path(f"{target}.bak.2").read_text() == "v2"
        assert Path(f"{target}.bak.3").read_text() == "v1"

    def test_deletes_oldest_beyond_count(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v5")
        Path(f"{target}.bak").write_text("v4")
        Path(f"{target}.bak.1").write_text("v3")
        Path(f"{target}.bak.2").write_text("v2")
        Path(f"{target}.bak.3").write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=3)
        assert not Path(f"{target}.bak.4").exists()
        # .bak.3 should exist (was .bak.2 before rotation)
        assert Path(f"{target}.bak.3").exists()

    def test_noop_when_source_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.json"
        from file_util import rotate_backups

        rotate_backups(target, count=3)  # should not raise

    def test_count_of_one(self, tmp_path: Path) -> None:
        target = tmp_path / "state.json"
        target.write_text("v2")
        Path(f"{target}.bak").write_text("v1")
        from file_util import rotate_backups

        rotate_backups(target, count=1)
        assert Path(f"{target}.bak").read_text() == "v2"
        # With count=1, the old .bak (now .bak.1) is the oldest allowed
        assert Path(f"{target}.bak.1").read_text() == "v1"
