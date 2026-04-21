"""Integration tests — plugin skills appear in each factory phase prompt.

Mirrors ``tests/test_beads_manager.py::TestAgentBeadPromptIntegration`` — the
existing pattern for asserting that a runtime-built registry lands in the
final prompt string sent to Claude.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_skill_cache():
    """Clear the discovery cache before every test to prevent cross-test leakage."""
    from plugin_skill_registry import clear_plugin_skill_cache

    clear_plugin_skill_cache()
    yield
    clear_plugin_skill_cache()


# ---------------------------------------------------------------------------
# Shared helper: a cross-phase skill list covering all whitelists.
# Used by whitelist-filtering tests to ensure cross-phase leak detection.
# ---------------------------------------------------------------------------


def _all_phase_skills():
    """Return a PluginSkill list covering every whitelisted skill across phases."""
    from plugin_skill_registry import PluginSkill

    return [
        PluginSkill("superpowers", "test-driven-development", "TDD discipline"),
        PluginSkill("superpowers", "systematic-debugging", "Debug systematically"),
        PluginSkill(
            "superpowers", "verification-before-completion", "Verify before done"
        ),
        PluginSkill("superpowers", "writing-plans", "Write structured plans"),
        PluginSkill("code-review", "code-review", "Review a PR"),
        PluginSkill("code-simplifier", "simplify", "Simplify code"),
        PluginSkill("frontend-design", "frontend-design", "Design frontend"),
    ]


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

        # Use skills that are in the agent whitelist
        fake_skills = [
            PluginSkill(
                "superpowers",
                "test-driven-development",
                "Use when implementing a feature",
            ),
            PluginSkill(
                "superpowers",
                "systematic-debugging",
                "Debug systematically",
            ),
        ]

        issue = TaskFactory.create(id=1, title="t", body="b")
        runner = AgentRunner(config, event_bus)

        with patch("agent.discover_plugin_skills", return_value=fake_skills):
            prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "superpowers:test-driven-development" in prompt
        assert "superpowers:systematic-debugging" in prompt
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

    @pytest.mark.asyncio
    async def test_agent_prompt_includes_only_agent_whitelisted_skills(
        self, config, event_bus
    ) -> None:
        """Agent prompt shows its whitelist and excludes reviewer-only skills."""
        from agent import AgentRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="t", body="b")
        runner = AgentRunner(config, event_bus)

        with patch("agent.discover_plugin_skills", return_value=_all_phase_skills()):
            prompt, _ = await runner._build_prompt_with_stats(issue)

        assert "## Available Skills" in prompt
        # 1% confidence preamble
        assert "1% confidence" in prompt
        # agent whitelist skills present
        assert "superpowers:test-driven-development" in prompt
        assert "superpowers:systematic-debugging" in prompt
        assert "superpowers:verification-before-completion" in prompt
        assert "code-simplifier:simplify" in prompt
        assert "frontend-design:frontend-design" in prompt
        # reviewer-only skill must NOT appear
        assert "code-review:code-review" not in prompt


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

        # Use skills that are in the reviewer whitelist
        fake_skills = [
            PluginSkill("code-review", "code-review", "Review a PR"),
            PluginSkill(
                "superpowers",
                "systematic-debugging",
                "Debug systematically",
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
        assert "superpowers:systematic-debugging" in prompt
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

    @pytest.mark.asyncio
    async def test_reviewer_prompt_includes_only_reviewer_whitelisted_skills(
        self, config, event_bus
    ) -> None:
        """Reviewer prompt shows its whitelist and excludes agent-only skills."""
        from models import PRInfo
        from reviewer import ReviewRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="t", body="b")
        pr = PRInfo(number=1, issue_number=1, branch="feat/test")
        reviewer = ReviewRunner(config, event_bus)

        with patch("reviewer.discover_plugin_skills", return_value=_all_phase_skills()):
            prompt, _ = await reviewer._build_review_prompt_with_stats(
                pr, issue, diff="diff --git a/x b/x\n+foo\n"
            )

        assert "## Available Skills" in prompt
        # 1% confidence preamble
        assert "1% confidence" in prompt
        # reviewer whitelist skills present
        assert "code-review:code-review" in prompt
        assert "superpowers:systematic-debugging" in prompt
        # agent-only skill must NOT appear
        assert "superpowers:test-driven-development" not in prompt


class TestTriageSkillInjection:
    """Verify plugin skills are injected into the triage prompt."""

    def test_plugin_skills_appear_in_triage_prompt(self, config, event_bus) -> None:
        """The formatted skills section appears in the triage prompt."""
        from plugin_skill_registry import PluginSkill
        from tests.conftest import TaskFactory
        from triage import TriageRunner

        # Use a skill that is in the triage whitelist
        fake_skills = [
            PluginSkill("superpowers", "systematic-debugging", "Debug systematically")
        ]

        issue = TaskFactory.create(id=1, title="Vague idea", body="do stuff")
        triager = TriageRunner(config, event_bus)

        with patch("triage.discover_plugin_skills", return_value=fake_skills):
            prompt, _ = triager._build_prompt_with_stats(issue)

        assert "superpowers:systematic-debugging" in prompt
        assert "## Available Skills" in prompt

    def test_triage_prompt_includes_only_triage_whitelisted_skills(
        self, config, event_bus
    ) -> None:
        """Triage prompt shows its whitelist and excludes agent-only skills."""
        from tests.conftest import TaskFactory
        from triage import TriageRunner

        issue = TaskFactory.create(id=1, title="Vague idea", body="do stuff")
        triager = TriageRunner(config, event_bus)

        with patch("triage.discover_plugin_skills", return_value=_all_phase_skills()):
            prompt, _ = triager._build_prompt_with_stats(issue)

        assert "## Available Skills" in prompt
        # 1% confidence preamble
        assert "1% confidence" in prompt
        # triage whitelist skill present
        assert "superpowers:systematic-debugging" in prompt
        # agent-only skill must NOT appear
        assert "superpowers:test-driven-development" not in prompt


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

    @pytest.mark.asyncio
    async def test_planner_prompt_includes_only_planner_whitelisted_skills(
        self, config, event_bus
    ) -> None:
        """Planner prompt shows its whitelist and excludes reviewer-only skills."""
        from planner import PlannerRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="t", body="b")
        planner = PlannerRunner(config, event_bus)

        with patch("planner.discover_plugin_skills", return_value=_all_phase_skills()):
            prompt, _ = await planner._build_prompt_with_stats(issue)

        assert "## Available Skills" in prompt
        # 1% confidence preamble
        assert "1% confidence" in prompt
        # planner whitelist skills present
        assert "superpowers:writing-plans" in prompt
        assert "superpowers:systematic-debugging" in prompt
        # reviewer-only skill must NOT appear
        assert "code-review:code-review" not in prompt


class TestDiscoverSkillInjection:
    """Verify plugin skills are injected into the discover prompt."""

    def test_plugin_skills_appear_in_discover_prompt(self, config, event_bus) -> None:
        """The formatted skills section appears in the discover prompt."""
        from discover_runner import DiscoverRunner
        from plugin_skill_registry import PluginSkill
        from tests.conftest import TaskFactory

        # Use a skill that is in the discover whitelist
        fake_skills = [
            PluginSkill("superpowers", "systematic-debugging", "Debug systematically")
        ]

        issue = TaskFactory.create(id=1, title="build something", body="vague")
        runner = DiscoverRunner(config, event_bus)

        with patch("discover_runner.discover_plugin_skills", return_value=fake_skills):
            prompt = runner._build_prompt(issue)

        assert "superpowers:systematic-debugging" in prompt
        assert "## Available Skills" in prompt

    def test_discover_prompt_includes_only_discover_whitelisted_skills(
        self, config, event_bus
    ) -> None:
        """Discover prompt shows its whitelist and excludes agent-only skills."""
        from discover_runner import DiscoverRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="build something", body="vague")
        runner = DiscoverRunner(config, event_bus)

        with patch(
            "discover_runner.discover_plugin_skills", return_value=_all_phase_skills()
        ):
            prompt = runner._build_prompt(issue)

        assert "## Available Skills" in prompt
        # 1% confidence preamble
        assert "1% confidence" in prompt
        # discover whitelist skill present
        assert "superpowers:systematic-debugging" in prompt
        # agent-only skill must NOT appear
        assert "superpowers:test-driven-development" not in prompt


class TestShapeSkillInjection:
    """Verify plugin skills are injected into the shape turn prompt."""

    def test_plugin_skills_appear_in_shape_prompt(self, config, event_bus) -> None:
        """The formatted skills section appears in the shape turn prompt."""
        from models import ShapeConversation
        from plugin_skill_registry import PluginSkill
        from shape_runner import ShapeRunner
        from tests.conftest import TaskFactory

        # Use a skill that is in the shape whitelist
        fake_skills = [
            PluginSkill("superpowers", "writing-plans", "Use when writing a plan")
        ]

        issue = TaskFactory.create(id=1, title="shape this", body="rough idea")
        conversation = ShapeConversation(issue_number=1)
        runner = ShapeRunner(config, event_bus)

        with patch("shape_runner.discover_plugin_skills", return_value=fake_skills):
            prompt = runner._build_turn_prompt(issue, conversation)

        assert "superpowers:writing-plans" in prompt
        assert "## Available Skills" in prompt

    def test_shape_prompt_includes_only_shape_whitelisted_skills(
        self, config, event_bus
    ) -> None:
        """Shape prompt shows its whitelist and excludes reviewer-only skills."""
        from models import ShapeConversation
        from shape_runner import ShapeRunner
        from tests.conftest import TaskFactory

        issue = TaskFactory.create(id=1, title="shape this", body="rough idea")
        conversation = ShapeConversation(issue_number=1)
        runner = ShapeRunner(config, event_bus)

        with patch(
            "shape_runner.discover_plugin_skills", return_value=_all_phase_skills()
        ):
            prompt = runner._build_turn_prompt(issue, conversation)

        assert "## Available Skills" in prompt
        # 1% confidence preamble
        assert "1% confidence" in prompt
        # shape whitelist skill present
        assert "superpowers:writing-plans" in prompt
        # reviewer-only skill must NOT appear
        assert "code-review:code-review" not in prompt
