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
