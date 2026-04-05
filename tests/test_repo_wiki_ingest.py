"""Tests for repo_wiki_ingest — knowledge extraction from phase outputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_wiki import RepoWikiStore
from repo_wiki_ingest import _extract_sections, ingest_from_plan, ingest_from_review


@pytest.fixture
def store(tmp_path: Path) -> RepoWikiStore:
    return RepoWikiStore(tmp_path / "wiki")


REPO = "acme/widget"


class TestExtractSections:
    def test_parses_markdown_headings(self) -> None:
        text = "## Architecture\nService layer.\n\n## Testing\nUse pytest.\n"
        sections = _extract_sections(text)
        assert "architecture" in sections
        assert "testing" in sections
        assert "Service layer." in sections["architecture"]

    def test_empty_text(self) -> None:
        assert _extract_sections("") == {}

    def test_no_headings(self) -> None:
        assert _extract_sections("Just plain text.") == {}


class TestIngestFromPlan:
    def test_extracts_architecture(self, store: RepoWikiStore) -> None:
        plan = (
            "## Architecture\n"
            "The system uses a three-layer architecture with service, domain, and infra layers. "
            "Each layer has clear boundaries.\n"
            "\n## Risks\nConcurrency issues with shared state.\n"
        )
        count = ingest_from_plan(store, REPO, 42, plan)
        assert count >= 1

    def test_empty_plan(self, store: RepoWikiStore) -> None:
        assert ingest_from_plan(store, REPO, 1, "") == 0

    def test_no_repo(self, store: RepoWikiStore) -> None:
        assert (
            ingest_from_plan(store, "", 1, "## Architecture\nSome content here.") == 0
        )

    def test_short_sections_skipped(self, store: RepoWikiStore) -> None:
        plan = "## Architecture\nToo short.\n"
        count = ingest_from_plan(store, REPO, 1, plan)
        assert count == 0


class TestIngestFromReview:
    def test_extracts_feedback(self, store: RepoWikiStore) -> None:
        feedback = (
            "The PR has good test coverage but the error handling in the API layer "
            "should use structured responses instead of plain strings. Also, the "
            "database connection pooling configuration needs to be externalized."
        )
        count = ingest_from_review(store, REPO, 55, feedback)
        assert count >= 1

    def test_empty_feedback(self, store: RepoWikiStore) -> None:
        assert ingest_from_review(store, REPO, 1, "") == 0

    def test_short_feedback_skipped(self, store: RepoWikiStore) -> None:
        assert ingest_from_review(store, REPO, 1, "LGTM") == 0
