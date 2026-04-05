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
    config = MagicMock()
    config.repo_wiki_interval = 3600
    config.dry_run = False
    store = RepoWikiStore(wiki_root)
    return RepoWikiLoop(config=config, wiki_store=store, deps=_make_deps())


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

        config = MagicMock()
        config.repo_wiki_interval = 3600
        config.dry_run = False
        loop = RepoWikiLoop(config=config, wiki_store=store, deps=_make_deps())

        result = await loop._do_work()
        assert result is not None
        assert result["repos"] == 1
        assert result["total_entries"] >= 1
