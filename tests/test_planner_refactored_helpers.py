"""Tests for planner.py extracted helper methods."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from models import PlanResult, Task
from planner import PlannerRunner


@pytest.fixture
def planner_task() -> Task:
    return Task(
        id=10,
        title="Add feature X",
        body="Implement feature X in the system.",
        tags=["ready"],
        comments=[],
        source_url="https://github.com/test/repo/issues/10",
    )


@pytest.fixture
def runner(config, event_bus):
    return PlannerRunner(config=config, event_bus=event_bus)


# ---------------------------------------------------------------------------
# _build_comments_section
# ---------------------------------------------------------------------------


class TestPlannerBuildCommentsSection:
    """Tests for PlannerRunner._build_comments_section."""

    def test_empty_comments(self, runner) -> None:
        section, before, after = runner._build_comments_section([])
        assert section == ""
        assert before == 0
        assert after == 0

    def test_single_comment(self, runner) -> None:
        section, before, after = runner._build_comments_section(["hello world"])
        assert "## Discussion" in section
        assert "hello world" in section
        assert before == len("hello world")

    def test_limits_to_six_comments(self, runner) -> None:
        comments = [f"comment {i}" for i in range(10)]
        section, _before, _after = runner._build_comments_section(comments)
        assert "4 more comments omitted" in section

    def test_truncates_long_comments(self, runner) -> None:
        long_comment = "a" * 2000
        section, before, _after = runner._build_comments_section([long_comment])
        assert before == 2000
        assert "\u2026(truncated)" in section


# ---------------------------------------------------------------------------
# _build_body_with_image_note
# ---------------------------------------------------------------------------


class TestBuildBodyWithImageNote:
    """Tests for PlannerRunner._build_body_with_image_note."""

    def test_simple_body(self, runner, planner_task) -> None:
        body, note, raw_len, body_len = runner._build_body_with_image_note(planner_task)
        assert body == planner_task.body
        assert note == ""
        assert raw_len == body_len

    def test_detects_markdown_image(self, runner, planner_task) -> None:
        planner_task.body = "See ![screenshot](image.png) for details."
        _body, note, _raw, _bl = runner._build_body_with_image_note(planner_task)
        assert "images" in note.lower()

    def test_detects_html_image(self, runner, planner_task) -> None:
        planner_task.body = 'Check <img src="x.png"> this'
        _body, note, _raw, _bl = runner._build_body_with_image_note(planner_task)
        assert note != ""

    def test_empty_body(self, runner, planner_task) -> None:
        planner_task.body = ""
        body, note, raw_len, body_len = runner._build_body_with_image_note(planner_task)
        assert body == ""
        assert note == ""
        assert raw_len == 0

    def test_none_body(self, runner, planner_task) -> None:
        planner_task.body = None
        body, _note, raw_len, _bl = runner._build_body_with_image_note(planner_task)
        assert raw_len == 0


# ---------------------------------------------------------------------------
# _build_schema_sections
# ---------------------------------------------------------------------------


class TestBuildSchemaSections:
    """Tests for PlannerRunner._build_schema_sections."""

    def test_lite_schema(self) -> None:
        mode, schema, graph, mortem = PlannerRunner._build_schema_sections("lite")
        assert "LITE" in mode
        assert "LITE SCHEMA" in schema
        assert graph == ""
        assert mortem == ""

    def test_full_schema(self) -> None:
        mode, schema, graph, mortem = PlannerRunner._build_schema_sections("full")
        assert "FULL" in mode
        assert "REQUIRED SCHEMA" in schema
        assert "Task Graph Format" in graph
        assert "Pre-Mortem" in mortem


# ---------------------------------------------------------------------------
# _make_plan_complete_checker
# ---------------------------------------------------------------------------


class TestMakePlanCompleteChecker:
    """Tests for PlannerRunner._make_plan_complete_checker."""

    def test_detects_plan_end(self, runner) -> None:
        checker = runner._make_plan_complete_checker(10)
        assert checker("some text PLAN_END more") is True

    def test_detects_already_satisfied_end(self, runner) -> None:
        checker = runner._make_plan_complete_checker(10)
        assert checker("ALREADY_SATISFIED_END") is True

    def test_returns_false_when_no_markers(self, runner) -> None:
        checker = runner._make_plan_complete_checker(10)
        assert checker("partial output") is False


# ---------------------------------------------------------------------------
# _collect_validation_errors
# ---------------------------------------------------------------------------


class TestCollectValidationErrors:
    """Tests for PlannerRunner._collect_validation_errors."""

    def test_lite_skips_gate_errors(self, runner, planner_task) -> None:
        with patch.object(runner, "_validate_plan", return_value=["err1"]):
            errors = runner._collect_validation_errors(
                planner_task, "some plan", "lite"
            )
        assert errors == ["err1"]

    def test_full_includes_gate_errors(self, runner, planner_task) -> None:
        with (
            patch.object(runner, "_validate_plan", return_value=["err1"]),
            patch.object(
                runner,
                "_run_phase_minus_one_gates",
                return_value=(["gate_err"], []),
            ),
        ):
            errors = runner._collect_validation_errors(
                planner_task, "some plan", "full"
            )
        assert "err1" in errors
        assert "gate_err" in errors


# ---------------------------------------------------------------------------
# _finalize_result
# ---------------------------------------------------------------------------


class TestFinalizeResult:
    """Tests for PlannerRunner._finalize_result."""

    def test_sets_duration(self, runner, planner_task) -> None:
        result = PlanResult(issue_number=10)
        runner._finalize_result(planner_task, result, 0.0)
        assert result.duration_seconds > 0

    def test_saves_plan_on_success(self, runner, planner_task) -> None:
        result = PlanResult(issue_number=10)
        result.success = True
        result.plan = "the plan"
        result.summary = "summary"
        with (
            patch.object(runner, "_save_transcript"),
            patch.object(runner, "_save_plan") as mock_save,
        ):
            runner._finalize_result(planner_task, result, 0.0)
        mock_save.assert_called_once_with(10, "the plan", "summary")

    def test_skips_plan_save_on_failure(self, runner, planner_task) -> None:
        result = PlanResult(issue_number=10)
        result.success = False
        with (
            patch.object(runner, "_save_transcript"),
            patch.object(runner, "_save_plan") as mock_save,
        ):
            runner._finalize_result(planner_task, result, 0.0)
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# _build_research_section
# ---------------------------------------------------------------------------


class TestBuildResearchSection:
    """Tests for PlannerRunner._build_research_section."""

    def test_empty_when_no_context(self) -> None:
        assert PlannerRunner._build_research_section("") == ""

    def test_includes_research_context(self) -> None:
        result = PlannerRunner._build_research_section("Found class Foo at line 42")
        assert "## Pre-Plan Research" in result
        assert "Found class Foo at line 42" in result

    def test_includes_guidance_text(self) -> None:
        result = PlannerRunner._build_research_section("context")
        assert "do not repeat this exploration" in result


# ---------------------------------------------------------------------------
# _assemble_planning_prompt
# ---------------------------------------------------------------------------


class TestAssemblePlanningPrompt:
    """Tests for PlannerRunner._assemble_planning_prompt."""

    def test_contains_issue_info(self, runner, planner_task) -> None:
        prompt = runner._assemble_planning_prompt(
            planner_task,
            body="Implement feature X",
            image_note="",
            comments_section="",
            research_section="",
            manifest_section="",
            memory_section="",
            mode_note="**Plan mode: FULL**\n\n",
            schema_section="## Plan Format",
            task_graph_guidance="",
            pre_mortem_section="",
        )
        assert "issue #10" in prompt.lower()
        assert "Add feature X" in prompt
        assert "Implement feature X" in prompt

    def test_includes_read_only_instruction(self, runner, planner_task) -> None:
        prompt = runner._assemble_planning_prompt(
            planner_task,
            body="",
            image_note="",
            comments_section="",
            research_section="",
            manifest_section="",
            memory_section="",
            mode_note="",
            schema_section="",
            task_graph_guidance="",
            pre_mortem_section="",
        )
        assert "READ-ONLY" in prompt

    def test_includes_research_section(self, runner, planner_task) -> None:
        prompt = runner._assemble_planning_prompt(
            planner_task,
            body="",
            image_note="",
            comments_section="",
            research_section="\n\n## Pre-Plan Research\n\nSome research",
            manifest_section="",
            memory_section="",
            mode_note="",
            schema_section="",
            task_graph_guidance="",
            pre_mortem_section="",
        )
        assert "Pre-Plan Research" in prompt
        assert "Some research" in prompt


# ---------------------------------------------------------------------------
# _compute_prompt_stats
# ---------------------------------------------------------------------------


class TestPlannerComputePromptStats:
    """Tests for PlannerRunner._compute_prompt_stats."""

    def test_no_pruning(self) -> None:
        stats = PlannerRunner._compute_prompt_stats(
            history_before=100,
            history_after=100,
            body_raw_len=200,
            body_len=200,
        )
        assert stats["pruned_chars_total"] == 0

    def test_with_pruning(self) -> None:
        stats = PlannerRunner._compute_prompt_stats(
            history_before=500,
            history_after=200,
            body_raw_len=1000,
            body_len=600,
        )
        assert stats["pruned_chars_total"] == 700
        assert stats["section_chars"]["discussion_before"] == 500
        assert stats["section_chars"]["discussion_after"] == 200

    def test_returns_expected_keys(self) -> None:
        stats = PlannerRunner._compute_prompt_stats(
            history_before=0,
            history_after=0,
            body_raw_len=0,
            body_len=0,
        )
        assert "history_chars_before" in stats
        assert "context_chars_before" in stats
        assert "pruned_chars_total" in stats
        assert "section_chars" in stats


# ---------------------------------------------------------------------------
# _build_exploration_and_steps_section
# ---------------------------------------------------------------------------


class TestBuildExplorationAndStepsSection:
    """Tests for PlannerRunner._build_exploration_and_steps_section."""

    def test_contains_exploration_header(self) -> None:
        section = PlannerRunner._build_exploration_and_steps_section()
        assert "## Exploration Strategy" in section

    def test_contains_planning_steps(self) -> None:
        section = PlannerRunner._build_exploration_and_steps_section()
        assert "## Planning Steps" in section

    def test_contains_semantic_tools(self) -> None:
        section = PlannerRunner._build_exploration_and_steps_section()
        assert "claude-context search_code" in section
        assert "cclsp" in section

    def test_contains_ui_exploration(self) -> None:
        section = PlannerRunner._build_exploration_and_steps_section()
        assert "UI Exploration" in section

    def test_returns_string(self) -> None:
        result = PlannerRunner._build_exploration_and_steps_section()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _build_discovered_issues_section
# ---------------------------------------------------------------------------


class TestBuildDiscoveredIssuesSection:
    """Tests for PlannerRunner._build_discovered_issues_section."""

    def test_contains_markers(self) -> None:
        section = PlannerRunner._build_discovered_issues_section("hydraflow-plan")
        assert "NEW_ISSUES_START" in section
        assert "NEW_ISSUES_END" in section

    def test_includes_find_label(self) -> None:
        section = PlannerRunner._build_discovered_issues_section("my-label")
        assert "my-label" in section

    def test_contains_instructions(self) -> None:
        section = PlannerRunner._build_discovered_issues_section("hydraflow-plan")
        assert "Optional: Discovered Issues" in section
        assert ">=50 chars" in section

    def test_empty_label(self) -> None:
        section = PlannerRunner._build_discovered_issues_section("")
        assert "NEW_ISSUES_START" in section


# ---------------------------------------------------------------------------
# _build_already_satisfied_section
# ---------------------------------------------------------------------------


class TestBuildAlreadySatisfiedSection:
    """Tests for PlannerRunner._build_already_satisfied_section."""

    def test_contains_markers(self) -> None:
        section = PlannerRunner._build_already_satisfied_section()
        assert "ALREADY_SATISFIED_START" in section
        assert "ALREADY_SATISFIED_END" in section

    def test_contains_evidence_fields(self) -> None:
        section = PlannerRunner._build_already_satisfied_section()
        assert "Feature:" in section
        assert "Tests:" in section
        assert "Criteria:" in section

    def test_contains_warnings(self) -> None:
        section = PlannerRunner._build_already_satisfied_section()
        assert "VERY RARELY" in section
        assert "False positives" in section

    def test_returns_string(self) -> None:
        result = PlannerRunner._build_already_satisfied_section()
        assert isinstance(result, str)
        assert len(result) > 0
