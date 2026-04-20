"""Tests for ``repo_wiki.active_lint_tracked``.

Phase 7 — scans the tracked per-entry layout and writes stale flags in
place so ``RepoWikiLoop._maybe_open_maintenance_pr`` sees uncommitted
diffs and opens a ``chore(wiki): maintenance`` PR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from repo_wiki import active_lint_tracked

REPO = "acme/widget"


def _write_entry(
    path: Path,
    *,
    entry_id: str,
    topic: str,
    source_issue: int | str,
    status: str = "active",
    created_at: str | None = None,
    body: str = "Body text.\n",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = created_at or datetime.now(UTC).isoformat()
    frontmatter = (
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: plan\n"
        f"created_at: {created}\n"
        f"status: {status}\n"
        "---\n"
        "\n"
        f"# Entry {entry_id}\n\n{body}"
    )
    path.write_text(frontmatter, encoding="utf-8")


def test_returns_zero_stats_when_repo_missing(tmp_path: Path) -> None:
    result = active_lint_tracked(tmp_path / "repo_wiki", REPO, {42})
    assert result.total_entries == 0
    assert result.entries_marked_stale == 0
    assert result.orphans_pruned == 0


def test_returns_zero_stats_when_topics_empty(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    (root / "acme" / "widget").mkdir(parents=True)
    result = active_lint_tracked(root, REPO, {42})
    assert result.total_entries == 0
    assert "architecture" in result.empty_topics


def test_marks_active_entry_stale_when_source_issue_closed(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    entry_path = root / "acme" / "widget" / "patterns" / "0001-issue-42-x.md"
    _write_entry(entry_path, entry_id="0001", topic="patterns", source_issue=42)

    result = active_lint_tracked(root, REPO, {42})

    assert result.entries_marked_stale == 1
    assert result.total_entries == 1
    text = entry_path.read_text()
    assert "status: stale" in text
    assert "stale_reason: source issue #42 closed" in text


def test_skips_already_stale_entry(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    entry_path = root / "acme" / "widget" / "patterns" / "0001-issue-42-x.md"
    _write_entry(
        entry_path,
        entry_id="0001",
        topic="patterns",
        source_issue=42,
        status="stale",
    )

    result = active_lint_tracked(root, REPO, {42})

    assert result.entries_marked_stale == 0
    assert result.stale_entries == 1


def test_ignores_entry_with_open_source_issue(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    entry_path = root / "acme" / "widget" / "patterns" / "0001-issue-7-x.md"
    _write_entry(entry_path, entry_id="0001", topic="patterns", source_issue=7)

    result = active_lint_tracked(root, REPO, closed_issues={42})

    assert result.entries_marked_stale == 0
    assert "status: active" in entry_path.read_text()


def test_ignores_entry_with_unknown_source_issue(tmp_path: Path) -> None:
    """Synthesis entries carry ``source_issue: unknown``; never stale."""
    root = tmp_path / "repo_wiki"
    entry_path = root / "acme" / "widget" / "patterns" / "0005-issue-unknown-s.md"
    _write_entry(entry_path, entry_id="0005", topic="patterns", source_issue="unknown")

    result = active_lint_tracked(root, REPO, {42})
    assert result.entries_marked_stale == 0


def test_prunes_stale_entries_older_than_90_days(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    old_stale = root / "acme" / "widget" / "patterns" / "0001-issue-42-old.md"
    long_ago = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    _write_entry(
        old_stale,
        entry_id="0001",
        topic="patterns",
        source_issue=42,
        status="stale",
        created_at=long_ago,
    )

    result = active_lint_tracked(root, REPO, set())

    assert not old_stale.exists()
    assert result.orphans_pruned == 1


def test_does_not_prune_fresh_stale_entries(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    fresh_stale = root / "acme" / "widget" / "patterns" / "0001-issue-42-new.md"
    _write_entry(
        fresh_stale,
        entry_id="0001",
        topic="patterns",
        source_issue=42,
        status="stale",
    )

    active_lint_tracked(root, REPO, set())

    assert fresh_stale.exists()


def test_mark_then_prune_in_same_pass_still_keeps_fresh_mark(tmp_path: Path) -> None:
    """A just-marked-stale entry must not be immediately pruned.

    The transition mark→stale happens today (``now``), so the ``created_at``
    of a freshly-marked-stale entry remains its original (recent) value —
    pruning would kick in only 90 days later.
    """
    root = tmp_path / "repo_wiki"
    entry_path = root / "acme" / "widget" / "patterns" / "0001-issue-42-new.md"
    _write_entry(entry_path, entry_id="0001", topic="patterns", source_issue=42)

    result = active_lint_tracked(root, REPO, {42})

    assert entry_path.exists()
    assert result.entries_marked_stale == 1
    assert result.orphans_pruned == 0


def test_writes_are_idempotent(tmp_path: Path) -> None:
    """A second pass with the same inputs is a no-op for already-stale entries."""
    root = tmp_path / "repo_wiki"
    entry_path = root / "acme" / "widget" / "patterns" / "0001-issue-42-x.md"
    _write_entry(entry_path, entry_id="0001", topic="patterns", source_issue=42)

    active_lint_tracked(root, REPO, {42})
    first = entry_path.read_text()

    second_result = active_lint_tracked(root, REPO, {42})

    assert second_result.entries_marked_stale == 0
    assert entry_path.read_text() == first


def test_skips_entries_without_frontmatter(tmp_path: Path) -> None:
    """Malformed files don't crash the lint pass."""
    root = tmp_path / "repo_wiki"
    broken = root / "acme" / "widget" / "patterns" / "0001-issue-42-x.md"
    broken.parent.mkdir(parents=True)
    broken.write_text("# Broken\n\nNo frontmatter here.\n")

    result = active_lint_tracked(root, REPO, {42})

    assert result.total_entries == 0
    assert broken.read_text().startswith("# Broken")


def test_counts_entries_across_topics(tmp_path: Path) -> None:
    root = tmp_path / "repo_wiki"
    _write_entry(
        root / "acme" / "widget" / "patterns" / "0001-issue-1-a.md",
        entry_id="0001",
        topic="patterns",
        source_issue=1,
    )
    _write_entry(
        root / "acme" / "widget" / "gotchas" / "0001-issue-2-b.md",
        entry_id="0001",
        topic="gotchas",
        source_issue=2,
    )
    _write_entry(
        root / "acme" / "widget" / "testing" / "0001-issue-3-c.md",
        entry_id="0001",
        topic="testing",
        source_issue=3,
    )

    result = active_lint_tracked(root, REPO, {2, 3})

    assert result.total_entries == 3
    assert result.entries_marked_stale == 2


def test_old_active_entry_gets_flipped_and_pruned_same_pass(tmp_path: Path) -> None:
    """An active entry whose issue just closed AND is already past the
    90-day window gets flipped stale AND pruned in the same pass.

    Matches the legacy ``active_lint`` semantic (``created_at`` is the
    prune clock, not a separate ``stale_since`` timestamp).  By the time
    an entry is 120 days old it's typically already superseded by a
    compiler synthesis entry, so the wiki stays compact.
    """
    root = tmp_path / "repo_wiki"
    old_path = root / "acme" / "widget" / "patterns" / "0001-issue-42-stale-oldie.md"
    long_ago = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    _write_entry(
        old_path,
        entry_id="0001",
        topic="patterns",
        source_issue=42,
        status="active",
        created_at=long_ago,
    )

    result = active_lint_tracked(root, REPO, {42})

    assert not old_path.exists()
    assert result.entries_marked_stale == 1
    assert result.orphans_pruned == 1
