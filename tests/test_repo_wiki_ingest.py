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


class TestGitBackedIngest:
    """Phase 3: `git_backed=True` routes through per-entry writes + per-issue log."""

    def test_plan_writes_per_entry_files_and_skips_legacy(
        self, store: RepoWikiStore
    ) -> None:
        plan = (
            "## Architecture\n"
            + ("Service A talks to service B via a queue. " * 5)
            + "\n\n## Testing\n"
            + ("Run unit tests before integration tests. " * 5)
        )
        count = ingest_from_plan(store, REPO, 42, plan, git_backed=True)

        assert count == 2
        arch_dir = store._wiki_root / REPO / "architecture"
        testing_dir = store._wiki_root / REPO / "testing"
        assert len(list(arch_dir.glob("*.md"))) == 1
        assert len(list(testing_dir.glob("*.md"))) == 1

        arch_entry = next(arch_dir.glob("*.md")).read_text()
        assert arch_entry.startswith("---\n")
        assert "source_phase: plan" in arch_entry

        # Legacy topic files should NOT have been written.
        assert not (store._wiki_root / REPO / "architecture.md").exists()
        assert not (store._wiki_root / REPO / "testing.md").exists()

        # Per-issue log stamped with issue_number.
        import json as _json

        log = (
            (store._wiki_root / REPO / "log" / "42.jsonl")
            .read_text()
            .strip()
            .splitlines()
        )
        rec = _json.loads(log[0])
        assert rec["phase"] == "plan"
        assert rec["issue_number"] == 42
        assert rec["entries"] == 2

    def test_review_writes_single_patterns_entry(self, store: RepoWikiStore) -> None:
        feedback = "Long review feedback body. " * 20
        count = ingest_from_review(store, REPO, 101, feedback, git_backed=True)

        assert count == 1
        patterns_dir = store._wiki_root / REPO / "patterns"
        files = list(patterns_dir.glob("*.md"))
        assert len(files) == 1
        entry_text = files[0].read_text()
        assert "source_phase: review" in entry_text
        assert "issue-101" in files[0].name

        import json as _json

        log = (
            (store._wiki_root / REPO / "log" / "101.jsonl")
            .read_text()
            .strip()
            .splitlines()
        )
        rec = _json.loads(log[0])
        assert rec["phase"] == "review"
        assert rec["issue_number"] == 101

    def test_default_git_backed_false_preserves_legacy_path(
        self, store: RepoWikiStore
    ) -> None:
        """Default path unchanged — existing callers see the legacy
        topic-level layout until they explicitly opt in."""
        plan = "## Architecture\n" + ("Service A talks to service B via a queue. " * 5)
        count = ingest_from_plan(store, REPO, 50, plan)

        assert count >= 1
        assert (store._wiki_root / REPO / "architecture.md").exists()

    def test_partial_failure_rolls_back_written_entries(
        self, store: RepoWikiStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If one write_entry raises mid-loop, every prior write in the
        batch is removed so orphans can't leak into future ingests.
        """
        plan = (
            "## Architecture\n"
            + ("Service A talks to service B via a queue. " * 5)
            + "\n\n## Testing\n"
            + ("Run unit tests before integration tests. " * 5)
        )

        calls: list[str] = []
        original = store.write_entry

        def flaky_write_entry(repo_slug: str, entry, *, topic: str):
            calls.append(topic)
            if topic == "testing":  # second call blows up
                raise OSError("disk full")
            return original(repo_slug, entry, topic=topic)

        monkeypatch.setattr(store, "write_entry", flaky_write_entry)

        with pytest.raises(OSError, match="disk full"):
            ingest_from_plan(store, REPO, 77, plan, git_backed=True)

        # First write landed on disk; rollback should have removed it.
        arch_dir = store._wiki_root / REPO / "architecture"
        assert arch_dir.is_dir() is False or list(arch_dir.glob("*.md")) == []

        # No log record should exist — log append only runs after all writes.
        assert not (store._wiki_root / REPO / "log" / "77.jsonl").exists()


# ---------------------------------------------------------------------------
# ingest_phase_output — end-to-end contradiction detection
# ---------------------------------------------------------------------------


async def test_ingest_phase_output_marks_contradicted_siblings(tmp_path: Path) -> None:
    """End-to-end: ingest entry A, then ingest contradicting B → A.superseded_by = B.id."""
    from unittest.mock import AsyncMock

    from repo_wiki import RepoWikiStore, WikiEntry
    from repo_wiki_ingest import ingest_phase_output
    from wiki_compiler import ContradictedEntry, ContradictionCheck

    store = RepoWikiStore(tmp_path / "wiki")

    # First ingest: one entry, no contradictions.
    entry_a = WikiEntry(
        id="01HQ0000000000000000000000",
        title="Use X always",
        content="Always use X.",
        source_type="plan",
        topic="patterns",
    )
    compiler = AsyncMock()
    compiler.detect_contradictions = AsyncMock(return_value=ContradictionCheck())
    await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=[entry_a],
        compiler=compiler,
    )

    # Second ingest: entry contradicts A.
    contradiction_reply = ContradictionCheck(
        contradicts=[
            ContradictedEntry(
                id="01HQ0000000000000000000000",
                reason="reverses guidance",
            )
        ]
    )
    entry_b = WikiEntry(
        id="01HQ1111111111111111111111",
        title="Never use X",
        content="Never use X; prefer Y.",
        source_type="plan",
        topic="patterns",
    )
    compiler.detect_contradictions = AsyncMock(return_value=contradiction_reply)
    result = await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=[entry_b],
        compiler=compiler,
    )
    assert result.contradictions_marked == 1

    # A now has superseded_by set.
    topic_path = store._repo_dir("acme/widget") / "patterns.md"
    on_disk = store._load_topic_entries(topic_path)
    a_on_disk = next(e for e in on_disk if e.id == entry_a.id)
    assert a_on_disk.superseded_by == entry_b.id
    assert a_on_disk.superseded_reason == "reverses guidance"

    # query() excludes superseded A, keeps current B
    out = store.query("acme/widget", topics=["patterns"])
    assert "Never use X" in out
    assert "Use X always" not in out


async def test_ingest_phase_output_emits_wiki_supersedes_event(tmp_path):
    """When an event_bus is provided, every contradiction publishes a WIKI_SUPERSEDES event."""
    from unittest.mock import AsyncMock

    from events import EventBus, EventType, HydraFlowEvent
    from repo_wiki import RepoWikiStore, WikiEntry
    from repo_wiki_ingest import ingest_phase_output
    from wiki_compiler import ContradictedEntry, ContradictionCheck

    store = RepoWikiStore(tmp_path / "wiki")
    event_bus = EventBus()
    published: list[HydraFlowEvent] = []

    async def capture(event: HydraFlowEvent) -> None:
        published.append(event)

    event_bus.publish = capture  # type: ignore[method-assign]

    entry_a = WikiEntry(
        id="01HQ0000000000000000000000",
        title="Use X",
        content="Always X.",
        source_type="plan",
        topic="patterns",
    )
    compiler = AsyncMock()
    compiler.detect_contradictions = AsyncMock(return_value=ContradictionCheck())
    await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=[entry_a],
        compiler=compiler,
        event_bus=event_bus,
    )
    assert published == []

    entry_b = WikiEntry(
        id="01HQ1111111111111111111111",
        title="Never X",
        content="Never X.",
        source_type="plan",
        topic="patterns",
    )
    reply = ContradictionCheck(
        contradicts=[ContradictedEntry(id=entry_a.id, reason="reverses")]
    )
    compiler.detect_contradictions = AsyncMock(return_value=reply)
    await ingest_phase_output(
        store=store,
        repo="acme/widget",
        entries=[entry_b],
        compiler=compiler,
        event_bus=event_bus,
    )

    assert len(published) == 1
    event = published[0]
    assert event.type == EventType.WIKI_SUPERSEDES
    assert event.data["repo"] == "acme/widget"
    assert event.data["superseded_id"] == entry_a.id
    assert event.data["superseded_by"] == entry_b.id
    assert event.data["reason"] == "reverses"


async def test_ingest_phase_output_rejects_duplicate_ids(tmp_path):
    from unittest.mock import AsyncMock

    from repo_wiki import RepoWikiStore, WikiEntry
    from repo_wiki_ingest import ingest_phase_output

    store = RepoWikiStore(tmp_path / "wiki")
    dup = WikiEntry(
        id="01HQ0000000000000000000000",
        title="x",
        content="y",
        source_type="plan",
        topic="patterns",
    )
    dup2 = WikiEntry(
        id="01HQ0000000000000000000000",  # same id — invalid
        title="z",
        content="w",
        source_type="plan",
        topic="patterns",
    )
    compiler = AsyncMock()
    with pytest.raises(ValueError, match="duplicate"):
        await ingest_phase_output(
            store=store,
            repo="acme/widget",
            entries=[dup, dup2],
            compiler=compiler,
        )


# ---------------------------------------------------------------------------
# entries_from_reflections_log
# ---------------------------------------------------------------------------


def test_entries_from_reflections_log_splits_by_phase_marker():
    from repo_wiki_ingest import entries_from_reflections_log

    log = (
        "--- plan | 2026-04-01 10:00 UTC ---\n"
        "Architecture: always use dependency injection for service modules.\n"
        "\n"
        "--- implement | 2026-04-01 11:00 UTC ---\n"
        "Gotcha: the auth middleware caches tokens for 5 minutes, breaking\n"
        "local-dev hot reload unless you restart uvicorn.\n"
    )
    entries = entries_from_reflections_log(
        log=log,
        repo="acme/widget",
        issue_number=42,
    )
    assert len(entries) == 2
    assert entries[0].source_type == "reflection"
    assert entries[0].source_issue == 42
    assert entries[0].source_repo == "acme/widget"
    assert "dependency injection" in entries[0].content
    assert entries[1].source_type == "reflection"
    assert "auth middleware" in entries[1].content


def test_entries_from_reflections_log_empty_input_returns_empty():
    from repo_wiki_ingest import entries_from_reflections_log

    assert entries_from_reflections_log(log="", repo="x/y", issue_number=1) == []
    assert (
        entries_from_reflections_log(log="   \n\n  ", repo="x/y", issue_number=1) == []
    )


def test_entries_from_reflections_log_drops_blocks_with_no_content():
    from repo_wiki_ingest import entries_from_reflections_log

    log = (
        "--- plan | 2026-04-01 10:00 UTC ---\n"
        "\n"
        "--- implement | 2026-04-01 11:00 UTC ---\n"
        "Actual content here.\n"
    )
    entries = entries_from_reflections_log(log=log, repo="x/y", issue_number=1)
    assert len(entries) == 1
    assert "Actual content" in entries[0].content


def test_entries_from_reflections_log_distinct_ids_per_block():
    from repo_wiki_ingest import entries_from_reflections_log

    log = (
        "--- plan | 2026-04-01 10:00 UTC ---\nA.\n"
        "--- implement | 2026-04-01 11:00 UTC ---\nB.\n"
    )
    entries = entries_from_reflections_log(log=log, repo="x/y", issue_number=1)
    assert entries[0].id != entries[1].id
