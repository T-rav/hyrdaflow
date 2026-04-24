"""Temporal annotator — turns created_at + corroboration counts into
short stability tags the planner/reviewer can read alongside the entry
body. Pure function, no I/O, no LLM calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repo_wiki import WikiEntry, annotate_entries_with_temporal_tags


def _entry(
    *,
    title: str,
    created_at: datetime,
    corroborations: int = 1,
) -> WikiEntry:
    return WikiEntry(
        title=title,
        content="body",
        source_type="review",
        created_at=created_at.isoformat(),
        corroborations=corroborations,
    )


def test_recently_created_entry_is_tagged_recent() -> None:
    now = datetime.now(UTC)
    young = _entry(title="x", created_at=now - timedelta(days=3))

    [(entry, tag)] = annotate_entries_with_temporal_tags([young], now=now)

    assert entry.title == "x"
    assert tag == "recently added"


def test_months_old_entry_is_tagged_stable_for_n_months() -> None:
    now = datetime.now(UTC)
    old = _entry(title="y", created_at=now - timedelta(days=200))

    [(_e, tag)] = annotate_entries_with_temporal_tags([old], now=now)

    assert tag == "stable for 6 months"


def test_year_old_entry_is_tagged_stable_for_one_year() -> None:
    now = datetime.now(UTC)
    ancient = _entry(title="z", created_at=now - timedelta(days=400))

    [(_e, tag)] = annotate_entries_with_temporal_tags([ancient], now=now)

    assert tag == "stable for 1 year"


def test_multi_year_old_entry_uses_years_plural() -> None:
    now = datetime.now(UTC)
    ancient = _entry(title="z", created_at=now - timedelta(days=800))

    [(_e, tag)] = annotate_entries_with_temporal_tags([ancient], now=now)

    assert tag == "stable for 2 years"


def test_high_corroboration_is_reflected_in_tag() -> None:
    """Entries with many corroborations get a (+N) suffix so the reader
    can see how independently-re-discovered the claim is at a glance."""
    now = datetime.now(UTC)
    e = _entry(title="q", created_at=now - timedelta(days=200), corroborations=12)

    [(_e, tag)] = annotate_entries_with_temporal_tags([e], now=now)

    assert tag == "stable for 6 months (+12)"


def test_single_corroboration_does_not_add_suffix() -> None:
    """(+1) would be noise on every entry — skip the suffix until >=2."""
    now = datetime.now(UTC)
    e = _entry(title="q", created_at=now - timedelta(days=200), corroborations=1)

    [(_e, tag)] = annotate_entries_with_temporal_tags([e], now=now)

    assert tag == "stable for 6 months"


def test_empty_input_returns_empty_list() -> None:
    now = datetime.now(UTC)

    assert annotate_entries_with_temporal_tags([], now=now) == []


def test_malformed_created_at_tags_as_age_unknown() -> None:
    """Never crash on bad timestamps — entry passes through with a
    placeholder tag."""
    e = WikiEntry(
        title="w",
        content="body",
        source_type="review",
        created_at="not a date",
    )

    [(_e, tag)] = annotate_entries_with_temporal_tags([e], now=datetime.now(UTC))

    assert tag == "age unknown"


# ----------------------------------------------------------------------
# Integration — query_with_tags returns a title → tag map alongside
# the markdown so callers can weave tags into the injected prompt.
# ----------------------------------------------------------------------

import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from repo_wiki import RepoWikiStore  # noqa: E402


@pytest.fixture
def tracked_store(tmp_path: Path) -> RepoWikiStore:
    root = tmp_path / "tracked"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "seed").write_text("x")
    subprocess.run(
        ["git", "add", "seed"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
    )
    return RepoWikiStore(wiki_root=root, tracked_root=root)


def test_query_with_tags_returns_title_to_tag_map_for_corroborated_entry(
    tracked_store: RepoWikiStore,
) -> None:
    """query_with_tags must emit the markdown body and a
    ``title → stability-tag`` dict so ``_inject_repo_wiki`` can weave
    tags inline."""
    old_date = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    entry = WikiEntry(
        title="Always use factories",
        content="Details about factories.",
        source_type="review",
        source_issue=1,
        created_at=old_date,
        corroborations=4,
    )
    tracked_store.write_entry("o/r", entry, topic="patterns")

    markdown, tags = tracked_store.query_with_tags("o/r")

    assert "Always use factories" in markdown
    tag = tags.get("Always use factories")
    assert tag is not None
    assert "stable for" in tag
    assert "+4" in tag


# ----------------------------------------------------------------------
# Direct unit tests for _weave_temporal_tags.
# ----------------------------------------------------------------------

from base_runner import _weave_temporal_tags  # noqa: E402


def test_weave_temporal_tags_appends_italic_line_after_matching_h3() -> None:
    markdown = "## Patterns\n\n### Always use factories\nBody text.\n"
    tags = {"Always use factories": "stable for 6 months (+4)"}

    woven = _weave_temporal_tags(markdown, tags)

    assert "### Always use factories\n*(stable for 6 months (+4))*" in woven


def test_weave_temporal_tags_noop_on_empty_tags() -> None:
    markdown = "### x\nbody\n"
    assert _weave_temporal_tags(markdown, {}) == markdown


def test_weave_temporal_tags_noop_on_empty_markdown() -> None:
    assert _weave_temporal_tags("", {"x": "y"}) == ""


def test_weave_temporal_tags_ignores_h2_headings() -> None:
    """Only ### (entry) headings get tagged — ## are topic sections."""
    markdown = "## Patterns\n### foo\nbody\n"
    tags = {"Patterns": "stale", "foo": "recent"}

    woven = _weave_temporal_tags(markdown, tags)

    assert "## Patterns\n*(stale)*" not in woven
    assert "### foo\n*(recent)*" in woven
