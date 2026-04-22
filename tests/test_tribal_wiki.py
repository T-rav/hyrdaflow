"""Tests for TribalWikiStore — global cross-repo knowledge."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_wiki import WikiEntry
from tribal_wiki import TribalWikiStore


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "tribal_test"


def test_tribal_store_ingest_entry_gets_global_source_repo(root):
    store = TribalWikiStore(root)
    entry = WikiEntry(
        title="Python uv pattern",
        content="All Python projects use uv for dependency management.",
        source_type="librarian",
        topic="patterns",
    )
    store.ingest([entry])
    out = store.query()
    assert "uv" in out


def test_tribal_store_persists_and_reloads(root):
    store1 = TribalWikiStore(root)
    entry = WikiEntry(
        title="Test runner convention",
        content="Use pytest-asyncio with mode=auto.",
        source_type="librarian",
        topic="testing",
    )
    store1.ingest([entry])

    # New store instance reads the same data.
    store2 = TribalWikiStore(root)
    out = store2.query()
    assert "pytest-asyncio" in out


def test_tribal_store_filters_non_current_on_query(root):
    """Staleness evaluator applies to tribal entries too."""
    from datetime import UTC, datetime, timedelta

    store = TribalWikiStore(root)
    current = WikiEntry(
        title="valid",
        content="ok",
        source_type="librarian",
        topic="patterns",
    )
    expired = WikiEntry(
        title="expired",
        content="gone",
        source_type="librarian",
        topic="patterns",
        valid_to=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    store.ingest([current, expired])

    out = store.query()
    assert "ok" in out
    assert "gone" not in out
