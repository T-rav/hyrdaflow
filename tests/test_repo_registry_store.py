"""Tests for repo_registry_store.RepoRegistryStore."""

from __future__ import annotations

from pathlib import Path

from repo_registry_store import RepoEntry, RepoRegistryStore


class TestRepoRegistryStore:
    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        store = RepoRegistryStore(tmp_path)
        assert store.load() == []

    def test_add_and_round_trip(self, tmp_path: Path) -> None:
        store = RepoRegistryStore(tmp_path)
        entry = RepoEntry(slug="org-repo", path="/repos/org-repo", auto_start=True)
        store.add(entry)
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].model_dump() == entry.model_dump()

    def test_add_overwrites_existing_slug(self, tmp_path: Path) -> None:
        store = RepoRegistryStore(tmp_path)
        first = RepoEntry(slug="org-repo", path="/repos/one", auto_start=True)
        updated = RepoEntry(slug="org-repo", path="/repos/two", auto_start=False)
        store.add(first)
        store.add(updated)
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].path == "/repos/two"
        assert loaded[0].auto_start is False

    def test_remove_deletes_entry(self, tmp_path: Path) -> None:
        store = RepoRegistryStore(tmp_path)
        store.add(RepoEntry(slug="a", path="/repos/a"))
        store.add(RepoEntry(slug="b", path="/repos/b"))
        assert store.remove("a") is True
        remaining = [entry.slug for entry in store.load()]
        assert remaining == ["b"]

    def test_remove_returns_false_when_missing(self, tmp_path: Path) -> None:
        store = RepoRegistryStore(tmp_path)
        assert store.remove("missing") is False

    def test_corrupt_file_is_quarantined(self, tmp_path: Path) -> None:
        store = RepoRegistryStore(tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("not-json")
        entries = store.load()
        assert entries == []
        backups = list(store.path.parent.glob("repos.json.corrupt*"))
        assert backups, "Expected corrupt file to be renamed"
