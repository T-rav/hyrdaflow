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
