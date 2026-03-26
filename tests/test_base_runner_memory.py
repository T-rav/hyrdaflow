"""Tests for memory injection in BaseRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from base_runner import BaseRunner
from config import HydraFlowConfig
from events import EventBus
from hindsight import Bank, HindsightMemory


def _make_memory(text: str, score: float = 0.8) -> HindsightMemory:
    return HindsightMemory(content=text, text=text, relevance_score=score)


@pytest.fixture
def base_runner():
    config = HydraFlowConfig(repo_root="/tmp/test", gh_token="fake")
    bus = EventBus()
    hindsight = AsyncMock()
    runner = BaseRunner(config, bus, hindsight=hindsight)
    return runner


@pytest.mark.asyncio
async def test_review_insights_recalled(base_runner):
    """REVIEW_INSIGHTS bank should be recalled and injected into prompt."""
    memories = {
        Bank.LEARNINGS: [_make_memory("learning-1")],
        Bank.TROUBLESHOOTING: [],
        Bank.RETROSPECTIVES: [],
        Bank.REVIEW_INSIGHTS: [_make_memory("missing tests flagged 5 times")],
        Bank.HARNESS_INSIGHTS: [],
    }

    async def mock_recall(client, bank, query, *, limit=10):
        return memories.get(bank, [])

    with patch("hindsight.recall_safe", side_effect=mock_recall):
        _, memory_section = await base_runner._inject_manifest_and_memory(
            query_context="add user endpoint"
        )

    assert "Common Review Patterns" in memory_section
    assert "missing tests flagged 5 times" in memory_section


@pytest.mark.asyncio
async def test_harness_insights_recalled(base_runner):
    """HARNESS_INSIGHTS bank should be recalled and injected into prompt."""
    memories = {
        Bank.LEARNINGS: [],
        Bank.TROUBLESHOOTING: [],
        Bank.RETROSPECTIVES: [],
        Bank.REVIEW_INSIGHTS: [],
        Bank.HARNESS_INSIGHTS: [_make_memory("CI timeout in pytest-xdist on macOS")],
    }

    async def mock_recall(client, bank, query, *, limit=10):
        return memories.get(bank, [])

    with patch("hindsight.recall_safe", side_effect=mock_recall):
        _, memory_section = await base_runner._inject_manifest_and_memory(
            query_context="fix CI pipeline"
        )

    assert "Known Pipeline Patterns" in memory_section
    assert "CI timeout" in memory_section


@pytest.mark.asyncio
async def test_fallback_to_manifest_when_no_hindsight():
    """When hindsight is None, fall back to CuratedManifestStore."""
    config = HydraFlowConfig(repo_root="/tmp/test", gh_token="fake")
    bus = EventBus()
    runner = BaseRunner(config, bus, hindsight=None)

    with patch(
        "manifest_curator.CuratedManifestStore.render_markdown",
        return_value="## Curated Learnings\n### Project Overview\nHydraFlow automates stuff\n",
    ):
        _, memory_section = await runner._inject_manifest_and_memory(
            query_context="add feature"
        )

    assert "HydraFlow automates" in memory_section
