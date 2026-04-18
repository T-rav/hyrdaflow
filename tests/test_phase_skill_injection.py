"""Integration tests — plugin skills appear in each factory phase prompt.

Mirrors ``tests/test_beads_manager.py::TestAgentBeadPromptIntegration`` — the
existing pattern for asserting that a runtime-built registry lands in the
final prompt string sent to Claude.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestImplementSkillInjection:
    """Verify plugin skills are injected into the implement prompt."""

    @pytest.mark.asyncio
    async def test_plugin_skills_appear_in_implement_prompt(
        self, config, event_bus
    ) -> None:
        """The formatted skills section and qualified names appear in the prompt."""
        from agent import AgentRunner
        from plugin_skill_registry import PluginSkill
        from tests.conftest import TaskFactory

        fake_skills = [
            PluginSkill(
                "superpowers",
                "test-driven-development",
                "Use when implementing a feature",
            ),
            PluginSkill("code-review", "code-review", "Review a PR"),
        ]

        issue = TaskFactory.create(id=1, title="t", body="b")
        runner = AgentRunner(config, event_bus)

        with patch("agent.discover_plugin_skills", return_value=fake_skills):
            prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "superpowers:test-driven-development" in prompt
        assert "code-review:code-review" in prompt
        assert "## Available Skills" in prompt

    @pytest.mark.asyncio
    async def test_no_skills_section_when_registry_empty(
        self, config, event_bus
    ) -> None:
        """Empty skill list produces no '## Available Skills' section."""
        from agent import AgentRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="t", body="b")
        runner = AgentRunner(config, event_bus)

        with patch("agent.discover_plugin_skills", return_value=[]):
            prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "## Available Skills" not in prompt
