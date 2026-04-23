"""Tests for the pre-cutover Hindsight → wiki extraction script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# The script lives under scripts/, not src/ — add it to sys.path so tests can import it.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from extract_hindsight_to_wiki import (
    extract_corroborated_memories,
    write_entries_to_wiki,
)


def test_extract_corroborated_requires_two_citations():
    raw = [
        {"text": "A", "citations": []},
        {"text": "B", "citations": ["issue#1"]},
        {"text": "C", "citations": ["issue#1", "issue#2"]},
    ]
    survivors = extract_corroborated_memories(raw)
    assert len(survivors) == 1
    assert survivors[0]["text"] == "C"


def test_extract_keeps_memories_tied_to_closed_issues():
    raw = [
        {
            "text": "Only one cite but tied to closed",
            "citations": ["issue#99"],
            "closed_issue": True,
        },
        {
            "text": "Only one cite, open",
            "citations": ["issue#99"],
            "closed_issue": False,
        },
    ]
    survivors = extract_corroborated_memories(raw)
    assert len(survivors) == 1
    assert "closed" in survivors[0]["text"]


def test_extract_handles_missing_citations_field():
    raw = [{"text": "no citations key at all"}]
    survivors = extract_corroborated_memories(raw)
    assert survivors == []


async def test_write_entries_runs_synthesize_per_memory(tmp_path):
    from repo_wiki import RepoWikiStore, WikiEntry

    store = RepoWikiStore(tmp_path / "wiki")
    compiler = MagicMock()
    compiler.synthesize_ingest = AsyncMock(
        return_value=[
            WikiEntry(
                title="extracted",
                content="body",
                source_type="librarian",
                topic="patterns",
            ),
        ]
    )
    written = await write_entries_to_wiki(
        store=store,
        compiler=compiler,
        repo="acme/widget",
        memories=[{"text": "raw memory", "citations": ["issue#1", "issue#2"]}],
    )
    assert written == 1
    out = store.query("acme/widget")
    assert "extracted" in out


async def test_write_entries_empty_survivor_list_writes_nothing(tmp_path):
    from repo_wiki import RepoWikiStore

    store = RepoWikiStore(tmp_path / "wiki")
    compiler = MagicMock()
    compiler.synthesize_ingest = AsyncMock(return_value=[])  # librarian drops
    written = await write_entries_to_wiki(
        store=store,
        compiler=compiler,
        repo="acme/widget",
        memories=[{"text": "raw", "citations": ["issue#1", "issue#2"]}],
    )
    assert written == 0
