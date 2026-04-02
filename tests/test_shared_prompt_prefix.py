"""Tests for SharedPromptPrefix."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared_prompt_prefix import SharedPromptPrefix
from tests.helpers import ConfigFactory


@pytest.fixture()
def config(tmp_path):
    return ConfigFactory.create(repo_root=tmp_path)


def test_build_caches_prefix(config):
    """Second call returns same string without rebuilding."""
    import asyncio

    prefix = SharedPromptPrefix(config)
    result1 = asyncio.get_event_loop().run_until_complete(prefix.build())
    result2 = asyncio.get_event_loop().run_until_complete(prefix.build())
    assert result1 is result2  # same object, not just equal


@pytest.mark.asyncio()
async def test_build_includes_claude_md(config):
    (config.repo_root / "CLAUDE.md").write_text("# Project Rules\nAlways test first.")
    prefix = SharedPromptPrefix(config)
    result = await prefix.build()
    assert "Project Rules" in result
    assert "Always test first" in result


@pytest.mark.asyncio()
async def test_build_without_claude_md(config):
    prefix = SharedPromptPrefix(config)
    result = await prefix.build()
    assert "Project Conventions" not in result


@pytest.mark.asyncio()
async def test_with_task_appends_instructions(config):
    prefix = SharedPromptPrefix(config)
    await prefix.build()
    result = prefix.with_task("Implement the foo function")
    assert "## Your Task" in result
    assert "Implement the foo function" in result


def test_with_task_raises_before_build(config):
    prefix = SharedPromptPrefix(config)
    with pytest.raises(RuntimeError, match="Call build"):
        prefix.with_task("anything")


@pytest.mark.asyncio()
async def test_prefix_chars_zero_before_build(config):
    prefix = SharedPromptPrefix(config)
    assert prefix.prefix_chars == 0


@pytest.mark.asyncio()
async def test_prefix_chars_after_build(config):
    (config.repo_root / "CLAUDE.md").write_text("Some content")
    prefix = SharedPromptPrefix(config)
    await prefix.build()
    assert prefix.prefix_chars > 0


@pytest.mark.asyncio()
async def test_deterministic_prefix(config):
    """Two builders with same input produce same prefix."""
    (config.repo_root / "CLAUDE.md").write_text("# Rules")
    p1 = SharedPromptPrefix(config)
    p2 = SharedPromptPrefix(config)
    with patch.object(SharedPromptPrefix, "_get_repo_state", return_value=""):
        r1 = await p1.build()
        r2 = await p2.build()
    assert r1 == r2


@pytest.mark.asyncio()
async def test_claude_md_truncated_to_max_chars(config):
    """CLAUDE.md content is truncated to max_memory_prompt_chars."""
    config.max_memory_prompt_chars = 20
    (config.repo_root / "CLAUDE.md").write_text("A" * 100)
    prefix = SharedPromptPrefix(config)
    with patch.object(SharedPromptPrefix, "_get_repo_state", return_value=""):
        result = await prefix.build()
    # The prefix wraps CLAUDE.md in a heading; the raw content should be truncated.
    assert "A" * 21 not in result


@pytest.mark.asyncio()
async def test_repo_state_included(config):
    """Repo state section appears in the prefix when git info is available."""
    prefix = SharedPromptPrefix(config)
    with patch.object(
        SharedPromptPrefix,
        "_get_repo_state",
        return_value="Branch: main\n\nRecent commits:\nabc123 initial",
    ):
        result = await prefix.build()
    assert "Repository State" in result
    assert "Branch: main" in result


@pytest.mark.asyncio()
async def test_memory_recall_included(config):
    """Memory recall from hindsight is included when available."""
    mock_hindsight = MagicMock()

    prefix = SharedPromptPrefix(config)
    with patch.object(
        SharedPromptPrefix,
        "_recall_shared_memory",
        new_callable=AsyncMock,
        return_value="## Accumulated Learnings\n\nAlways run tests",
    ):
        result = await prefix.build(
            hindsight=mock_hindsight, query_context="test context"
        )
    assert "Accumulated Learnings" in result


@pytest.mark.asyncio()
async def test_memory_recall_skipped_without_hindsight(config):
    """Memory recall is skipped when hindsight client is None."""
    prefix = SharedPromptPrefix(config)
    with patch.object(SharedPromptPrefix, "_get_repo_state", return_value=""):
        result = await prefix.build(query_context="test context")
    # No memory section should be present
    assert "Accumulated Learnings" not in result


@pytest.mark.asyncio()
async def test_with_task_separator(config):
    """Task section is separated from prefix by a horizontal rule."""
    prefix = SharedPromptPrefix(config)
    await prefix.build()
    result = prefix.with_task("Do something")
    assert "---" in result
