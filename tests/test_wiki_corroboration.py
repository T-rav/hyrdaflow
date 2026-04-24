"""Ingest-path dedup: re-discoveries of the same principle should
bump the canonical entry's corroboration counter instead of landing
as a sibling. Uses generalize_pair as the semantic-match primitive."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import WikiEntry
from wiki_compiler import (
    GeneralizationCheck,
    WikiCompiler,
)


def _entry(title: str, content: str = "body") -> WikiEntry:
    return WikiEntry(
        title=title,
        content=content,
        source_type="review",
        source_issue=1,
        topic="patterns",
    )


@pytest.fixture
def compiler() -> WikiCompiler:
    config = MagicMock()
    runner = MagicMock()
    creds = MagicMock()
    return WikiCompiler(config=config, runner=runner, credentials=creds)


@pytest.mark.asyncio
async def test_match_with_high_confidence_returns_corroboration_decision(
    compiler: WikiCompiler,
) -> None:
    new = _entry("Always use factories")
    canonical = _entry("Use factories not direct instantiation")
    canonical_path = Path("/tmp/canonical.md")
    existing = [(canonical, canonical_path)]
    compiler.generalize_pair = AsyncMock(
        return_value=GeneralizationCheck(same_principle=True, confidence="high")
    )

    decision = await compiler.dedup_or_corroborate(
        repo_slug="o/r",
        entry=new,
        existing_entries=existing,
        topic="patterns",
    )

    assert decision.should_corroborate is True
    assert decision.canonical_title == "Use factories not direct instantiation"
    assert decision.canonical_path == canonical_path


@pytest.mark.asyncio
async def test_low_confidence_does_not_corroborate(compiler: WikiCompiler) -> None:
    new = _entry("Always use factories")
    existing = [(_entry("Unrelated"), Path("/tmp/u.md"))]
    compiler.generalize_pair = AsyncMock(
        return_value=GeneralizationCheck(same_principle=True, confidence="low")
    )

    decision = await compiler.dedup_or_corroborate(
        repo_slug="o/r",
        entry=new,
        existing_entries=existing,
        topic="patterns",
    )

    assert decision.should_corroborate is False


@pytest.mark.asyncio
async def test_no_same_principle_returns_no_corroboration(
    compiler: WikiCompiler,
) -> None:
    new = _entry("Always use factories")
    existing = [(_entry("Unrelated"), Path("/tmp/u.md"))]
    compiler.generalize_pair = AsyncMock(
        return_value=GeneralizationCheck(same_principle=False, confidence="high")
    )

    decision = await compiler.dedup_or_corroborate(
        repo_slug="o/r",
        entry=new,
        existing_entries=existing,
        topic="patterns",
    )

    assert decision.should_corroborate is False


@pytest.mark.asyncio
async def test_empty_existing_entries_skips_llm(compiler: WikiCompiler) -> None:
    new = _entry("First")
    compiler.generalize_pair = AsyncMock()

    decision = await compiler.dedup_or_corroborate(
        repo_slug="o/r",
        entry=new,
        existing_entries=[],
        topic="patterns",
    )

    assert decision.should_corroborate is False
    compiler.generalize_pair.assert_not_called()


@pytest.mark.asyncio
async def test_stops_at_first_confident_match(compiler: WikiCompiler) -> None:
    """Cost bound — don't query every existing entry once we have a match."""
    new = _entry("q")
    existing = [(_entry(f"e{i}"), Path(f"/tmp/e{i}.md")) for i in range(5)]
    calls: list[tuple[str, str]] = []

    async def fake_generalize(*, entry_a, entry_b, topic):
        calls.append((entry_a.title, entry_b.title))
        if entry_b.title == "e0":
            return GeneralizationCheck(same_principle=True, confidence="high")
        return GeneralizationCheck()

    compiler.generalize_pair = fake_generalize  # type: ignore[method-assign]

    decision = await compiler.dedup_or_corroborate(
        repo_slug="o/r",
        entry=new,
        existing_entries=existing,
        topic="patterns",
    )

    assert decision.should_corroborate is True
    assert decision.canonical_path == Path("/tmp/e0.md")
    assert len(calls) == 1
