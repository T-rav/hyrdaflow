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


# ----------------------------------------------------------------------
# Ingest wiring — PlanPhase._wiki_commit_compiler_entries reads the
# decisions list and bumps the canonical instead of writing a sibling.
# ----------------------------------------------------------------------

import subprocess  # noqa: E402

from repo_wiki import RepoWikiStore  # noqa: E402


def test_commit_entries_with_corroborate_decision_bumps_canonical_and_skips_write(
    tmp_path: Path,
) -> None:
    """Ingest commit: when the decision says corroborate, the canonical's
    counter bumps and no new file is written for that entry."""
    from wiki_compiler import CorroborationDecision  # runtime-import

    # Set up a real git worktree so commit_pending_entries doesn't fail.
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=worktree, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=worktree,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree, check=True)
    (worktree / "seed").write_text("x")
    subprocess.run(
        ["git", "add", "seed"], cwd=worktree, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )

    tracked_root = worktree / "repo_wiki"
    store = RepoWikiStore(wiki_root=tracked_root, tracked_root=tracked_root)

    # Seed an existing canonical entry that a new ingest will match.
    canonical = WikiEntry(
        title="Factories over direct instantiation",
        content="Use a factory.",
        source_type="review",
        source_issue=1,
    )
    canonical_path = store.write_entry("o/r", canonical, topic="patterns")
    subprocess.run(
        ["git", "add", "repo_wiki"], cwd=worktree, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )

    # Now call _wiki_commit_compiler_entries directly with a pre-populated
    # "should_corroborate" decision. We don't need PlanPhase — just the
    # bound method's logic.
    from plan_phase import PlanPhase

    new_entry = _entry("Another factories insight")
    decisions = [
        CorroborationDecision(
            should_corroborate=True,
            canonical_title=canonical.title,
            canonical_id=canonical.id,
            canonical_path=canonical_path,
        )
    ]

    topic_dir = canonical_path.parent
    before_count = sum(1 for _ in topic_dir.glob("*.md"))

    # Build a PlanPhase-like object with the minimum surface to call the
    # method. The method only reads self._config.repo_wiki_path and
    # doesn't touch other state in this path.
    phase_config = MagicMock()
    phase_config.repo_wiki_path = "repo_wiki"
    phase = PlanPhase.__new__(PlanPhase)
    phase._config = phase_config

    phase._wiki_commit_compiler_entries(
        tracked_store=store,
        worktree_path=worktree,
        repo="o/r",
        issue_number=99,
        phase="plan",
        entries=[new_entry],
        decisions=decisions,
    )

    # Canonical's corroborations bumped from 1 to 2.
    canonical_text = canonical_path.read_text(encoding="utf-8")
    assert "corroborations: 2" in canonical_text

    # No new file written for the corroborated entry.
    after_count = sum(1 for _ in topic_dir.glob("*.md"))
    assert after_count == before_count
