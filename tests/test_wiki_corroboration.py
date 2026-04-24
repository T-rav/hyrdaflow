"""Ingest-path dedup: re-discoveries of the same principle should
bump the canonical entry's corroboration counter instead of landing
as a sibling. Uses generalize_pair as the semantic-match primitive."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import WikiEntry
from wiki_compiler import (
    CorroborationDecision,
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


# ----------------------------------------------------------------------
# Precompute — _precompute_corroboration runs dedup_or_corroborate per
# entry, caps candidates, swallows per-entry exceptions.
# ----------------------------------------------------------------------


def _git_seeded_tracked_store(tmp_path: Path) -> tuple[Path, RepoWikiStore]:
    """Build a real git worktree + tracked RepoWikiStore fixture so the
    precompute tests exercise the real ``_tracked_topic_dir`` and
    ``_load_tracked_topic_entries_with_paths`` code paths (not mocks)."""
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
    return worktree, store


@pytest.mark.asyncio
async def test_plan_phase_precompute_returns_empty_decisions_when_no_compiler(
    tmp_path: Path,
) -> None:
    """No compiler wired → one empty decision per entry, never raises."""
    from plan_phase import PlanPhase

    _worktree, store = _git_seeded_tracked_store(tmp_path)
    phase = PlanPhase.__new__(PlanPhase)
    phase._wiki_compiler = None

    entries = [_entry("a"), _entry("b")]
    decisions = await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=entries,
    )

    assert len(decisions) == len(entries)
    assert all(not d.should_corroborate for d in decisions)


@pytest.mark.asyncio
async def test_plan_phase_precompute_calls_compiler_once_per_entry_with_candidates(
    tmp_path: Path,
) -> None:
    """Each entry is judged against the existing tracked entries in the
    same topic. Resulting decisions are returned in entry order."""
    from plan_phase import PlanPhase

    worktree, store = _git_seeded_tracked_store(tmp_path)
    canonical = _entry("Factories over direct instantiation")
    canonical_path = store.write_entry("o/r", canonical, topic="patterns")

    new_entries = [_entry("A related factories insight"), _entry("Unrelated topic")]
    compiler = MagicMock()
    # Script: first entry matches canonical (high), second returns no match.
    calls: list[str] = []

    async def fake_dedup(
        *, repo_slug, entry, existing_entries, topic, min_confidence="medium"
    ):
        calls.append(entry.title)
        if entry.title == "A related factories insight":
            return CorroborationDecision(
                should_corroborate=True,
                canonical_title=canonical.title,
                canonical_id=canonical.id,
                canonical_path=canonical_path,
            )
        return CorroborationDecision()

    compiler.dedup_or_corroborate = fake_dedup
    phase = PlanPhase.__new__(PlanPhase)
    phase._wiki_compiler = compiler

    decisions = await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=new_entries,
    )

    assert len(decisions) == 2
    assert decisions[0].should_corroborate is True
    assert decisions[0].canonical_path == canonical_path
    assert decisions[1].should_corroborate is False
    assert calls == ["A related factories insight", "Unrelated topic"]
    del worktree  # quiet unused-fixture lint


@pytest.mark.asyncio
async def test_plan_phase_precompute_caps_candidates_per_entry_at_five(
    tmp_path: Path,
) -> None:
    """A topic with >5 existing entries must only pass 5 to generalize_pair
    so a packed wiki doesn't blow the LLM budget on every ingest."""
    from plan_phase import PlanPhase

    _worktree, store = _git_seeded_tracked_store(tmp_path)
    # Seed 10 existing entries in patterns.
    for i in range(10):
        store.write_entry("o/r", _entry(f"existing-{i}"), topic="patterns")

    seen_candidate_counts: list[int] = []
    compiler = MagicMock()

    async def fake_dedup(
        *, repo_slug, entry, existing_entries, topic, min_confidence="medium"
    ):
        seen_candidate_counts.append(len(existing_entries))
        return CorroborationDecision()

    compiler.dedup_or_corroborate = fake_dedup
    phase = PlanPhase.__new__(PlanPhase)
    phase._wiki_compiler = compiler

    await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=[_entry("new")],
    )

    assert seen_candidate_counts == [5]


