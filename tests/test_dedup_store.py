"""Tests for the DedupStore class."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dedup_store import DedupStore

# ---------------------------------------------------------------------------
# File-backed tests (no Dolt)
# ---------------------------------------------------------------------------


class TestDedupStoreFileBacked:
    """Tests for DedupStore using file-backed JSON."""

    def test_get_empty_when_file_missing(self, tmp_path: Path) -> None:
        store = DedupStore("test_set", tmp_path / "missing.json")
        assert store.get() == set()

    def test_add_creates_file_and_persists(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        store = DedupStore("test_set", fp)
        store.add("alpha")
        assert fp.exists()
        assert store.get() == {"alpha"}

    def test_add_multiple_values(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        store = DedupStore("test_set", fp)
        store.add("alpha")
        store.add("beta")
        store.add("alpha")  # duplicate
        assert store.get() == {"alpha", "beta"}

    def test_set_all_overwrites(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        store = DedupStore("test_set", fp)
        store.add("alpha")
        store.set_all({"x", "y", "z"})
        assert store.get() == {"x", "y", "z"}

    def test_set_all_empty(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        store = DedupStore("test_set", fp)
        store.add("alpha")
        store.set_all(set())
        assert store.get() == set()

    def test_get_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        fp.write_text("{bad json!!!")
        store = DedupStore("test_set", fp)
        assert store.get() == set()

    def test_get_non_list_json_returns_empty(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        fp.write_text('{"not": "a list"}')
        store = DedupStore("test_set", fp)
        assert store.get() == set()

    def test_add_creates_parent_dirs(self, tmp_path: Path) -> None:
        fp = tmp_path / "sub" / "dir" / "dedup.json"
        store = DedupStore("test_set", fp)
        store.add("value")
        assert fp.exists()
        assert store.get() == {"value"}

    def test_set_all_creates_parent_dirs(self, tmp_path: Path) -> None:
        fp = tmp_path / "sub" / "dir" / "dedup.json"
        store = DedupStore("test_set", fp)
        store.set_all({"a", "b"})
        assert fp.exists()
        assert store.get() == {"a", "b"}

    def test_file_stores_sorted_json_list(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        store = DedupStore("test_set", fp)
        store.add("charlie")
        store.add("alpha")
        store.add("bravo")
        data = json.loads(fp.read_text())
        assert data == ["alpha", "bravo", "charlie"]


# ---------------------------------------------------------------------------
# Dolt-backed tests
# ---------------------------------------------------------------------------


class TestDedupStoreDoltBacked:
    """Tests for DedupStore using a mocked DoltBackend."""

    @pytest.fixture()
    def mock_dolt(self) -> MagicMock:
        dolt = MagicMock()
        dolt.get_dedup_set.return_value = set()
        return dolt

    def test_get_delegates_to_dolt(self, tmp_path: Path, mock_dolt: MagicMock) -> None:
        mock_dolt.get_dedup_set.return_value = {"a", "b"}
        store = DedupStore("my_set", tmp_path / "unused.json", dolt=mock_dolt)
        result = store.get()
        assert result == {"a", "b"}
        mock_dolt.get_dedup_set.assert_called_once_with("my_set")

    def test_add_delegates_to_dolt(self, tmp_path: Path, mock_dolt: MagicMock) -> None:
        store = DedupStore("my_set", tmp_path / "unused.json", dolt=mock_dolt)
        store.add("val")
        mock_dolt.add_to_dedup_set.assert_called_once_with("my_set", "val")
        # File should NOT be written when Dolt is active
        assert not (tmp_path / "unused.json").exists()

    def test_set_all_delegates_to_dolt(
        self, tmp_path: Path, mock_dolt: MagicMock
    ) -> None:
        store = DedupStore("my_set", tmp_path / "unused.json", dolt=mock_dolt)
        store.set_all({"x", "y"})
        mock_dolt.set_dedup_set.assert_called_once_with("my_set", {"x", "y"})
        assert not (tmp_path / "unused.json").exists()

    def test_dolt_none_falls_back_to_file(self, tmp_path: Path) -> None:
        fp = tmp_path / "dedup.json"
        store = DedupStore("test_set", fp, dolt=None)
        store.add("file_backed")
        assert store.get() == {"file_backed"}
        assert fp.exists()
