"""Tests for TriageRunner memory injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from config import HydraFlowConfig
from events import EventBus
from models import Task
from triage import TriageRunner


def _make_memory(text: str, score: float = 0.8):
    from hindsight import HindsightMemory

    return HindsightMemory(content=text, text=text, relevance_score=score)


@pytest.fixture
def _config():
    return HydraFlowConfig(repo_root="/tmp/test")


@pytest.fixture
def _bus():
    return EventBus()


class TestTriageRunnerHindsightWiring:
    """TriageRunner accepts and stores hindsight via BaseRunner."""

    def test_accepts_hindsight(self, _config, _bus):
        hindsight = AsyncMock()
        runner = TriageRunner(_config, _bus, hindsight=hindsight)
        assert runner._hindsight is hindsight

    def test_without_hindsight(self, _config, _bus):
        runner = TriageRunner(_config, _bus)
        assert runner._hindsight is None


class TestEvaluateWithLlmMemoryInjection:
    """_evaluate_with_llm injects memory into the prompt."""

    @pytest.mark.asyncio
    async def test_memory_injected_into_prompt(self, _config, _bus):
        """When hindsight returns memories, they appear in the prompt."""
        from hindsight import Bank

        hindsight = AsyncMock()
        runner = TriageRunner(_config, _bus, hindsight=hindsight)

        issue = Task(id=42, title="Add caching layer", body="Speed up API responses")

        memories = {
            Bank.TRIBAL: [_make_memory("caching requires invalidation strategy")],
            Bank.TROUBLESHOOTING: [],
            Bank.RETROSPECTIVES: [],
            Bank.REVIEW_INSIGHTS: [],
            Bank.HARNESS_INSIGHTS: [],
        }

        async def mock_recall(client, bank, query, *, limit=10):
            return memories.get(bank, [])

        captured_prompt = None

        async def mock_execute(cmd, prompt, cwd, meta, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return '{"ready": true, "reasons": [], "issue_type": "feature", "enrichment": ""}'

        with (
            patch("hindsight.recall_safe", side_effect=mock_recall),
            patch.object(runner, "_execute", side_effect=mock_execute),
        ):
            result = await runner._evaluate_with_llm(issue)

        assert captured_prompt is not None
        assert "caching requires invalidation strategy" in captured_prompt
        assert result.ready is True

    @pytest.mark.asyncio
    async def test_no_memory_without_hindsight(self, _config, _bus):
        """Without hindsight, prompt has no memory section."""
        runner = TriageRunner(_config, _bus)

        issue = Task(id=99, title="Fix login bug", body="Users cannot log in")

        captured_prompt = None

        async def mock_execute(cmd, prompt, cwd, meta, **kwargs):
            nonlocal captured_prompt
            captured_prompt = prompt
            return (
                '{"ready": true, "reasons": [], "issue_type": "bug", "enrichment": ""}'
            )

        with patch.object(runner, "_execute", side_effect=mock_execute):
            result = await runner._evaluate_with_llm(issue)

        assert captured_prompt is not None
        # No memory section headers should appear without Hindsight
        assert "## Accumulated Learnings" not in captured_prompt
        assert "## Known Troubleshooting Patterns" not in captured_prompt
        assert result.ready is True
