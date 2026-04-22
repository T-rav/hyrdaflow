"""Tests for RepoWikiStore — per-repo LLM knowledge base."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_wiki import (
    DEFAULT_TOPICS,
    IngestResult,
    LintResult,
    RepoWikiStore,
    WikiEntry,
    WikiIndex,
)


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    return tmp_path / "repo_wiki"


@pytest.fixture
def store(wiki_root: Path) -> RepoWikiStore:
    return RepoWikiStore(wiki_root)


REPO = "acme/widget"


class TestEnsureRepoDir:
    def test_creates_directory_and_default_topics(self, store: RepoWikiStore) -> None:
        repo_dir = store._ensure_repo_dir(REPO)
        assert repo_dir.exists()
        for topic in DEFAULT_TOPICS:
            assert (repo_dir / f"{topic}.md").exists()
        assert (repo_dir / "index.json").exists()

    def test_idempotent(self, store: RepoWikiStore) -> None:
        store._ensure_repo_dir(REPO)
        store._ensure_repo_dir(REPO)  # should not raise


class TestIngest:
    def test_adds_entries(self, store: RepoWikiStore) -> None:
        entries = [
            WikiEntry(
                title="Watch out for circular imports",
                content="Module A imports B which imports A.",
                source_type="plan",
                source_issue=42,
            ),
        ]
        result = store.ingest(REPO, entries)
        assert isinstance(result, IngestResult)
        assert result.entries_added == 1
        assert result.entries_updated == 0

    def test_updates_existing_entry_by_title(self, store: RepoWikiStore) -> None:
        entry_v1 = WikiEntry(
            title="Auth pattern",
            content="Use JWT tokens.",
            source_type="plan",
            source_issue=1,
        )
        entry_v2 = WikiEntry(
            title="Auth pattern",
            content="Use OAuth2 with refresh tokens.",
            source_type="review",
            source_issue=2,
        )
        store.ingest(REPO, [entry_v1])
        result = store.ingest(REPO, [entry_v2])
        assert result.entries_updated == 1
        assert result.entries_added == 0

    def test_rebuilds_index(self, store: RepoWikiStore) -> None:
        entries = [
            WikiEntry(
                title="Test coverage requirement",
                content="All modules need 80% coverage.",
                source_type="review",
                source_issue=10,
            ),
        ]
        store.ingest(REPO, entries)
        index = store._load_index(REPO)
        assert index is not None
        assert index.total_entries == 1
        assert any(
            "Test coverage requirement" in titles for titles in index.topics.values()
        )

    def test_appends_log(self, store: RepoWikiStore, wiki_root: Path) -> None:
        entries = [
            WikiEntry(
                title="Log test",
                content="Should appear in log.",
                source_type="implement",
                source_issue=5,
            ),
        ]
        store.ingest(REPO, entries)
        log_path = wiki_root / REPO / "log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert '"op": "ingest"' in lines[0]


class TestQuery:
    def test_empty_when_no_wiki(self, store: RepoWikiStore) -> None:
        result = store.query("nonexistent/repo")
        assert result == ""

    def test_returns_markdown_with_entries(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="API rate limiting",
                    content="Use exponential backoff for GitHub API.",
                    source_type="implement",
                    source_issue=7,
                ),
            ],
        )
        result = store.query(REPO)
        assert "Repo Wiki: acme/widget" in result
        assert "API rate limiting" in result
        assert "exponential backoff" in result

    def test_keyword_filtering(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Database migration pattern",
                    content="Always use Alembic for migrations.",
                    source_type="plan",
                ),
                WikiEntry(
                    title="API error handling",
                    content="Return structured error responses.",
                    source_type="plan",
                ),
            ],
        )
        result = store.query(REPO, keywords=["migration"])
        assert "migration" in result.lower()
        # The non-matching entry should be filtered out
        assert "error handling" not in result

    def test_respects_max_chars(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Big entry",
                    content="x" * 5000,
                    source_type="plan",
                ),
            ],
        )
        result = store.query(REPO, max_chars=200)
        assert len(result) <= 200

    def test_topic_filtering(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Test fixture patterns",
                    content="Use pytest fixtures over setUp.",
                    source_type="review",
                ),
                WikiEntry(
                    title="Service layer architecture",
                    content="Separate domain from infrastructure.",
                    source_type="plan",
                ),
            ],
        )
        result = store.query(REPO, topics=["testing"])
        assert "fixture" in result.lower()


class TestLint:
    def test_empty_wiki(self, store: RepoWikiStore) -> None:
        result = store.lint(REPO)
        assert isinstance(result, LintResult)
        assert result.total_entries == 0

    def test_detects_empty_topics(self, store: RepoWikiStore) -> None:
        store._ensure_repo_dir(REPO)
        result = store.lint(REPO)
        assert len(result.empty_topics) == len(DEFAULT_TOPICS)

    def test_counts_entries(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Pattern A",
                    content="Description A.",
                    source_type="plan",
                ),
                WikiEntry(
                    title="Gotcha B",
                    content="Watch out for B.",
                    source_type="review",
                ),
            ],
        )
        result = store.lint(REPO)
        assert result.total_entries == 2

    def test_detects_stale_entries(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Stale insight",
                    content="This is outdated.",
                    source_type="plan",
                    stale=True,
                ),
            ],
        )
        result = store.lint(REPO)
        assert result.stale_entries == 1


class TestListRepos:
    def test_empty(self, store: RepoWikiStore) -> None:
        assert store.list_repos() == []

    def test_lists_repos_with_wikis(self, store: RepoWikiStore) -> None:
        store.ingest(
            "org/repo-a", [WikiEntry(title="A", content="a", source_type="plan")]
        )
        store.ingest(
            "org/repo-b", [WikiEntry(title="B", content="b", source_type="plan")]
        )
        repos = store.list_repos()
        assert "org/repo-a" in repos
        assert "org/repo-b" in repos


class TestClassifyTopic:
    @pytest.mark.parametrize(
        ("title", "content", "expected"),
        [
            (
                "Module layout",
                "directory structure of the service layer",
                "architecture",
            ),
            (
                "Common pitfall with async",
                "gotcha when using asyncio.gather",
                "gotchas",
            ),
            (
                "pytest fixtures guide",
                "use conftest.py for shared test fixtures",
                "testing",
            ),
            ("Upgrade numpy", "dependency needs version bump to 2.0", "dependencies"),
            (
                "Code style convention",
                "use this pattern for error handling",
                "patterns",
            ),
        ],
    )
    def test_classifies_correctly(
        self,
        store: RepoWikiStore,
        title: str,
        content: str,
        expected: str,
    ) -> None:
        entry = WikiEntry(title=title, content=content, source_type="plan")
        assert store._classify_topic(entry) == expected


class TestRoundTrip:
    """Entries survive write → read cycle via JSON code blocks."""

    def test_entries_round_trip(self, store: RepoWikiStore) -> None:
        original = WikiEntry(
            title="Round trip test",
            content="Content with special chars: <>&\"'",
            source_type="implement",
            source_issue=99,
        )
        store.ingest(REPO, [original])

        # Read back
        repo_dir = store._repo_dir(REPO)
        topic = store._classify_topic(original)
        topic_path = repo_dir / f"{topic}.md"
        entries = store._load_topic_entries(topic_path)
        assert len(entries) == 1
        assert entries[0].title == original.title
        assert entries[0].content == original.content
        assert entries[0].source_issue == 99


class TestActiveLint:
    """Tests for the self-healing active lint pass."""

    def test_marks_entries_stale_for_closed_issues(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Insight from closed issue",
                    content="Something learned.",
                    source_type="plan",
                    source_issue=99,
                ),
            ],
        )
        result = store.active_lint(REPO, closed_issues={99})
        assert result.entries_marked_stale == 1
        assert result.stale_entries == 1

    def test_flags_old_stale_entries_instead_of_pruning(
        self, store: RepoWikiStore
    ) -> None:
        # Phase 1: 90-day hard-prune replaced by review_candidates_flagged counter.
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Ancient stale entry",
                    content="Very old.",
                    source_type="plan",
                    stale=True,
                    created_at="2020-01-01T00:00:00+00:00",
                ),
            ],
        )
        result = store.active_lint(REPO)
        assert result.orphans_pruned == 0
        assert result.review_candidates_flagged >= 1

    def test_preserves_fresh_stale_entries(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Recently stale",
                    content="Just flagged.",
                    source_type="plan",
                    stale=True,
                    # created_at defaults to now, so it's fresh
                ),
            ],
        )
        result = store.active_lint(REPO)
        assert result.orphans_pruned == 0
        assert result.stale_entries == 1

    def test_rebuilds_index_after_changes(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Will be marked stale",
                    content="From closed issue.",
                    source_type="plan",
                    source_issue=50,
                ),
            ],
        )
        result = store.active_lint(REPO, closed_issues={50})
        assert result.index_rebuilt is True

    def test_updates_last_lint_timestamp(self, store: RepoWikiStore) -> None:
        store._ensure_repo_dir(REPO)
        store.active_lint(REPO)
        index = store._load_index(REPO)
        assert index is not None
        assert index.last_lint is not None

    def test_no_rebuild_when_unchanged(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [WikiEntry(title="Stable", content="Not stale.", source_type="plan")],
        )
        result = store.active_lint(REPO)
        assert result.index_rebuilt is False

    def test_handles_unparseable_created_at(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Bad timestamp",
                    content="Stale with bad date.",
                    source_type="plan",
                    stale=True,
                    created_at="not-a-date",
                ),
            ],
        )
        # Should not raise — age_days falls back to 0, entry preserved
        result = store.active_lint(REPO)
        assert result.stale_entries == 1
        assert result.orphans_pruned == 0

    def test_closed_issues_none_default(self, store: RepoWikiStore) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="From issue",
                    content="Something.",
                    source_type="plan",
                    source_issue=42,
                ),
            ],
        )
        result = store.active_lint(REPO, closed_issues=None)
        assert result.entries_marked_stale == 0


class TestDedupTracking:
    """Tests for ingest deduplication."""

    def test_not_ingested_initially(self, store: RepoWikiStore) -> None:
        store._ensure_repo_dir(REPO)
        assert store.is_ingested(REPO, 42, "review") is False

    def test_mark_and_check(self, store: RepoWikiStore) -> None:
        store._ensure_repo_dir(REPO)
        store.mark_ingested(REPO, 42, "review")
        assert store.is_ingested(REPO, 42, "review") is True
        # Different source_type is not deduped
        assert store.is_ingested(REPO, 42, "plan") is False
        # Different issue is not deduped
        assert store.is_ingested(REPO, 99, "review") is False

    def test_survives_reinstantiation(self, wiki_root: Path) -> None:
        store1 = RepoWikiStore(wiki_root)
        store1._ensure_repo_dir(REPO)
        store1.mark_ingested(REPO, 10, "plan")

        store2 = RepoWikiStore(wiki_root)
        assert store2.is_ingested(REPO, 10, "plan") is True


class TestWikiIndexModel:
    def test_serialization(self) -> None:
        index = WikiIndex(
            repo_slug="acme/widget",
            topics={"patterns": ["A", "B"]},
            total_entries=2,
        )
        data = index.model_dump()
        assert data["repo_slug"] == "acme/widget"
        assert data["total_entries"] == 2
        assert "patterns" in data["topics"]


import re


def test_wiki_entry_auto_generates_id():
    e = WikiEntry(title="t", content="c", source_type="plan")
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", e.id) is not None


def test_wiki_entry_two_entries_get_distinct_ids():
    a = WikiEntry(title="t", content="c", source_type="plan")
    b = WikiEntry(title="t", content="c", source_type="plan")
    assert a.id != b.id


def test_wiki_entry_accepts_topic_and_source_repo():
    e = WikiEntry(
        title="t",
        content="c",
        source_type="plan",
        topic="architecture",
        source_repo="acme/widget",
    )
    assert e.topic == "architecture"
    assert e.source_repo == "acme/widget"


def test_wiki_entry_topic_and_source_repo_default_to_none():
    e = WikiEntry(title="t", content="c", source_type="plan")
    assert e.topic is None
    assert e.source_repo is None


class TestListReposLayoutCompat:
    """list_repos must accept both legacy (index.json) and new (index.md) layouts.

    The git-backed wiki migration lands index.md in a separate PR before
    callers switch away from index.json, so during the migration window both
    files may coexist.
    """

    def test_list_repos_accepts_new_layout_index_md(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "w"
        repo = wiki_root / "owner" / "repo"
        repo.mkdir(parents=True)
        (repo / "index.md").write_text("# index\n")

        store = RepoWikiStore(wiki_root)
        assert store.list_repos() == ["owner/repo"]

    def test_list_repos_accepts_legacy_layout_index_json(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "w"
        repo = wiki_root / "legacy-owner" / "legacy-repo"
        repo.mkdir(parents=True)
        (repo / "index.json").write_text("{}")

        store = RepoWikiStore(wiki_root)
        assert store.list_repos() == ["legacy-owner/legacy-repo"]

    def test_list_repos_skips_dirs_without_index(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "w"
        (wiki_root / "stale-owner" / "no-index").mkdir(parents=True)

        store = RepoWikiStore(wiki_root)
        assert store.list_repos() == []


def test_wiki_entry_temporal_defaults():
    e = WikiEntry(title="t", content="c", source_type="plan")
    assert e.valid_from == e.created_at
    assert e.valid_to is None
    assert e.superseded_by is None
    assert e.superseded_reason is None
    assert e.confidence == "medium"


def test_wiki_entry_temporal_explicit_values():
    e = WikiEntry(
        title="t",
        content="c",
        source_type="plan",
        valid_from="2026-01-01T00:00:00+00:00",
        valid_to="2027-01-01T00:00:00+00:00",
        superseded_by="01HQ0000000000000000000000",
        superseded_reason="replaced by X",
        confidence="high",
    )
    assert e.valid_to == "2027-01-01T00:00:00+00:00"
    assert e.superseded_by == "01HQ0000000000000000000000"
    assert e.confidence == "high"


def test_wiki_entry_confidence_rejects_invalid():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        WikiEntry(title="t", content="c", source_type="plan", confidence="maybe")


def test_wiki_entry_backward_compat_loads_old_shape():
    # Simulate loading an entry missing temporal fields (old on-disk format)
    e = WikiEntry.model_validate(
        {
            "title": "legacy",
            "content": "c",
            "source_type": "plan",
            "created_at": "2025-06-01T00:00:00+00:00",
            "updated_at": "2025-06-01T00:00:00+00:00",
            "stale": False,
        }
    )
    assert e.valid_from == e.created_at  # defaulted from created_at
    assert e.valid_to is None
    assert e.superseded_by is None
    assert e.confidence == "medium"


# ---------------------------------------------------------------------------
# Staleness filtering in query()
# ---------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta


def test_query_excludes_superseded_entries(store, tmp_path):
    store.ingest(
        REPO,
        [
            WikiEntry(
                title="old rule", content="A", source_type="plan", topic="patterns"
            ),
        ],
    )
    # Simulate another ingest that supersedes the first (we'll wire the
    # contradiction detector in PR 2; here we set superseded_by directly)
    index_dir = store._repo_dir(REPO)
    topic_path = index_dir / "patterns.md"
    entries = store._load_topic_entries(topic_path)
    assert len(entries) == 1
    superseded = entries[0].model_copy(
        update={"superseded_by": "01HQ0000000000000000000000"}
    )
    store._write_topic_page(topic_path, "patterns", [superseded])

    out = store.query(REPO, topics=["patterns"])
    assert "old rule" not in out


def test_query_excludes_expired_entries(store):
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    expired = WikiEntry(
        title="expired rule",
        content="A",
        source_type="plan",
        topic="patterns",
        valid_to=past,
    )
    store.ingest(REPO, [expired])
    out = store.query(REPO, topics=["patterns"])
    assert "expired rule" not in out


def test_query_includes_current_entries(store):
    current = WikiEntry(
        title="current rule",
        content="A",
        source_type="plan",
        topic="patterns",
    )
    store.ingest(REPO, [current])
    out = store.query(REPO, topics=["patterns"])
    assert "current rule" in out


def test_active_lint_does_not_prune_old_entries(store):
    old_date = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    old_entry = WikiEntry(
        title="ancient rule",
        content="A",
        source_type="plan",
        topic="patterns",
        created_at=old_date,
        updated_at=old_date,
        stale=True,  # stale marker set
    )
    store.ingest(REPO, [old_entry])

    result = store.active_lint(REPO, closed_issues=set())
    assert result.orphans_pruned == 0
    # Entry is still on disk
    topic_path = store._repo_dir(REPO) / "patterns.md"
    entries = store._load_topic_entries(topic_path)
    assert any(e.title == "ancient rule" for e in entries)


def test_active_lint_still_marks_stale_when_source_issue_closed(store):
    e = WikiEntry(
        title="closed issue entry",
        content="Architecture detail.",
        source_type="plan",
        topic="architecture",
        source_issue=42,
    )
    store.ingest(REPO, [e])

    result = store.active_lint(REPO, closed_issues={42})
    assert result.entries_marked_stale == 1

    # Find entry across all topic pages (classifier picks the actual topic)
    repo_dir = store._repo_dir(REPO)
    all_entries = []
    for topic_file in repo_dir.glob("*.md"):
        if topic_file.stem in ("index",):
            continue
        all_entries.extend(store._load_topic_entries(topic_file))
    assert any(e.title == "closed issue entry" and e.stale for e in all_entries)


def test_active_lint_flags_old_entries_in_result_but_keeps_them(store):
    old_date = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    old_entry = WikiEntry(
        title="ancient rule",
        content="A",
        source_type="plan",
        topic="patterns",
        created_at=old_date,
        updated_at=old_date,
        stale=True,
    )
    store.ingest(REPO, [old_entry])

    result = store.active_lint(REPO, closed_issues=set())
    # New semantics: report flagged count, do not prune
    assert getattr(result, "review_candidates_flagged", 0) >= 1
