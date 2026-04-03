"""Tests for skill_registry — declarative agent post-implementation skills."""

from __future__ import annotations

from skill_registry import (
    BUILTIN_SKILLS,
    AgentSkill,
    format_skills_for_prompt,
    get_skills,
)


class TestAgentSkill:
    def test_builtin_skills_count(self):
        assert len(BUILTIN_SKILLS) == 2

    def test_diff_sanity_skill(self):
        skill = BUILTIN_SKILLS[0]
        assert skill.name == "diff-sanity"
        assert skill.blocking is True
        assert skill.config_key == "max_diff_sanity_attempts"
        assert callable(skill.prompt_builder)
        assert callable(skill.result_parser)

    def test_test_adequacy_skill(self):
        skill = BUILTIN_SKILLS[1]
        assert skill.name == "test-adequacy"
        assert skill.blocking is False
        assert skill.config_key == "max_test_adequacy_attempts"

    def test_skill_is_frozen(self):
        skill = BUILTIN_SKILLS[0]
        import pytest

        with pytest.raises(AttributeError):
            skill.name = "mutated"  # type: ignore[misc]


class TestGetSkills:
    def test_returns_copy(self):
        skills = get_skills()
        assert skills == BUILTIN_SKILLS
        assert skills is not BUILTIN_SKILLS  # copy, not reference

    def test_modifying_copy_doesnt_affect_builtin(self):
        skills = get_skills()
        skills.clear()
        assert len(BUILTIN_SKILLS) == 2


class TestFormatSkillsForPrompt:
    def test_includes_all_skills(self):
        result = format_skills_for_prompt(get_skills())
        assert "diff-sanity" in result
        assert "test-adequacy" in result
        assert "[blocking]" in result
        assert "[non-blocking]" in result

    def test_includes_purpose(self):
        result = format_skills_for_prompt(get_skills())
        assert "accidental deletions" in result
        assert "test coverage" in result

    def test_empty_list_returns_empty(self):
        assert format_skills_for_prompt([]) == ""

    def test_has_header(self):
        result = format_skills_for_prompt(get_skills())
        assert "## Post-Implementation Skills" in result

    def test_custom_skill(self):
        custom = AgentSkill(
            name="custom-check",
            purpose="Check custom things",
            config_key="max_custom_attempts",
            blocking=True,
            prompt_builder=lambda **kw: "prompt",
            result_parser=lambda t: (True, "ok", []),
        )
        result = format_skills_for_prompt([custom])
        assert "custom-check" in result
        assert "Check custom things" in result


class TestSkillPromptBuilders:
    """Verify that built-in skill prompt builders produce valid prompts."""

    def test_diff_sanity_builder(self):
        skill = BUILTIN_SKILLS[0]
        prompt = skill.prompt_builder(
            issue_number=42, issue_title="Fix auth", diff="+ new line"
        )
        assert "issue #42" in prompt.lower() or "#42" in prompt
        assert "diff" in prompt.lower()

    def test_test_adequacy_builder(self):
        skill = BUILTIN_SKILLS[1]
        prompt = skill.prompt_builder(
            issue_number=99, issue_title="Add tests", diff="+ test code"
        )
        assert "#99" in prompt
        assert "diff" in prompt.lower()


class TestSkillResultParsers:
    """Verify that built-in skill result parsers handle OK and RETRY."""

    def test_diff_sanity_parser_ok(self):
        skill = BUILTIN_SKILLS[0]
        passed, summary, findings = skill.result_parser(
            "DIFF_SANITY_RESULT: OK\nSUMMARY: No issues found"
        )
        assert passed is True
        assert findings == []

    def test_diff_sanity_parser_retry(self):
        skill = BUILTIN_SKILLS[0]
        passed, summary, findings = skill.result_parser(
            "DIFF_SANITY_RESULT: RETRY\nSUMMARY: debug code\nFINDINGS:\n- src/foo.py:10 — print statement"
        )
        assert passed is False
        assert len(findings) == 1

    def test_test_adequacy_parser_ok(self):
        skill = BUILTIN_SKILLS[1]
        passed, summary, gaps = skill.result_parser(
            "TEST_ADEQUACY_RESULT: OK\nSUMMARY: All covered"
        )
        assert passed is True

    def test_test_adequacy_parser_retry(self):
        skill = BUILTIN_SKILLS[1]
        passed, summary, gaps = skill.result_parser(
            "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing tests\nGAPS:\n- src/bar.py:func — needs test"
        )
        assert passed is False
        assert len(gaps) == 1


# ---------------------------------------------------------------------------
# Agent Tools — dynamic discovery from .claude/commands/hf.*.md
# ---------------------------------------------------------------------------


class TestDiscoverTools:
    """discover_tools scans .claude/commands/ for hf.*.md files."""

    def test_discovers_hf_commands(self, tmp_path):
        from skill_registry import discover_tools

        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "hf.quality-gate.md").write_text(
            "# Quality Gate\n\nRun checks.\n"
        )
        (commands_dir / "hf.diff-sanity.md").write_text(
            "# Diff Sanity Check\n\nReview diff.\n"
        )
        (commands_dir / "other-command.md").write_text("# Not an hf command\n")

        tools = discover_tools(tmp_path)
        assert len(tools) == 2
        commands = {t.command for t in tools}
        assert "/hf.diff-sanity" in commands
        assert "/hf.quality-gate" in commands

    def test_extracts_purpose_from_heading(self, tmp_path):
        from skill_registry import discover_tools

        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "hf.test-adequacy.md").write_text(
            "# Test Adequacy Check\n\nDetails.\n"
        )

        tools = discover_tools(tmp_path)
        assert len(tools) == 1
        assert tools[0].purpose == "Test Adequacy Check"

    def test_empty_dir_returns_empty(self, tmp_path):
        from skill_registry import discover_tools

        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        assert discover_tools(tmp_path) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        from skill_registry import discover_tools

        assert discover_tools(tmp_path) == []

    def test_skips_files_without_heading(self, tmp_path):
        from skill_registry import discover_tools

        commands_dir = tmp_path / ".claude" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "hf.empty.md").write_text("")
        (commands_dir / "hf.good.md").write_text("# Good Command\n")

        tools = discover_tools(tmp_path)
        assert len(tools) == 1
        assert tools[0].command == "/hf.good"

    def test_discovers_real_repo_tools(self):
        """Discover tools from the actual repo .claude/commands/ directory."""
        from pathlib import Path

        from skill_registry import discover_tools

        repo_root = Path(__file__).parent.parent
        tools = discover_tools(repo_root)
        commands = {t.command for t in tools}
        # These should exist in the actual repo
        assert "/hf.quality-gate" in commands
        assert "/hf.diff-sanity" in commands
        assert "/hf.test-adequacy" in commands


class TestFormatToolsForPrompt:
    def test_includes_all_tools(self):
        from skill_registry import AgentTool, format_tools_for_prompt

        tools = [
            AgentTool(command="/hf.quality-gate", purpose="Run quality checks"),
            AgentTool(command="/hf.diff-sanity", purpose="Review diff"),
        ]
        result = format_tools_for_prompt(tools)
        assert "/hf.quality-gate" in result
        assert "/hf.diff-sanity" in result
        assert "Run quality checks" in result
        assert "## Available Tools" in result

    def test_empty_returns_empty(self):
        from skill_registry import format_tools_for_prompt

        assert format_tools_for_prompt([]) == ""
