"""Tests for memory injection in BaseRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from base_runner import BaseRunner
from config import HydraFlowConfig
from events import EventBus


def _make_memory(text: str, score: float = 0.8):
    from hindsight import HindsightMemory

    return HindsightMemory(content=text, text=text, relevance_score=score)


@pytest.fixture
def base_runner():
    config = HydraFlowConfig(repo_root="/tmp/test")
    bus = EventBus()
    hindsight = AsyncMock()
    runner = BaseRunner(config, bus, hindsight=hindsight)
    return runner


@pytest.mark.asyncio
async def test_review_insights_recalled(base_runner):
    """REVIEW_INSIGHTS bank should be recalled and injected into prompt."""
    from hindsight import Bank

    memories = {
        Bank.TRIBAL: [_make_memory("learning-1")],
        Bank.TROUBLESHOOTING: [],
        Bank.RETROSPECTIVES: [],
        Bank.REVIEW_INSIGHTS: [_make_memory("missing tests flagged 5 times")],
        Bank.HARNESS_INSIGHTS: [],
    }

    async def mock_recall(client, bank, query, *, limit=10):
        return memories.get(bank, [])

    with patch("hindsight.recall_safe", side_effect=mock_recall):
        memory_section = await base_runner._inject_memory(
            query_context="add user endpoint"
        )

    assert "Common Review Patterns" in memory_section
    assert "missing tests flagged 5 times" in memory_section


@pytest.mark.asyncio
async def test_harness_insights_recalled(base_runner):
    """HARNESS_INSIGHTS bank should be recalled and injected into prompt."""
    from hindsight import Bank

    memories = {
        Bank.TRIBAL: [],
        Bank.TROUBLESHOOTING: [],
        Bank.RETROSPECTIVES: [],
        Bank.REVIEW_INSIGHTS: [],
        Bank.HARNESS_INSIGHTS: [_make_memory("CI timeout in pytest-xdist on macOS")],
    }

    async def mock_recall(client, bank, query, *, limit=10):
        return memories.get(bank, [])

    with patch("hindsight.recall_safe", side_effect=mock_recall):
        memory_section = await base_runner._inject_memory(
            query_context="fix CI pipeline"
        )

    assert "Known Pipeline Patterns" in memory_section
    assert "CI timeout" in memory_section


# ---------------------------------------------------------------------------
# ADR index injection (Task 3.4)
# ---------------------------------------------------------------------------


def test_inject_adr_index_full_for_plan_phase(tmp_path):
    """Plan-phase injection contains the full ADR index with summaries."""
    from adr_index import ADRIndex

    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "0001-foo.md").write_text(
        "# ADR-0001: Foo\n\n**Status:** Accepted\n\n## Context\n\nbar.\n"
    )

    runner = BaseRunner.__new__(BaseRunner)
    runner._adr_index = ADRIndex(adr_dir)
    runner._phase_name = "plan"  # type: ignore[misc]

    section = runner._inject_adr_index()
    assert "ADR-0001 Foo" in section
    assert "bar." in section


def test_inject_adr_index_titles_only_for_implement_phase(tmp_path):
    from adr_index import ADRIndex

    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "0001-foo.md").write_text(
        "# ADR-0001: Foo\n\n**Status:** Accepted\n\n## Context\n\nbar.\n"
    )

    runner = BaseRunner.__new__(BaseRunner)
    runner._adr_index = ADRIndex(adr_dir)
    runner._phase_name = "implement"  # type: ignore[misc]

    section = runner._inject_adr_index()
    assert "ADR-0001 Foo" in section
    assert "bar." not in section


def test_inject_adr_index_empty_dir_returns_empty_string(tmp_path):
    from adr_index import ADRIndex

    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    runner = BaseRunner.__new__(BaseRunner)
    runner._adr_index = ADRIndex(adr_dir)
    runner._phase_name = "plan"  # type: ignore[misc]
    assert runner._inject_adr_index() == ""


def test_inject_adr_index_unknown_phase_returns_empty(tmp_path):
    """Default phase (e.g. HITL) returns empty — no ADR injection."""
    from adr_index import ADRIndex

    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    (adr_dir / "0001-foo.md").write_text(
        "# ADR-0001: Foo\n\n**Status:** Accepted\n\n## Context\n\nbar.\n"
    )
    runner = BaseRunner.__new__(BaseRunner)
    runner._adr_index = ADRIndex(adr_dir)
    runner._phase_name = "unknown"  # type: ignore[misc]
    assert runner._inject_adr_index() == ""


def test_inject_repo_wiki_includes_tribal_content(tmp_path):
    from unittest.mock import MagicMock

    from base_runner import BaseRunner
    from repo_wiki import RepoWikiStore, WikiEntry
    from tribal_wiki import TribalWikiStore

    per_repo = RepoWikiStore(tmp_path / "per")
    tribal = TribalWikiStore(tmp_path / "global")
    tribal.ingest(
        [
            WikiEntry(
                title="Use dataclasses",
                content="Prefer dataclasses for config.",
                source_type="librarian",
                topic="patterns",
            )
        ]
    )

    runner = BaseRunner.__new__(BaseRunner)
    runner._wiki_store = per_repo
    runner._tribal_wiki_store = tribal
    runner._config = MagicMock()
    runner._config.repo = "acme/widget"
    runner._config.max_repo_wiki_chars = 15_000

    section = runner._inject_repo_wiki()
    assert "Use dataclasses" in section


# ---------------------------------------------------------------------------
# ADR draft wiring in _save_transcript (Task 6.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_transcript_for_adr_draft_opens_issue(tmp_path):
    """End-to-end: transcript contains ADR_DRAFT_SUGGESTION → issue opened."""
    from unittest.mock import AsyncMock, MagicMock

    from base_runner import BaseRunner
    from repo_wiki import WikiEntry
    from tribal_wiki import TribalWikiStore
    from wiki_compiler import ADRDraftDecision

    tribal = TribalWikiStore(tmp_path / "tribal")
    tid = "01HQ0000000000000000000000"
    tribal.ingest(
        [
            WikiEntry(
                id=tid,
                title="pattern",
                content="x",
                source_type="librarian",
                topic="patterns",
            )
        ]
    )

    transcript = f"""Work log.
ADR_DRAFT_SUGGESTION:
title: Use Pydantic
context: C
decision: D
consequences: W
evidence:
  - issue: 1
  - issue: 2
  - wiki_entry: {tid}
"""

    runner = BaseRunner.__new__(BaseRunner)
    runner._tribal_wiki_store = tribal
    compiler = MagicMock()
    compiler.judge_adr_draft = AsyncMock(
        return_value=ADRDraftDecision(
            two_plus_issues=True,
            in_tribal=True,
            architectural=True,
            load_bearing=True,
            draft_ok=True,
        )
    )
    runner._wiki_compiler = compiler
    gh = AsyncMock()
    gh.create_issue = AsyncMock(return_value={"number": 7777})
    runner._gh_client = gh
    runner._bus = MagicMock()
    runner._bus.publish = AsyncMock()
    runner._log = MagicMock()

    await runner._process_transcript_for_adr_draft(transcript)
    gh.create_issue.assert_called_once()
    runner._bus.publish.assert_called_once()
    event = runner._bus.publish.call_args.args[0]
    from events import EventType

    assert event.type == EventType.ADR_DRAFT_OPENED
    assert event.data["issue_number"] == 7777
