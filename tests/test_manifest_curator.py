"""Tests for curated manifest assembly."""

from __future__ import annotations

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
