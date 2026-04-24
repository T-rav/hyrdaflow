"""Tests for on-PR-merge wiki compilation (P5 wiki-evolution audit).

Before this change, wiki compilation only ran on the RepoWikiLoop
interval (cron-ish). After a PR merged with new entries, agents on
the next issue still saw un-deduped siblings until the loop fired.

P5 adds an explicit compile trigger to PostMergeHandler's post-merge
hook chain. compile_topic_tracked is invoked for every topic that has
≥2 active entries under the tracked layout, running under _safe_hook
so failures don't block the merge path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from post_merge_handler import _compile_tracked_topics_for_merge


def _write_tracked_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    entry_id: str,
    source_issue: int,
) -> None:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    (topic_dir / f"{source_issue:04d}-{entry_id[-6:]}.md").write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {now}\n"
        "status: active\n"
        "---\n"
        f"# Insight {entry_id[-4:]}\n\nBody for entry {entry_id}.\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_compile_runs_for_topics_with_multiple_active_entries(
    tmp_path: Path,
) -> None:
    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(tracked_root, "o/r", "patterns", "01JF000000000000000001", 1)
    _write_tracked_entry(tracked_root, "o/r", "patterns", "01JF000000000000000002", 2)

    compiler = MagicMock()
    compiler.compile_topic_tracked = AsyncMock(return_value=1)

    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root,
        repo_slug="o/r",
        compiler=compiler,
    )

    compiler.compile_topic_tracked.assert_awaited_once()
    call = compiler.compile_topic_tracked.await_args
    assert call.kwargs["repo"] == "o/r"
    assert call.kwargs["topic"] == "patterns"
    assert call.kwargs["tracked_root"] == tracked_root


@pytest.mark.asyncio
async def test_compile_skips_topics_with_single_entry(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(tracked_root, "o/r", "patterns", "01JF000000000000000001", 1)

    compiler = MagicMock()
    compiler.compile_topic_tracked = AsyncMock(return_value=0)

    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root,
        repo_slug="o/r",
        compiler=compiler,
    )

    compiler.compile_topic_tracked.assert_not_awaited()


@pytest.mark.asyncio
async def test_compile_is_noop_when_tracked_root_missing(tmp_path: Path) -> None:
    compiler = MagicMock()
    compiler.compile_topic_tracked = AsyncMock()

    await _compile_tracked_topics_for_merge(
        tracked_root=tmp_path / "does-not-exist",
        repo_slug="o/r",
        compiler=compiler,
    )

    compiler.compile_topic_tracked.assert_not_awaited()


@pytest.mark.asyncio
async def test_compile_aggregates_multiple_topics(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    _write_tracked_entry(tracked_root, "o/r", "patterns", "01JF000000000000000001", 1)
    _write_tracked_entry(tracked_root, "o/r", "patterns", "01JF000000000000000002", 2)
    _write_tracked_entry(tracked_root, "o/r", "testing", "01JF000000000000000003", 3)
    _write_tracked_entry(tracked_root, "o/r", "testing", "01JF000000000000000004", 4)

    compiler = MagicMock()
    compiler.compile_topic_tracked = AsyncMock(return_value=1)

    await _compile_tracked_topics_for_merge(
        tracked_root=tracked_root,
        repo_slug="o/r",
        compiler=compiler,
    )

    assert compiler.compile_topic_tracked.await_count == 2
    topics_called = {
        c.kwargs["topic"] for c in compiler.compile_topic_tracked.await_args_list
    }
    assert topics_called == {"patterns", "testing"}