@pytest.mark.asyncio
async def test_plan_phase_precompute_swallows_per_entry_exceptions(
    tmp_path: Path,
) -> None:
    """A single entry's LLM failure must not sink the batch; that entry
    gets an empty decision and later entries still run."""
    from plan_phase import PlanPhase

    _worktree, store = _git_seeded_tracked_store(tmp_path)
    compiler = MagicMock()
    calls: list[str] = []

    async def fake_dedup(
        *, repo_slug, entry, existing_entries, topic, min_confidence="medium"
    ):
        calls.append(entry.title)
        if entry.title == "boom":
            raise RuntimeError("simulated LLM failure")
        return CorroborationDecision()

    compiler.dedup_or_corroborate = fake_dedup
    phase = PlanPhase.__new__(PlanPhase)
    phase._wiki_compiler = compiler

    entries = [_entry("ok1"), _entry("boom"), _entry("ok2")]
    decisions = await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=entries,
    )

    # All three processed despite one raising.
    assert calls == ["ok1", "boom", "ok2"]
    assert [d.should_corroborate for d in decisions] == [False, False, False]


# ----------------------------------------------------------------------
# ReviewPhase mirrors PlanPhase — one sanity test per side to prove the
# shape works symmetrically (same decision primitive, same commit path).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_phase_precompute_honours_compiler_decision(
    tmp_path: Path,
) -> None:
    from review_phase import ReviewPhase

    worktree, store = _git_seeded_tracked_store(tmp_path)
    canonical = _entry("Use factories")
    canonical_path = store.write_entry("o/r", canonical, topic="patterns")

    compiler = MagicMock()

    async def fake_dedup(
        *, repo_slug, entry, existing_entries, topic, min_confidence="medium"
    ):
        return CorroborationDecision(
            should_corroborate=True,
            canonical_title=canonical.title,
            canonical_id=canonical.id,
            canonical_path=canonical_path,
        )

    compiler.dedup_or_corroborate = fake_dedup
    phase = ReviewPhase.__new__(ReviewPhase)
    phase._wiki_compiler = compiler

    decisions = await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=[_entry("new one")],
    )

    assert len(decisions) == 1
    assert decisions[0].should_corroborate is True
    assert decisions[0].canonical_path == canonical_path
    del worktree  # quiet unused-fixture lint


def test_review_phase_commit_with_corroborate_decision_bumps_canonical(
    tmp_path: Path,
) -> None:
    """Symmetric proof that ReviewPhase._wiki_commit_compiler_entries
    honours decisions the same way PlanPhase does."""
    from review_phase import ReviewPhase

    worktree, store = _git_seeded_tracked_store(tmp_path)
    canonical = _entry("Factories over direct instantiation")
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

    phase_config = MagicMock()
    phase_config.repo_wiki_path = "repo_wiki"
    phase = ReviewPhase.__new__(ReviewPhase)
    phase._config = phase_config

    decisions = [
        CorroborationDecision(
            should_corroborate=True,
            canonical_title=canonical.title,
            canonical_id=canonical.id,
            canonical_path=canonical_path,
        )
    ]

    phase._wiki_commit_compiler_entries(
        tracked_store=store,
        worktree_path=worktree,
        repo="o/r",
        issue_number=42,
        phase="review",
        entries=[_entry("re-discovery")],
        decisions=decisions,
    )

    canonical_text = canonical_path.read_text(encoding="utf-8")
    assert "corroborations: 2" in canonical_text


# ----------------------------------------------------------------------
# Gap-filling tests flagged during self-review:
#   1) per-topic candidate isolation
#   2) mixed batch (some corroborate, some write)
#   3) fresh topic (no existing entries)
# ----------------------------------------------------------------------


def _topical_entry(title: str, *, topic_hint: str) -> WikiEntry:
    """Build a WikiEntry whose content deterministically routes to a
    chosen topic under ``classify_topic``. Uses single-topic keywords
    from ``_TOPIC_KEYWORDS`` so classification is stable without needing
    to stub the classifier."""
    keyword = {
        "patterns": "convention",
        "gotchas": "pitfall",
        "testing": "pytest fixture",
    }[topic_hint]
    return WikiEntry(
        title=title,
        content=f"This is a {keyword} worth recording.",
        source_type="review",
        source_issue=1,
    )


