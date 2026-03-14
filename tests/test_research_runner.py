"""Tests for research_runner.py — pre-plan codebase research."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from models import ResearchResult
from research_runner import ResearchRunner
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runner(config, event_bus):
    return ResearchRunner(config=config, event_bus=event_bus)


# ---------------------------------------------------------------------------
# ResearchRunner.research
# ---------------------------------------------------------------------------


class TestResearchRunner:
    @pytest.mark.asyncio
    async def test_dry_run_returns_success(self, event_bus):
        config = ConfigFactory.create(dry_run=True)
        runner = _make_runner(config, event_bus)
        task = TaskFactory.create(title="Add feature")
        result = await runner.research(task)
        assert result.success is True
        assert isinstance(result, ResearchResult)

    @pytest.mark.asyncio
    async def test_extracts_research_from_transcript(self, config, event_bus):
        transcript = (
            "Exploring the codebase...\n\n"
            "RESEARCH_START\n"
            "### Relevant Files\n"
            "| src/models.py | Data models | `Task` |\n\n"
            "### Patterns & Conventions\n"
            "- Uses Pydantic models\n"
            "RESEARCH_END\n"
        )
        runner = _make_runner(config, event_bus)
        with patch.object(
            runner, "_execute", new_callable=AsyncMock, return_value=transcript
        ):
            task = TaskFactory.create(id=1, title="Add feature")
            result = await runner.research(task)

        assert result.success is True
        assert "Relevant Files" in result.research
        assert "Pydantic" in result.research

    @pytest.mark.asyncio
    async def test_fails_when_no_markers(self, config, event_bus):
        transcript = "I explored the codebase but forgot the markers."
        runner = _make_runner(config, event_bus)
        with patch.object(
            runner, "_execute", new_callable=AsyncMock, return_value=transcript
        ):
            task = TaskFactory.create(id=1, title="Add feature")
            result = await runner.research(task)

        assert result.success is False
        assert "markers" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_handles_exception(self, config, event_bus):
        runner = _make_runner(config, event_bus)
        with patch.object(
            runner, "_execute", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            task = TaskFactory.create(id=1, title="Add feature")
            result = await runner.research(task)

        assert result.success is False
        assert "boom" in (result.error or "")


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestResearchPrompt:
    def test_prompt_contains_issue_info(self, config, event_bus):
        runner = _make_runner(config, event_bus)
        task = TaskFactory.create(
            title="Add widget support", body="Need to add widgets"
        )
        prompt = runner._build_prompt(task)
        assert "#42" in prompt
        assert "Add widget support" in prompt
        assert "RESEARCH_START" in prompt
        assert "RESEARCH_END" in prompt

    def test_prompt_is_read_only(self, config, event_bus):
        runner = _make_runner(config, event_bus)
        task = TaskFactory.create(id=1, title="Feature")
        prompt = runner._build_prompt(task)
        assert "READ-ONLY" in prompt


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


class TestExtractResearch:
    def test_extracts_between_markers(self):
        transcript = "noise\nRESEARCH_START\nfound stuff\nRESEARCH_END\nnoise"
        assert ResearchRunner._extract_research(transcript) == "found stuff"

    def test_returns_empty_when_no_markers(self):
        assert ResearchRunner._extract_research("no markers here") == ""

    def test_strips_whitespace(self):
        transcript = "RESEARCH_START\n  content  \nRESEARCH_END"
        assert ResearchRunner._extract_research(transcript) == "content"
