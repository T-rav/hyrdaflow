"""Tests for the DedupStore class."""

from __future__ import annotations

import json
from pathlib import Path

from dedup_store import DedupStore

# ---------------------------------------------------------------------------
# File-backed tests
# ---------------------------------------------------------------------------


class TestDedupStoreFileBacked:
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