@pytest.mark.asyncio
async def test_precompute_only_passes_candidates_from_the_new_entrys_topic(
    tmp_path: Path,
) -> None:
    """Per-topic isolation: an entry classified as ``patterns`` must
    only be compared against existing ``patterns`` entries — never
    against entries in ``gotchas`` or other topics."""
    from plan_phase import PlanPhase

    _worktree, store = _git_seeded_tracked_store(tmp_path)
    # Seed one entry in each of two topics.
    store.write_entry(
        "o/r",
        _topical_entry("Patterns seed", topic_hint="patterns"),
        topic="patterns",
    )
    store.write_entry(
        "o/r",
        _topical_entry("Gotchas seed", topic_hint="gotchas"),
        topic="gotchas",
    )

    seen_existing_titles: list[list[str]] = []
    compiler = MagicMock()

    async def fake_dedup(
        *, repo_slug, entry, existing_entries, topic, min_confidence="medium"
    ):
        seen_existing_titles.append([e.title for e, _ in existing_entries])
        return CorroborationDecision()

    compiler.dedup_or_corroborate = fake_dedup
    phase = PlanPhase.__new__(PlanPhase)
    phase._wiki_compiler = compiler

    new_entry = _topical_entry("new patterns entry", topic_hint="patterns")
    await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=[new_entry],
    )

    assert len(seen_existing_titles) == 1
    titles = seen_existing_titles[0]
    assert "Patterns seed" in titles
    assert "Gotchas seed" not in titles, (
        "precompute leaked cross-topic candidates into the dedup comparison"
    )


def test_commit_with_mixed_batch_bumps_some_and_writes_others(
    tmp_path: Path,
) -> None:
    """Mixed batch: three entries, two corroborate against two different
    canonicals, one writes normally. All three outcomes must materialise
    correctly in a single commit — append_log count must reflect the
    one actual write, not the batch size."""
    from plan_phase import PlanPhase

    worktree, store = _git_seeded_tracked_store(tmp_path)
    # Seed two different canonicals in patterns.
    canonical_a = _entry("Canonical A")
    canonical_b = _entry("Canonical B")
    path_a = store.write_entry("o/r", canonical_a, topic="patterns")
    path_b = store.write_entry("o/r", canonical_b, topic="patterns")
    subprocess.run(
        ["git", "add", "repo_wiki"], cwd=worktree, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )

    phase_config = MagicMock()
    phase_config.repo_wiki_path = "repo_wiki"
    phase = PlanPhase.__new__(PlanPhase)
    phase._config = phase_config

    entries = [
        _entry("re-discovery of A"),
        _entry("genuinely new insight"),
        _entry("re-discovery of B"),
    ]
    decisions = [
        CorroborationDecision(
            should_corroborate=True,
            canonical_title=canonical_a.title,
            canonical_id=canonical_a.id,
            canonical_path=path_a,
        ),
        CorroborationDecision(),  # no match → writes
        CorroborationDecision(
            should_corroborate=True,
            canonical_title=canonical_b.title,
            canonical_id=canonical_b.id,
            canonical_path=path_b,
        ),
    ]

    topic_dir = path_a.parent
    files_before = {p.name for p in topic_dir.glob("*.md")}

    phase._wiki_commit_compiler_entries(
        tracked_store=store,
        worktree_path=worktree,
        repo="o/r",
        issue_number=55,
        phase="plan",
        entries=entries,
        decisions=decisions,
    )

    # Both canonicals bumped exactly once.
    assert "corroborations: 2" in path_a.read_text(encoding="utf-8")
    assert "corroborations: 2" in path_b.read_text(encoding="utf-8")

    # Exactly one new file landed — the middle entry.
    files_after = {p.name for p in topic_dir.glob("*.md")}
    new_files = files_after - files_before
    assert len(new_files) == 1, (
        f"expected exactly one new file for the write, got {new_files}"
    )
    new_text = (topic_dir / next(iter(new_files))).read_text(encoding="utf-8")
    assert "# genuinely new insight" in new_text


@pytest.mark.asyncio
async def test_precompute_on_fresh_topic_passes_empty_candidates(
    tmp_path: Path,
) -> None:
    """Fresh topic: ingesting into a topic with no existing entries must
    still call the compiler (so a single existing entry in another topic
    doesn't silently skip dedup) and pass an empty candidate list."""
    from plan_phase import PlanPhase

    _worktree, store = _git_seeded_tracked_store(tmp_path)
    # Seed an unrelated topic so the repo has SOME tracked entries but
    # the target topic dir is empty.
    store.write_entry(
        "o/r",
        _topical_entry("elsewhere", topic_hint="gotchas"),
        topic="gotchas",
    )

    recorded: list[int] = []
    compiler = MagicMock()

    async def fake_dedup(
        *, repo_slug, entry, existing_entries, topic, min_confidence="medium"
    ):
        recorded.append(len(existing_entries))
        return CorroborationDecision()

    compiler.dedup_or_corroborate = fake_dedup
    phase = PlanPhase.__new__(PlanPhase)
    phase._wiki_compiler = compiler

    new_entry = _topical_entry("first patterns entry", topic_hint="patterns")
    decisions = await phase._precompute_corroboration(
        tracked_store=store,
        repo="o/r",
        entries=[new_entry],
    )

    assert recorded == [0]
    assert decisions[0].should_corroborate is False
