"""Tests for reflection → wiki bridge in post_merge_handler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from reflections import append_reflection, read_reflections
from repo_wiki import RepoWikiStore


@pytest.fixture
def config(tmp_path: Path):
    cfg = MagicMock()
    cfg.data_root = tmp_path
    return cfg


async def test_bridge_reads_appends_and_clears(config, tmp_path):
    from post_merge_handler import _bridge_reflections_to_wiki
    from wiki_compiler import ContradictionCheck

    store = RepoWikiStore(tmp_path / "wiki")
    compiler = AsyncMock()
    compiler.detect_contradictions = AsyncMock(return_value=ContradictionCheck())

    append_reflection(
        config,
        42,
        phase="plan",
        content="architecture: use DI for service modules",
    )

    # Before the bridge runs, reflections file exists and is non-empty.
    assert read_reflections(config, 42)

    await _bridge_reflections_to_wiki(
        config=config,
        issue_number=42,
        repo="acme/widget",
        store=store,
        compiler=compiler,
    )

    # Reflection content is now in the wiki.
    out = store.query("acme/widget")
    assert "DI" in out or "service modules" in out

    # Reflections file was cleared.
    assert read_reflections(config, 42) == ""


async def test_bridge_no_ops_when_reflections_empty(config, tmp_path):
    from post_merge_handler import _bridge_reflections_to_wiki

    store = RepoWikiStore(tmp_path / "wiki")
    compiler = AsyncMock()

    await _bridge_reflections_to_wiki(
        config=config,
        issue_number=99,
        repo="acme/widget",
        store=store,
        compiler=compiler,
    )

    # No wiki activity
    assert store.query("acme/widget") == ""
    compiler.detect_contradictions.assert_not_called()


async def test_bridge_no_ops_when_store_is_none(config, tmp_path):
    from post_merge_handler import _bridge_reflections_to_wiki

    append_reflection(config, 42, phase="plan", content="irrelevant")
    # No exception raised, no clear performed.
    await _bridge_reflections_to_wiki(
        config=config,
        issue_number=42,
        repo="acme/widget",
        store=None,
        compiler=None,
    )
    # The log remains — we did not clear because we did not promote.
    assert "irrelevant" in read_reflections(config, 42)
