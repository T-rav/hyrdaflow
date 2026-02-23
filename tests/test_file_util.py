"""Tests for file_util.atomic_write."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from file_util import atomic_write


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
