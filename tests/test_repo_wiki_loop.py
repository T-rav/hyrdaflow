"""Tests for RepoWikiLoop — background wiki lint worker."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from base_background_loop import LoopDeps
from repo_wiki import RepoWikiStore, WikiEntry
from repo_wiki_loop import RepoWikiLoop


def _make_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=MagicMock(),
        interval_cb=None,
    )


def _make_loop(wiki_root: Path) -> RepoWikiLoop:
    config = _make_config(wiki_root)
    store = RepoWikiStore(wiki_root)
    return RepoWikiLoop(config=config, wiki_store=store, deps=_make_deps())


def _make_config(wiki_root: Path) -> MagicMock:
    """Minimal config mock that does not pollute the filesystem.

    `RepoWikiLoop.__init__` calls `config.data_path(...)` to derive the
    maintenance-queue path. A bare MagicMock returns a mock that, once
    `.parent.mkdir()` fires via `MaintenanceQueue._save`, materialises a
    `MagicMock/mock.data_path()/<id>/` directory at repo root. Pinning
    `data_path.return_value` to a tmp path keeps writes inside the test's
    sandbox, and disabling `repo_wiki_git_backed` avoids the `repo_root`
    path that would repeat the same mistake.
    """
    config = MagicMock()
    config.repo_wiki_interval = 3600
    config.dry_run = False
    config.repo_wiki_git_backed = False
    config.data_path.return_value = wiki_root / "wiki_maint_queue.json"
    return config


class TestDefaultInterval:
    def test_returns_config_interval(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path / "wiki")
        assert loop._get_default_interval() == 3600


class TestDoWork:
    @pytest.mark.asyncio
    async def test_no_repos(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path / "wiki")
        result = await loop._do_work()
        assert result is not None
        assert result["repos"] == 0

    @pytest.mark.asyncio
    async def test_lints_existing_repos(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        store = RepoWikiStore(wiki_root)
        store.ingest(
            "org/repo",
            [
                WikiEntry(
                    title="Some pattern",
                    content="Details here.",
                    source_type="plan",
                ),
            ],
        )

        config = _make_config(wiki_root)
        loop = RepoWikiLoop(config=config, wiki_store=store, deps=_make_deps())

        result = await loop._do_work()
        assert result is not None
        assert result["repos"] == 1
        assert result["total_entries"] >= 1

    @pytest.mark.asyncio
    async def test_passes_closed_issues_from_state(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        store = RepoWikiStore(wiki_root)
        store.ingest(
            "org/repo",
            [
                WikiEntry(
                    title="Insight from issue 42",
                    content="Learned something.",
                    source_type="plan",
                    source_issue=42,
                ),
            ],
        )

        config = _make_config(wiki_root)

        # Mock StateTracker with a terminal outcome for issue 42
        from models import IssueOutcome, IssueOutcomeType

        state = MagicMock()
        state.get_all_outcomes.return_value = {
            "42": IssueOutcome(
                outcome=IssueOutcomeType.MERGED,
                reason="PR merged",
                closed_at="2026-01-01T00:00:00Z",
                phase="review",
            ),
        }

        loop = RepoWikiLoop(
            config=config, wiki_store=store, deps=_make_deps(), state=state
        )
        result = await loop._do_work()
        assert result is not None
        assert result["entries_marked_stale"] == 1

    @pytest.mark.asyncio
    async def test_compilation_runs_when_compiler_present(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock

        wiki_root = tmp_path / "wiki"
        store = RepoWikiStore(wiki_root)
        # Seed 5 entries in same topic to hit compilation threshold
        store.ingest(
            "org/repo",
            [
                WikiEntry(
                    title=f"Module layer {i}",
                    content=f"Architecture detail {i} about service layers.",
                    source_type="plan",
                    source_issue=i,
                )
                for i in range(5)
            ],
        )

        config = _make_config(wiki_root)

        compiler = MagicMock()
        compiler.compile_topic = AsyncMock(return_value=3)  # 5 → 3

        loop = RepoWikiLoop(
            config=config,
            wiki_store=store,
            deps=_make_deps(),
            wiki_compiler=compiler,
        )
        result = await loop._do_work()
        assert result is not None
        assert result["entries_compiled"] == 2  # 5 - 3
        compiler.compile_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_compilation_skipped_below_threshold(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock

        wiki_root = tmp_path / "wiki"
        store = RepoWikiStore(wiki_root)
        store.ingest(
            "org/repo",
            [
                WikiEntry(
                    title="Single module insight",
                    content="Architecture note about the service layer.",
                    source_type="plan",
                ),
            ],
        )

        config = _make_config(wiki_root)

        compiler = MagicMock()
        compiler.compile_topic = AsyncMock()

        loop = RepoWikiLoop(
            config=config,
            wiki_store=store,
            deps=_make_deps(),
            wiki_compiler=compiler,
        )
        result = await loop._do_work()
        assert result is not None
        assert result["entries_compiled"] == 0
        compiler.compile_topic.assert_not_called()


@pytest.mark.asyncio
async def test_generalization_promotes_pair_to_tribal(tmp_path):
    """Two per-repo entries on same topic → tribal entry + per-repo cross-refs."""
    from unittest.mock import AsyncMock, MagicMock

    from repo_wiki import RepoWikiStore, WikiEntry
    from repo_wiki_loop import run_generalization_pass
    from tribal_wiki import TribalWikiStore
    from wiki_compiler import GeneralizationCheck

    per_repo = RepoWikiStore(tmp_path / "per_repo")
    tribal = TribalWikiStore(tmp_path / "tribal")

    # Two entries, same topic, different repos. Content contains
    # words that classify_topic routes to "testing".
    per_repo.ingest(
        "acme/a",
        [
            WikiEntry(
                id="01HQA00000000000000000000A",
                title="Use pytest-asyncio",
                content="Testing: configure pytest-asyncio with mode=auto.",
                source_type="plan",
                topic="testing",
                source_repo="acme/a",
            )
        ],
    )
    per_repo.ingest(
        "other/b",
        [
            WikiEntry(
                id="01HQB00000000000000000000B",
                title="Async test mode",
                content="Testing: pytest-asyncio mode=auto works.",
                source_type="plan",
                topic="testing",
                source_repo="other/b",
            )
        ],
    )

    compiler = MagicMock()
    compiler.generalize_pair = AsyncMock(
        return_value=GeneralizationCheck(
            same_principle=True,
            generalized_title="Pytest async mode",
            generalized_body="Configure pytest-asyncio with mode=auto.",
            confidence="high",
        )
    )

    result = await run_generalization_pass(
        per_repo=per_repo,
        tribal=tribal,
        compiler=compiler,
    )
    assert result.promoted == 1

    # Tribal has the generalized entry.
    out = tribal.query()
    assert "Pytest async mode" in out

    # Per-repo entries are marked with supersedes pointing at the tribal id.
    for repo in ("acme/a", "other/b"):
        entries = per_repo.load_topic_entries(per_repo.repo_dir(repo) / "testing.md")
        assert all(e.superseded_by for e in entries), (
            f"per-repo entries in {repo} should be marked superseded"
        )


@pytest.mark.asyncio
async def test_generalization_emits_tribal_promotion_event(tmp_path):
    """When event_bus is provided, every promotion publishes TRIBAL_PROMOTION."""
    from unittest.mock import AsyncMock, MagicMock

    from events import EventBus, EventType, HydraFlowEvent
    from repo_wiki import RepoWikiStore, WikiEntry
    from repo_wiki_loop import run_generalization_pass
    from tribal_wiki import TribalWikiStore
    from wiki_compiler import GeneralizationCheck

    per_repo = RepoWikiStore(tmp_path / "per_repo")
    tribal = TribalWikiStore(tmp_path / "tribal")

    per_repo.ingest(
        "acme/a",
        [
            WikiEntry(
                id="01HQA00000000000000000000A",
                title="Use pytest-asyncio",
                content="Testing: configure pytest-asyncio with mode=auto.",
                source_type="plan",
                topic="testing",
                source_repo="acme/a",
            )
        ],
    )
    per_repo.ingest(
        "other/b",
        [
            WikiEntry(
                id="01HQB00000000000000000000B",
                title="Async test mode",
                content="Testing: pytest-asyncio mode=auto works.",
                source_type="plan",
                topic="testing",
                source_repo="other/b",
            )
        ],
    )

    compiler = MagicMock()
    compiler.generalize_pair = AsyncMock(
        return_value=GeneralizationCheck(
            same_principle=True,
            generalized_title="Pytest async mode",
            generalized_body="Configure pytest-asyncio with mode=auto.",
            confidence="high",
        )
    )

    event_bus = EventBus()
    published: list[HydraFlowEvent] = []

    async def capture(event):
        published.append(event)

    event_bus.publish = capture  # type: ignore[method-assign]

    result = await run_generalization_pass(
        per_repo=per_repo,
        tribal=tribal,
        compiler=compiler,
        event_bus=event_bus,
    )
    assert result.promoted == 1
    assert len(published) == 1
    event = published[0]
    assert event.type == EventType.TRIBAL_PROMOTION
    assert event.data["topic"] == "testing"
    assert {event.data["repo_a"], event.data["repo_b"]} == {"acme/a", "other/b"}
