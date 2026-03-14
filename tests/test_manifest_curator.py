"""Tests for curated manifest assembly."""

from __future__ import annotations

import json
from pathlib import Path

from manifest_curator import CuratedLearning, CuratedManifestStore
from models import MemoryType
from tests.helpers import ConfigFactory


class TestCuratedManifestStore:
    """Tests covering curated manifest persistence and rendering."""

    def test_update_and_render_sections(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        learnings = [
            CuratedLearning(
                number=1,
                title="Platform overview",
                learning="HydraFlow orchestrates repo prep, planning, and execution.",
                created_at="2024-01-01T00:00:00Z",
                memory_type=MemoryType.KNOWLEDGE,
                body="**Learning:** HydraFlow orchestrates ...",
            ),
            CuratedLearning(
                number=2,
                title="Run supervisor service",
                learning="The hf-supervisor API service coordinates agents.",
                created_at="2024-01-02T00:00:00Z",
                memory_type=MemoryType.KNOWLEDGE,
                body="Services include the supervisor API.",
            ),
            CuratedLearning(
                number=3,
                title="Acceptance tests",
                learning="All agents must pass the architecture convergence checklist.",
                created_at="2024-01-03T00:00:00Z",
                memory_type=MemoryType.KNOWLEDGE,
                body="Standards mention the architecture checklist.",
            ),
        ]

        payload = store.update_from_learnings(learnings)
        assert payload["overview"]
        assert payload["key_services"]
        assert payload["standards"]

        markdown = store.render_markdown(payload)
        assert "## Curated Learnings" in markdown
        assert "### Project Overview" in markdown
        assert "### Key Services & Projects" in markdown

    def test_render_markdown_empty_payload(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        payload = store.update_from_learnings([])
        assert payload["source_count"] == 0
        assert store.render_markdown(payload) == ""


class TestCuratedManifestPath:
    """Tests for the path property."""

    def test_path_returns_data_path(self, tmp_path: Path) -> None:
        """path property returns config.data_path('manifest', 'curated.json')."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        expected = config.data_path("manifest", "curated.json")
        assert store.path == expected

    def test_path_is_a_path_object(self, tmp_path: Path) -> None:
        """path property returns a Path instance."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        assert isinstance(store.path, Path)


class TestCuratedManifestLoad:
    """Tests for load() error paths and happy path."""

    def test_load_missing_file_returns_empty_payload(self, tmp_path: Path) -> None:
        """load() returns empty payload when the file does not exist."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        # File doesn't exist yet — should return empty payload
        payload = store.load()
        assert payload["overview"] == ""
        assert payload["key_services"] == []
        assert payload["standards"] == []
        assert payload["architecture"] == []
        assert payload["source_count"] == 0
        assert payload["updated_at"] is None

    def test_load_corrupt_json_returns_empty_payload(self, tmp_path: Path) -> None:
        """load() returns empty payload when the file contains malformed JSON."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not valid json!!!")
        payload = store.load()
        assert payload["overview"] == ""
        assert payload["source_count"] == 0
        assert payload["updated_at"] is None

    def test_load_empty_file_returns_empty_payload(self, tmp_path: Path) -> None:
        """load() returns empty payload when the file is empty."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("")
        payload = store.load()
        assert payload["overview"] == ""
        assert payload["source_count"] == 0

    def test_load_json_array_returns_empty_payload(self, tmp_path: Path) -> None:
        """load() returns empty payload when file contains a JSON array instead of dict."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(json.dumps(["item1", "item2"]))
        payload = store.load()
        assert payload["overview"] == ""
        assert payload["key_services"] == []
        assert payload["source_count"] == 0
        assert payload["updated_at"] is None

    def test_load_valid_json_returns_coerced_payload(self, tmp_path: Path) -> None:
        """load() returns a properly coerced payload for valid JSON dict."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "overview": "Project summary",
            "key_services": ["svc-a", "svc-b"],
            "standards": ["std-1"],
            "architecture": [],
            "source_count": 5,
            "updated_at": "2024-06-01T00:00:00Z",
        }
        store.path.write_text(json.dumps(data))
        payload = store.load()
        assert payload["overview"] == "Project summary"
        assert payload["key_services"] == ["svc-a", "svc-b"]
        assert payload["standards"] == ["std-1"]
        assert payload["architecture"] == []
        assert payload["source_count"] == 5
        assert payload["updated_at"] == "2024-06-01T00:00:00Z"

    def test_load_partial_json_coerces_missing_fields(self, tmp_path: Path) -> None:
        """load() fills in defaults for missing keys in a valid JSON dict."""
        config = ConfigFactory.create(repo_root=tmp_path)
        store = CuratedManifestStore(config)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(json.dumps({"overview": "partial"}))
        payload = store.load()
        assert payload["overview"] == "partial"
        assert payload["key_services"] == []
        assert payload["standards"] == []
        assert payload["architecture"] == []
        assert payload["source_count"] == 0
        assert payload["updated_at"] is None
