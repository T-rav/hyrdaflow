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


class TestReviewSkillInjection:
    """Verify plugin skills are injected into the review prompt."""

    @pytest.mark.asyncio
    async def test_plugin_skills_appear_in_review_prompt(
        self, config, event_bus
    ) -> None:
        """The formatted skills section and qualified names appear in the review prompt."""
        from models import PRInfo
        from plugin_skill_registry import PluginSkill
        from reviewer import ReviewRunner
        from tests.conftest import TaskFactory

        fake_skills = [
            PluginSkill("code-review", "code-review", "Review a PR"),
            PluginSkill(
                "superpowers",
                "receiving-code-review",
                "Use when receiving review feedback",
            ),
        ]

        issue = TaskFactory.create(id=1, title="t", body="b")
        pr = PRInfo(number=1, issue_number=1, branch="feat/test")
        reviewer = ReviewRunner(config, event_bus)

        with patch("reviewer.discover_plugin_skills", return_value=fake_skills):
            prompt, _ = await reviewer._build_review_prompt_with_stats(
                pr, issue, diff="diff --git a/x b/x\n+foo\n"
            )

        assert "code-review:code-review" in prompt
        assert "superpowers:receiving-code-review" in prompt
        assert "## Available Skills" in prompt

    @pytest.mark.asyncio
    async def test_no_skills_section_when_review_empty(self, config, event_bus) -> None:
        """Empty skill list in review phase produces no header."""
        from models import PRInfo
        from reviewer import ReviewRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="t", body="b")
        pr = PRInfo(number=1, issue_number=1, branch="feat/test")
        reviewer = ReviewRunner(config, event_bus)

        with patch("reviewer.discover_plugin_skills", return_value=[]):
            prompt, _ = await reviewer._build_review_prompt_with_stats(
                pr, issue, diff=""
            )

        assert "## Available Skills" not in prompt


class TestTriageSkillInjection:
    """Verify plugin skills are injected into the triage prompt."""

    def test_plugin_skills_appear_in_triage_prompt(self, config, event_bus) -> None:
        """The formatted skills section appears in the triage prompt."""
        from plugin_skill_registry import PluginSkill
        from tests.conftest import TaskFactory
        from triage import TriageRunner

        fake_skills = [
            PluginSkill(
                "superpowers", "brainstorming", "Use when starting creative work"
            )
        ]

        issue = TaskFactory.create(id=1, title="Vague idea", body="do stuff")
        triager = TriageRunner(config, event_bus)

        with patch("triage.discover_plugin_skills", return_value=fake_skills):
            prompt, _ = triager._build_prompt_with_stats(issue)

        assert "superpowers:brainstorming" in prompt
        assert "## Available Skills" in prompt


class TestPlannerSkillInjection:
    """Verify plugin skills are injected into the planner prompt."""

    @pytest.mark.asyncio
    async def test_plugin_skills_appear_in_planner_prompt(
        self, config, event_bus
    ) -> None:
        """The formatted skills section appears in the planner prompt."""
        from planner import PlannerRunner
        from plugin_skill_registry import PluginSkill
        from tests.conftest import TaskFactory

        fake_skills = [
            PluginSkill("superpowers", "writing-plans", "Use when writing a plan")
        ]

        issue = TaskFactory.create(id=1, title="t", body="b")
        planner = PlannerRunner(config, event_bus)

        with patch("planner.discover_plugin_skills", return_value=fake_skills):
            prompt, _ = await planner._build_prompt_with_stats(issue)

        assert "superpowers:writing-plans" in prompt
        assert "## Available Skills" in prompt
