"""Release-gating scenarios for the wiki-evolution stack.

Covers the session's runtime-affecting PRs:

- **P5 #8400** — ``post_merge_handler._compile_tracked_topics_for_merge``
  calls ``WikiCompiler.compile_topic_tracked`` on every topic that has
  ≥2 active entries after a PR merges.
- **P4 #8401 + B2 #8403** — ``RepoWikiLoop`` runs ``detect_drift``
  every tick, then ``apply_drift_markers`` flips entries citing
  missing files to ``status: stale``.

These scenarios use ``FakeWikiCompiler`` (in-memory call recorder)
and real tracked-layout filesystem state — the on-disk wiki format
is load-bearing for drift detection, so we exercise it end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mockworld.fakes.fake_wiki_compiler import FakeWikiCompiler


def _write_tracked_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    *,
    body: str,
    entry_id: str,
    source_issue: int,
    status: str = "active",
) -> Path:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"{source_issue:04d}-{entry_id[-6:]}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# P5 — post-merge wiki compile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_merge_triggers_wiki_compile_for_multi_entry_topic(
    tmp_path: Path,
) -> None:
    """After a PR merges, topics with ≥2 active entries get compiled."""
    from post_merge_handler import _compile_tracked_topics_for_merge

    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# A\n\nFirst claim.",
        entry_id="01JF000000000000000001",
        source_issue=1,
    )
    _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# B\n\nSecond claim, maybe overlapping.",
        entry_id="01JF000000000000000002",
        source_issue=2,
    )

    compiler = FakeWikiCompiler()

    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root,
        repo_slug="o/r",
        compiler=compiler,
    )

    assert len(compiler.compile_calls) == 1
    call = compiler.compile_calls[0]
    assert call.repo == "o/r"
    assert call.topic == "patterns"
    assert call.tracked_root == tracked_root


@pytest.mark.asyncio
async def test_post_merge_skips_single_entry_topic(tmp_path: Path) -> None:
    """Topics with only one active entry don't trigger a compile."""
    from post_merge_handler import _compile_tracked_topics_for_merge

    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="Only one here.",
        entry_id="01JF000000000000000001",
        source_issue=1,
    )

    compiler = FakeWikiCompiler()
    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root,
        repo_slug="o/r",
        compiler=compiler,
    )

    assert compiler.compile_calls == []


@pytest.mark.asyncio
async def test_post_merge_noop_without_compiler(tmp_path: Path) -> None:
    """Missing WikiCompiler means the hook silently skips (wiki disabled)."""
    from post_merge_handler import _compile_tracked_topics_for_merge

    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="x",
        entry_id="01JF000000000000000001",
        source_issue=1,
    )
    # No assertion on side effects — just verify no exception.
    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root, repo_slug="o/r", compiler=None
    )


@pytest.mark.asyncio
async def test_post_merge_noop_when_repo_slug_empty(tmp_path: Path) -> None:
    """Guard against iterating owner dirs as if they were topics (C1 fix)."""
    from post_merge_handler import _compile_tracked_topics_for_merge

    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="x",
        entry_id="01JF000000000000000001",
        source_issue=1,
    )
    compiler = FakeWikiCompiler()

    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root, repo_slug="", compiler=compiler
    )

    assert compiler.compile_calls == []


# ---------------------------------------------------------------------------
# P4 + B2 — drift detection + auto-stale-marking
# ---------------------------------------------------------------------------


def test_drift_loop_flags_and_marks_missing_file_citation(tmp_path: Path) -> None:
    """End-to-end: seed wiki with a broken citation, run detect_drift
    and apply_drift_markers, verify the entry flipped to stale."""
    from wiki_drift_detector import apply_drift_markers, detect_drift

    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    entry_path = _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="# title\n\nLives in `src/deleted.py:LongGone`.",
        entry_id="01JF000000000000000001",
        source_issue=42,
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert "src/deleted.py" in finding.missing_files

    marked = apply_drift_markers(result.findings)
    assert marked == 1

    updated = entry_path.read_text(encoding="utf-8")
    assert "status: stale" in updated
    assert "stale_reason: drift_detected: src/deleted.py" in updated


def test_drift_loop_leaves_intact_entries_alone(tmp_path: Path) -> None:
    """Entries whose cited files still exist stay active, untouched."""
    from wiki_drift_detector import apply_drift_markers, detect_drift

    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "present.py").write_text("class ReallyHere:\n    pass\n")

    entry_path = _write_tracked_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="See `src/present.py:ReallyHere`.",
        entry_id="01JF000000000000000002",
        source_issue=43,
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )
    assert result.findings == []

    marked = apply_drift_markers(result.findings)
    assert marked == 0
    assert "status: active" in entry_path.read_text(encoding="utf-8")
