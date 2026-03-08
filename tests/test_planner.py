"""Tests for dx/hydraflow/planner.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_runner import BaseRunner
from events import EventType
from models import PlannerStatus, Task
from planner import PlannerRunner
from tests.helpers import ConfigFactory, make_streaming_proc

# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestPlannerRunnerInheritance:
    """PlannerRunner must extend BaseRunner."""

    def test_inherits_from_base_runner(self, config, event_bus) -> None:
        runner = PlannerRunner(config, event_bus)
        assert isinstance(runner, BaseRunner)

    def test_has_terminate_method(self, config, event_bus) -> None:
        runner = PlannerRunner(config, event_bus)
        assert callable(runner.terminate)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runner(config, event_bus):
    return PlannerRunner(config=config, event_bus=event_bus)


def _valid_plan(*, word_pad: int = 200) -> str:
    """Return a plan with all required sections that passes validation."""
    padding = " ".join(["word"] * max(0, word_pad - 80))
    return (
        "## Files to Modify\n\n"
        "- src/models.py — add new data model\n"
        "- src/config.py — add configuration field\n\n"
        "## New Files\n\n"
        "None\n\n"
        "## File Delta\n\n"
        "MODIFIED: src/models.py\n"
        "MODIFIED: src/config.py\n\n"
        "## Implementation Steps\n\n"
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic\n\n"
        "## Testing Strategy\n\n"
        "- Add tests/test_models.py for the new model\n"
        "- Add tests/test_config.py for the new config field\n\n"
        "## Acceptance Criteria\n\n"
        "- New model can be created and serialized\n"
        "- Config field is validated correctly\n\n"
        "## Key Considerations\n\n"
        "- Backward compatibility with existing serialization\n"
        f"- Edge cases around empty values\n\n{padding}"
    )


def _valid_transcript(*, word_pad: int = 200) -> str:
    """Return a transcript containing a valid plan."""
    return (
        "Analysis complete.\n"
        f"PLAN_START\n{_valid_plan(word_pad=word_pad)}\nPLAN_END\n"
        "SUMMARY: Implementation plan for the feature"
    )


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


def test_build_command_includes_output_format(config):
    runner = _make_runner(config, None)
    cmd = runner._build_command()

    assert "--output-format" in cmd
    fmt_idx = cmd.index("--output-format")
    assert cmd[fmt_idx + 1] == "stream-json"


def test_build_command_includes_verbose(config):
    runner = _make_runner(config, None)
    cmd = runner._build_command()

    assert "--verbose" in cmd


def test_build_command_disallows_write_tools(config):
    runner = _make_runner(config, None)
    cmd = runner._build_command()

    assert "--disallowedTools" in cmd
    idx = cmd.index("--disallowedTools")
    blocked = cmd[idx + 1]
    assert "Write" in blocked
    assert "Edit" in blocked
    assert "NotebookEdit" in blocked


def test_build_command_supports_codex_backend(tmp_path):
    cfg = ConfigFactory.create(
        planner_tool="codex",
        planner_model="gpt-5-codex",
        repo_root=tmp_path / "repo",
        worktree_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    runner = _make_runner(cfg, None)
    cmd = runner._build_command()
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_includes_issue_number(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert f"#{task.id}" in prompt


def test_build_prompt_includes_issue_context(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert task.title in prompt
    assert task.body in prompt


def test_build_prompt_includes_read_only_instructions(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "READ-ONLY" in prompt
    assert "Do NOT create, modify, or delete any files" in prompt


def test_build_prompt_includes_plan_markers(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "PLAN_START" in prompt
    assert "PLAN_END" in prompt
    assert "SUMMARY:" in prompt


def test_build_prompt_includes_comments_when_present(config, event_bus):
    task = Task(
        id=42,
        title="Fix the frobnicator",
        body="It is broken.",
        comments=["First comment", "Second comment"],
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    assert "First comment" in prompt
    assert "Second comment" in prompt
    assert "Discussion" in prompt


def test_build_prompt_omits_comments_section_when_empty(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "Discussion" not in prompt


def test_build_prompt_truncates_long_body(config, event_bus):
    task = Task(
        id=1, title="Big issue", body="X" * 20_000, tags=[], comments=[], source_url=""
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    assert "…(truncated)" in prompt
    assert len(prompt) < 10_000  # well under original 20k body


def test_build_prompt_truncates_long_comments(config, event_bus):
    task = Task(
        id=1,
        title="Big comments",
        body="Normal body with enough content",
        tags=[],
        comments=["C" * 5000, "Short"],
        source_url="",
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    # First comment should be truncated, second should be intact
    assert "…" in prompt
    assert "Short" in prompt


def test_build_prompt_truncates_long_lines(config, event_bus):
    """Lines exceeding _MAX_LINE_CHARS are hard-truncated to prevent
    Claude CLI text-splitter failures."""
    long_line = "A" * 2000
    body = f"Short line\n{long_line}\nAnother short line"
    task = Task(
        id=1, title="Long lines", body=body, tags=[], comments=[], source_url=""
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    # No line in the prompt should exceed _MAX_LINE_CHARS + ellipsis
    for line in prompt.splitlines():
        assert len(line) <= runner._MAX_LINE_CHARS + 10  # small margin for marker text


def test_truncate_text_respects_line_boundaries():
    """_truncate_text cuts at line boundaries, not mid-line."""
    text = "line1\nline2\nline3\nline4\nline5"
    result = PlannerRunner._truncate_text(text, char_limit=18, line_limit=500)
    # Should include line1 (5) + \n + line2 (5) + \n + line3 (5) = 17 chars
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result
    assert "line4" not in result or "…(truncated)" in result


def test_truncate_text_no_truncation_when_under_limit():
    """_truncate_text returns text unchanged when under limits."""
    text = "short text"
    result = PlannerRunner._truncate_text(text, char_limit=500, line_limit=500)
    assert result == text
    assert "…(truncated)" not in result


# ---------------------------------------------------------------------------
# _build_prompt - image handling
# ---------------------------------------------------------------------------


def test_build_prompt_notes_images_in_body(config, event_bus):
    """When the issue body contains markdown images, the prompt should note them."""
    task = Task(
        id=99,
        title="Fix layout bug",
        body="The layout is broken.\n\n![screenshot](https://example.com/img.png)\n\nSee above.",
        tags=[],
        comments=[],
        source_url="",
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    assert "image" in prompt.lower() or "screenshot" in prompt.lower()
    assert "visual" in prompt.lower() or "attached" in prompt.lower()


def test_build_prompt_notes_html_images_in_body(config, event_bus):
    """When the issue body contains HTML img tags, the prompt should note them."""
    task = Task(
        id=99,
        title="Fix layout bug",
        body='See screenshot:\n\n<img src="https://example.com/img.png" />\n\nPlease fix.',
        tags=[],
        comments=[],
        source_url="",
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    assert "image" in prompt.lower() or "screenshot" in prompt.lower()


def test_build_prompt_no_image_note_when_no_images(config, event_bus, issue):
    """When the issue body has no images, no image note should be added."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "image" not in prompt.lower() or "image" in task.body.lower()
    # The specific note about attached images should not appear
    assert "visual context" not in prompt.lower()


def test_build_prompt_handles_multiple_images(config, event_bus):
    """Multiple images in the body should still produce a single note."""
    task = Task(
        id=99,
        title="Fix layout bug",
        body="![img1](https://example.com/1.png)\n![img2](https://example.com/2.png)",
        tags=[],
        comments=[],
        source_url="",
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    # Should mention images
    assert "image" in prompt.lower()


# ---------------------------------------------------------------------------
# _build_prompt - UI exploration guidance
# ---------------------------------------------------------------------------


def test_build_prompt_includes_ui_exploration_guidance(config, event_bus, issue):
    """Planner prompt should include UI exploration patterns."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "src/ui/src/components/" in prompt
    assert "constants.js" in prompt
    assert "theme.js" in prompt
    assert "types.js" in prompt


# ---------------------------------------------------------------------------
# _extract_plan
# ---------------------------------------------------------------------------


def test_extract_plan_with_markers(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "Some preamble\nPLAN_START\nStep 1: Do this\nStep 2: Do that\nPLAN_END\nSome epilogue"
    plan = runner._extract_plan(transcript)

    assert plan == "Step 1: Do this\nStep 2: Do that"


def test_extract_plan_without_markers_returns_empty(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "Here is the full plan without markers.\nLine 2."
    plan = runner._extract_plan(transcript)

    assert plan == ""


def test_extract_plan_budget_exceeded_returns_empty(config, event_bus):
    """Budget-exceeded error output must not be treated as a plan."""
    runner = _make_runner(config, event_bus)
    transcript = "Error: Exceeded USD budget (3)"
    plan = runner._extract_plan(transcript)

    assert plan == ""


def test_extract_plan_multiline(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = (
        "Analysis:\nPLAN_START\n"
        "## Files to modify\n\n"
        "- models.py: Add new class\n"
        "- tests/test_models.py: Add tests\n\n"
        "## Steps\n\n"
        "1. Create the model\n"
        "2. Write tests\n"
        "PLAN_END\n"
        "SUMMARY: Add new model"
    )
    plan = runner._extract_plan(transcript)

    assert "## Files to modify" in plan
    assert "## Steps" in plan
    assert "SUMMARY" not in plan


def test_extract_plan_empty_transcript(config, event_bus):
    runner = _make_runner(config, event_bus)
    plan = runner._extract_plan("")

    assert plan == ""


# ---------------------------------------------------------------------------
# _extract_summary
# ---------------------------------------------------------------------------


def test_extract_summary_with_summary_line(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "Plan done.\nPLAN_END\nSUMMARY: implement the widget feature"
    summary = runner._extract_summary(transcript)

    assert summary == "implement the widget feature"


def test_extract_summary_case_insensitive(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "summary: all changes identified"
    summary = runner._extract_summary(transcript)

    assert summary == "all changes identified"


def test_extract_summary_fallback_to_last_line(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "First line.\nSecond line.\nThis is the last line"
    summary = runner._extract_summary(transcript)

    assert summary == "This is the last line"


def test_extract_summary_empty_transcript(config, event_bus):
    runner = _make_runner(config, event_bus)
    summary = runner._extract_summary("")

    assert summary == "No summary provided"


# ---------------------------------------------------------------------------
# _extract_already_satisfied
# ---------------------------------------------------------------------------


def test_extract_already_satisfied_with_markers():
    transcript = (
        "Analysis complete.\n"
        "ALREADY_SATISFIED_START\n"
        "The feature described in this issue is already implemented "
        "in src/models.py lines 10-25.\n"
        "ALREADY_SATISFIED_END\n"
        "Done."
    )
    result = PlannerRunner._extract_already_satisfied(transcript)
    assert "already implemented" in result
    assert "src/models.py" in result


def test_extract_already_satisfied_without_markers():
    transcript = "Analysis complete.\nPLAN_START\nStep 1\nPLAN_END\nSUMMARY: Done"
    result = PlannerRunner._extract_already_satisfied(transcript)
    assert result == ""


def test_extract_already_satisfied_empty_transcript():
    result = PlannerRunner._extract_already_satisfied("")
    assert result == ""


def test_extract_already_satisfied_strips_whitespace():
    transcript = (
        "ALREADY_SATISFIED_START\n"
        "  The code already handles this.  \n"
        "ALREADY_SATISFIED_END"
    )
    result = PlannerRunner._extract_already_satisfied(transcript)
    assert result == "The code already handles this."


def test_extract_already_satisfied_multiline():
    transcript = (
        "ALREADY_SATISFIED_START\n"
        "Line 1 of explanation.\n"
        "Line 2 of explanation.\n"
        "Line 3 of explanation.\n"
        "ALREADY_SATISFIED_END"
    )
    result = PlannerRunner._extract_already_satisfied(transcript)
    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result


# ---------------------------------------------------------------------------
# _build_prompt - already satisfied markers
# ---------------------------------------------------------------------------


def test_build_prompt_includes_already_satisfied_markers(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "ALREADY_SATISFIED_START" in prompt
    assert "ALREADY_SATISFIED_END" in prompt


def test_build_prompt_lite_includes_already_satisfied_markers(config, event_bus):
    """Lite prompt (for bug/typo tags) should also include markers."""
    task = Task(
        id=42,
        title="Fix typo",
        body="There's a typo in the docs.",
        tags=["bug"],
        comments=[],
    )
    runner = _make_runner(config, event_bus)
    prompt = runner._build_prompt(task)

    assert "ALREADY_SATISFIED_START" in prompt
    assert "ALREADY_SATISFIED_END" in prompt


# ---------------------------------------------------------------------------
# _significant_words
# ---------------------------------------------------------------------------


def test_significant_words_extracts_long_words(config, event_bus):
    runner = _make_runner(config, event_bus)
    words = runner._significant_words("Fix the broken authentication handler")
    assert "broken" in words
    assert "authentication" in words
    assert "handler" in words
    # "the" is too short (< 4 chars)
    assert "the" not in words
    # "Fix" is too short
    assert "fix" not in words


def test_significant_words_filters_stop_words(config, event_bus):
    runner = _make_runner(config, event_bus)
    words = runner._significant_words("This should have been done with more care")
    # All are stop words or short
    assert "this" not in words
    assert "should" not in words
    assert "have" not in words
    assert "been" not in words
    assert "with" not in words
    assert "more" not in words
    assert "care" in words
    assert "done" in words


def test_significant_words_empty_string(config, event_bus):
    runner = _make_runner(config, event_bus)
    words = runner._significant_words("")
    assert words == set()


# ---------------------------------------------------------------------------
# _validate_plan — schema validation
# ---------------------------------------------------------------------------


def test_validate_plan_all_sections_present(config, event_bus):
    """A valid plan with all 6 sections and sufficient words passes."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix authentication handler")
    errors = runner._validate_plan(task, _valid_plan())
    assert errors == []


def test_validate_plan_missing_section_returns_errors(config, event_bus):
    """Plan missing '## Testing Strategy' returns that specific error."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix authentication handler")
    plan = _valid_plan().replace("## Testing Strategy", "## Tests")
    errors = runner._validate_plan(task, plan)
    assert any("Testing Strategy" in e for e in errors)


def test_validate_plan_missing_multiple_sections(config, event_bus):
    """Plan missing 3 sections returns 3 corresponding errors."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix auth")
    plan = _valid_plan()
    plan = plan.replace("## Testing Strategy", "## Tests")
    plan = plan.replace("## Acceptance Criteria", "## Done")
    plan = plan.replace("## Key Considerations", "## Notes")
    errors = runner._validate_plan(task, plan)
    missing = [e for e in errors if "Missing required section" in e]
    assert len(missing) == 3


def test_validate_plan_files_to_modify_requires_file_path(config, event_bus):
    """Files to Modify section present but with no file paths fails."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "- src/models.py — add new data model\n"
        "- src/config.py — add configuration field",
        "- Some vague description without paths",
    )
    errors = runner._validate_plan(task, plan)
    assert any("file path" in e for e in errors)


def test_validate_plan_testing_strategy_requires_test_reference(config, event_bus):
    """Testing Strategy section present but with no test file references fails."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "- Add tests/test_models.py for the new model\n"
        "- Add tests/test_config.py for the new config field",
        "- Write some unit checks\n- Verify behavior manually",
    )
    errors = runner._validate_plan(task, plan)
    assert any("test file" in e for e in errors)


def test_validate_plan_implementation_steps_requires_at_least_one_step(
    config, event_bus
):
    """Implementation Steps must include at least one actionable list item."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic",
        "Do the thing and then verify",
    )
    errors = runner._validate_plan(task, plan)
    assert any("at least one actionable step" in e for e in errors)


def test_validate_plan_implementation_steps_allows_slim_numbered_plan(
    config, event_bus
):
    """A concise numbered plan should pass without a 3-step minimum."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic",
        "1. Update src/models.py model wiring\n2. Validate orchestrator.load_models() behavior",
    )
    errors = runner._validate_plan(task, plan)
    assert not any("Implementation Steps" in e for e in errors)


def test_validate_plan_implementation_steps_allows_bulleted_plan(config, event_bus):
    """Bulleted implementation steps are valid."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic",
        "- Update src/planner.py validation rule\n- Add tests/test_planner.py regression case",
    )
    errors = runner._validate_plan(task, plan)
    assert not any("Implementation Steps" in e for e in errors)


def test_validate_plan_implementation_steps_allows_markdown_heading_steps(
    config, event_bus
):
    """Markdown heading-style steps (### Step 1 / ### 1.) are valid."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic",
        "### Step 1: Update src/dashboard_routes.py worker metadata\n"
        "### 2. Wire ReviewPhase._record_review_insight() callbacks\n"
        "### Step 3: Add tests/test_review_phase.py regression tests",
    )
    errors = runner._validate_plan(task, plan)
    assert not any("Implementation Steps" in e for e in errors)


def test_validate_plan_implementation_steps_requires_two_for_full(config, event_bus):
    """Full plans need at least two implementation steps."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic",
        "1. Update src/models.py and validate behavior",
    )
    errors = runner._validate_plan(task, plan, scale="full")
    assert any("at least 2 steps for full plans" in e for e in errors)


def test_validate_plan_implementation_steps_require_concrete_target(config, event_bus):
    """Full plans should reference concrete code targets in implementation steps."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    plan = _valid_plan().replace(
        "1. Add the new model class to models.py\n"
        "2. Add configuration field to config.py\n"
        "3. Wire up the new model in the orchestrator\n"
        "4. Add validation logic",
        "1. Improve architecture and verify outcomes\n"
        "2. Refine behavior and validate assumptions",
    )
    errors = runner._validate_plan(task, plan, scale="full")
    assert any("concrete code target" in e for e in errors)


def test_score_actionability_high_for_concrete_plan(config, event_bus):
    """Concrete, test-aware plans should rank high actionability."""
    runner = _make_runner(config, event_bus)
    score, rank = runner._score_actionability(_valid_plan(), scale="full")
    assert score >= 85
    assert rank == "high"


def test_score_actionability_low_for_shallow_plan(config, event_bus):
    """Shallow plans with vague steps should rank low."""
    runner = _make_runner(config, event_bus)
    shallow_plan = (
        _valid_plan()
        .replace(
            "1. Add the new model class to models.py\n"
            "2. Add configuration field to config.py\n"
            "3. Wire up the new model in the orchestrator\n"
            "4. Add validation logic",
            "1. Do stuff\n2. Make better",
        )
        .replace(
            "## Testing Strategy\n\n"
            "- Add tests/test_models.py for the new model\n"
            "- Add tests/test_config.py for the new config field",
            "## Testing Strategy\n\n- Manual check",
        )
        .replace(
            "## File Delta\n\nMODIFIED: src/models.py\nMODIFIED: src/config.py",
            "## File Delta\n\nNone",
        )
    )
    score, rank = runner._score_actionability(shallow_plan, scale="full")
    assert score < 65
    assert rank == "low"


def test_validate_plan_minimum_word_count(config, event_bus):
    """Plan below min_plan_words fails."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix it")
    # Create a short plan that has all sections but few words
    short_plan = (
        "## Files to Modify\n\n- src/app.py — fix\n\n"
        "## New Files\n\nNone\n\n"
        "## Implementation Steps\n\n1. A\n2. B\n3. C\n\n"
        "## Testing Strategy\n\n- tests/test_app.py\n\n"
        "## Acceptance Criteria\n\n- Done\n\n"
        "## Key Considerations\n\n- None\n"
    )
    errors = runner._validate_plan(task, short_plan)
    assert any("words" in e for e in errors)


def test_validate_plan_word_count_configurable(event_bus, tmp_path):
    """Custom min_plan_words is respected."""
    cfg = ConfigFactory.create(min_plan_words=50, repo_root=tmp_path)
    runner = _make_runner(cfg, event_bus)
    task = Task(id=1, title="Fix it")
    # This plan has all sections but only ~50 words
    plan = (
        "## Files to Modify\n\n- src/app.py — fix bug\n\n"
        "## New Files\n\nNone\n\n"
        "## Implementation Steps\n\n1. Fix the bug in app.py\n"
        "2. Update the tests for the fix\n"
        "3. Run the test suite to verify\n\n"
        "## Testing Strategy\n\n- tests/test_app.py covers the fix\n\n"
        "## Acceptance Criteria\n\n- Bug is fixed\n\n"
        "## Key Considerations\n\n- Backward compatibility\n"
    )
    errors = runner._validate_plan(task, plan)
    assert not any("words" in e for e in errors)


def test_validate_plan_logs_warning_on_word_mismatch(config, event_bus):
    """Word-overlap check logs a warning but doesn't produce errors."""
    from unittest.mock import patch as mock_patch

    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix authentication handler")
    # Valid plan but title words don't overlap with plan
    plan = _valid_plan().replace("authentication", "database")

    with mock_patch("planner.logger") as mock_logger:
        runner._validate_plan(task, plan)

    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# _extract_new_issues
# ---------------------------------------------------------------------------


def test_extract_new_issues_with_markers(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = (
        "PLAN_START\nStep 1\nPLAN_END\n"
        "NEW_ISSUES_START\n"
        "- title: Fix the widget\n"
        "  body: The widget is broken\n"
        "  labels: bug, high-priority\n"
        "- title: Refactor auth module\n"
        "  body: Needs cleanup\n"
        "  labels: tech-debt\n"
        "NEW_ISSUES_END\n"
        "SUMMARY: done"
    )
    issues = runner._extract_new_issues(transcript)
    assert len(issues) == 2
    assert issues[0].title == "Fix the widget"
    assert issues[0].body == "The widget is broken"
    assert "bug" in issues[0].labels
    assert "high-priority" in issues[0].labels
    assert issues[1].title == "Refactor auth module"
    assert "tech-debt" in issues[1].labels


def test_extract_new_issues_without_markers(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "PLAN_START\nStep 1\nPLAN_END\nSUMMARY: done"
    issues = runner._extract_new_issues(transcript)
    assert issues == []


def test_extract_new_issues_single_issue(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = (
        "NEW_ISSUES_START\n"
        "- title: Add logging\n"
        "  body: We need more logging\n"
        "  labels: enhancement\n"
        "NEW_ISSUES_END"
    )
    issues = runner._extract_new_issues(transcript)
    assert len(issues) == 1
    assert issues[0].title == "Add logging"


def test_extract_new_issues_multiline_body(config, event_bus):
    """Multi-line body continuation lines are concatenated."""
    runner = _make_runner(config, event_bus)
    transcript = (
        "NEW_ISSUES_START\n"
        "- title: Fix the widget\n"
        "  body: The widget is broken in production. Users are seeing\n"
        "    errors when they click the submit button because the form\n"
        "    validation skips required fields.\n"
        "  labels: bug\n"
        "NEW_ISSUES_END"
    )
    issues = runner._extract_new_issues(transcript)
    assert len(issues) == 1
    assert issues[0].title == "Fix the widget"
    assert "widget is broken" in issues[0].body
    assert "form" in issues[0].body
    assert "validation" in issues[0].body
    assert len(issues[0].body) > 50


# ---------------------------------------------------------------------------
# plan - success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_success_path(config, event_bus, issue, tmp_path):
    runner = _make_runner(config, event_bus)
    transcript = _valid_transcript()
    task = issue.to_task()

    mock_execute = AsyncMock(return_value=transcript)

    with (
        patch.object(runner, "_execute", mock_execute),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.issue_number == task.id
    assert result.success is True
    assert "## Files to Modify" in result.plan
    assert result.summary == "Implementation plan for the feature"
    assert result.validation_errors == []


# ---------------------------------------------------------------------------
# plan - failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_failure_on_exception(config, event_bus, issue, tmp_path):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    mock_execute = AsyncMock(side_effect=RuntimeError("subprocess crashed"))

    with patch.object(runner, "_execute", mock_execute):
        result = await runner.plan(task, worker_id=0)

    assert result.success is False
    assert result.error == "subprocess crashed"


# ---------------------------------------------------------------------------
# plan - dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_dry_run(dry_config, event_bus, issue, tmp_path):
    runner = _make_runner(dry_config, event_bus)
    task = issue.to_task()
    mock_create = make_streaming_proc(returncode=0, stdout="")

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await runner.plan(task, worker_id=0)

    mock_create.assert_not_called()
    assert result.success is True
    assert result.summary == "Dry-run: plan skipped"


# ---------------------------------------------------------------------------
# plan - already_satisfied path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_already_satisfied_sets_flag_and_skips_validation(
    config, event_bus, issue
):
    """When transcript contains ALREADY_SATISFIED markers, plan() should
    set already_satisfied=True, success=True, and skip plan extraction."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    transcript = (
        "Analysis complete.\n"
        "ALREADY_SATISFIED_START\n"
        "The feature is already implemented in src/models.py lines 10-25.\n"
        "ALREADY_SATISFIED_END\n"
    )

    mock_execute = AsyncMock(return_value=transcript)

    with (
        patch.object(runner, "_execute", mock_execute),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.already_satisfied is True
    assert result.success is True
    assert result.plan == ""  # no plan extracted
    assert "already implemented" in result.summary


@pytest.mark.asyncio
async def test_plan_already_satisfied_does_not_extract_plan(config, event_bus, issue):
    """When already_satisfied markers are present, _extract_plan should NOT be called."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    transcript = "ALREADY_SATISFIED_START\nAlready done.\nALREADY_SATISFIED_END\n"

    mock_execute = AsyncMock(return_value=transcript)

    with (
        patch.object(runner, "_execute", mock_execute),
        patch.object(runner, "_save_transcript"),
        patch.object(runner, "_extract_plan") as mock_extract,
    ):
        result = await runner.plan(task, worker_id=0)

    mock_extract.assert_not_called()
    assert result.already_satisfied is True


# ---------------------------------------------------------------------------
# _save_transcript
# ---------------------------------------------------------------------------


def test_save_transcript_writes_to_correct_path(event_bus, tmp_path):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = PlannerRunner(config=cfg, event_bus=event_bus)
    transcript = "This is the planning transcript."

    runner._save_transcript("plan-issue", 42, transcript)

    expected_path = tmp_path / ".hydraflow" / "logs" / "plan-issue-42.txt"
    assert expected_path.exists()
    assert expected_path.read_text() == transcript


def test_save_transcript_creates_log_directory(event_bus, tmp_path):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = PlannerRunner(config=cfg, event_bus=event_bus)
    log_dir = tmp_path / ".hydraflow" / "logs"
    assert not log_dir.exists()

    runner._save_transcript("plan-issue", 7, "transcript content")

    assert log_dir.exists()
    assert log_dir.is_dir()


def test_save_transcript_handles_oserror(event_bus, tmp_path, caplog):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = PlannerRunner(config=cfg, event_bus=event_bus)

    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        runner._save_transcript("plan-issue", 42, "transcript")  # should not raise

    assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# _save_plan
# ---------------------------------------------------------------------------


def test_save_plan_writes_to_correct_path(event_bus, tmp_path):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = PlannerRunner(config=cfg, event_bus=event_bus)

    runner._save_plan(42, "Step 1: Do X\nStep 2: Do Y", "Two-step plan")

    expected_path = tmp_path / ".hydraflow" / "plans" / "issue-42.md"
    assert expected_path.exists()
    content = expected_path.read_text()
    assert "Step 1: Do X" in content
    assert "Two-step plan" in content


def test_save_plan_creates_plans_directory(event_bus, tmp_path):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = PlannerRunner(config=cfg, event_bus=event_bus)
    plan_dir = tmp_path / ".hydraflow" / "plans"
    assert not plan_dir.exists()

    runner._save_plan(7, "Some plan", "Summary")

    assert plan_dir.exists()
    assert plan_dir.is_dir()


def test_save_plan_handles_oserror(event_bus, tmp_path, caplog):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = PlannerRunner(config=cfg, event_bus=event_bus)

    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        runner._save_plan(42, "Some plan", "Summary")  # should not raise

    assert "Could not save plan" in caplog.text


# ---------------------------------------------------------------------------
# plan() — _save_transcript / _save_plan OSError defense-in-depth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_returns_result_when_save_transcript_raises_os_error(
    config, event_bus, issue, caplog
):
    """plan() should return a valid PlanResult even if _save_transcript raises OSError."""
    runner = _make_runner(config, event_bus)
    transcript = _valid_transcript()
    task = issue.to_task()

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_save_transcript", side_effect=OSError("disk full")),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is True
    assert result.issue_number == task.id
    assert "## Files to Modify" in result.plan
    assert "Failed to save transcript" in caplog.text


@pytest.mark.asyncio
async def test_plan_returns_result_when_save_plan_raises_os_error(
    config, event_bus, issue, caplog
):
    """plan() should return a successful PlanResult even if _save_plan raises OSError."""
    runner = _make_runner(config, event_bus)
    transcript = _valid_transcript()
    task = issue.to_task()

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_save_transcript"),
        patch.object(runner, "_save_plan", side_effect=OSError("disk full")),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is True
    assert result.issue_number == task.id
    assert "## Files to Modify" in result.plan
    assert "Failed to save plan" in caplog.text


@pytest.mark.asyncio
async def test_plan_returns_failure_result_when_save_transcript_raises_after_exception(
    config, event_bus, issue, caplog
):
    """plan() should return failure result even if _save_transcript raises after a planner error."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    with (
        patch.object(
            runner, "_execute", AsyncMock(side_effect=RuntimeError("planner crashed"))
        ),
        patch.object(runner, "_save_transcript", side_effect=OSError("disk full")),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is False
    assert "planner crashed" in (result.error or "")
    assert "Failed to save transcript" in caplog.text


@pytest.mark.asyncio
async def test_plan_already_satisfied_returns_success_when_save_transcript_raises_os_error(
    config, event_bus, issue, caplog
):
    """plan() should return already_satisfied=True even if _save_transcript raises OSError
    in the early-return path."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    transcript = (
        "ALREADY_SATISFIED_START\n"
        "The feature is already implemented in src/models.py.\n"
        "ALREADY_SATISFIED_END\n"
    )

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_save_transcript", side_effect=OSError("disk full")),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is True
    assert result.already_satisfied is True
    assert "Failed to save transcript" in caplog.text


# ---------------------------------------------------------------------------
# PLANNER_UPDATE events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_events_include_planner_role(config, event_bus, issue, tmp_path):
    """PLANNER_UPDATE events should carry role='planner'."""
    runner = _make_runner(config, event_bus)
    transcript = _valid_transcript()
    task = issue.to_task()

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.plan(task, worker_id=1)

    events = event_bus.get_history()
    planner_events = [e for e in events if e.type == EventType.PLANNER_UPDATE]
    assert len(planner_events) >= 2
    for event in planner_events:
        assert event.data.get("role") == "planner"


@pytest.mark.asyncio
async def test_plan_emits_planning_and_done_events(config, event_bus, issue, tmp_path):
    """Status should go through planning → done on success."""
    runner = _make_runner(config, event_bus)
    transcript = _valid_transcript()
    task = issue.to_task()

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.plan(task, worker_id=0)

    events = event_bus.get_history()
    planner_events = [e for e in events if e.type == EventType.PLANNER_UPDATE]

    statuses = [e.data["status"] for e in planner_events]
    assert PlannerStatus.PLANNING.value in statuses
    assert PlannerStatus.DONE.value in statuses


@pytest.mark.asyncio
async def test_plan_emits_planning_and_failed_events_on_error(
    config, event_bus, issue, tmp_path
):
    """Status should go through planning → failed on exception."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    with patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))):
        await runner.plan(task, worker_id=0)

    events = event_bus.get_history()
    planner_events = [e for e in events if e.type == EventType.PLANNER_UPDATE]

    statuses = [e.data["status"] for e in planner_events]
    assert PlannerStatus.PLANNING.value in statuses
    assert PlannerStatus.FAILED.value in statuses


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


def test_terminate_kills_active_processes(config, event_bus):
    runner = _make_runner(config, event_bus)
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    runner._active_procs.add(mock_proc)

    with patch("runner_utils.os.killpg") as mock_killpg:
        runner.terminate()

    mock_killpg.assert_called_once()


def test_terminate_handles_process_lookup_error(config, event_bus):
    runner = _make_runner(config, event_bus)
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    runner._active_procs.add(mock_proc)

    with patch("runner_utils.os.killpg", side_effect=ProcessLookupError):
        runner.terminate()  # Should not raise


def test_terminate_with_no_active_processes(config, event_bus):
    runner = _make_runner(config, event_bus)
    runner.terminate()  # Should not raise


# ---------------------------------------------------------------------------
# _execute - transcript lines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_publishes_transcript_lines(config, event_bus, issue, tmp_path):
    runner = _make_runner(config, event_bus)
    output = "Line one\nLine two\nLine three"
    task = issue.to_task()
    mock_create = make_streaming_proc(returncode=0, stdout=output)

    with patch("asyncio.create_subprocess_exec", mock_create):
        transcript = await runner._execute(
            ["claude", "-p"],
            "prompt",
            tmp_path,
            {"issue": task.id, "source": "planner"},
        )

    assert transcript == output

    events = event_bus.get_history()
    transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
    assert len(transcript_events) == 3
    for ev in transcript_events:
        assert ev.data["source"] == "planner"
        assert ev.data["issue"] == task.id


@pytest.mark.asyncio
async def test_execute_uses_large_stream_limit(config, event_bus, issue, tmp_path):
    """_execute should set limit=1MB to handle large stream-json lines."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    mock_create = make_streaming_proc(returncode=0, stdout="ok")

    with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
        await runner._execute(
            ["claude", "-p"],
            "prompt",
            tmp_path,
            {"issue": task.id, "source": "planner"},
        )

    kwargs = mock_exec.call_args[1]
    assert kwargs["limit"] == 1024 * 1024


# ---------------------------------------------------------------------------
# Phase -1 gates
# ---------------------------------------------------------------------------


def test_phase_minus_one_simplicity_gate_warns_on_many_new_files(config, event_bus):
    """Creating > max_new_files_warning new files produces a warning."""
    runner = _make_runner(config, event_bus)
    plan = _valid_plan().replace(
        "## New Files\n\nNone",
        "## New Files\n\n"
        "- src/new1.py\n- src/new2.py\n- src/new3.py\n"
        "- src/new4.py\n- src/new5.py\n- src/new6.py",
    )
    blocking, warnings = runner._run_phase_minus_one_gates(plan)
    assert not blocking
    assert any("Simplicity gate" in w for w in warnings)


def test_phase_minus_one_testing_gate_rejects_later(config, event_bus):
    """'tests will be added later' in Testing Strategy is rejected."""
    runner = _make_runner(config, event_bus)
    plan = _valid_plan().replace(
        "- Add tests/test_models.py for the new model\n"
        "- Add tests/test_config.py for the new config field",
        "Tests will be added later after implementation is stable.",
    )
    blocking, _ = runner._run_phase_minus_one_gates(plan)
    assert any("Testing gate" in e for e in blocking)


def test_phase_minus_one_testing_gate_rejects_tbd(config, event_bus):
    """'TBD' in Testing Strategy is rejected."""
    runner = _make_runner(config, event_bus)
    plan = _valid_plan().replace(
        "- Add tests/test_models.py for the new model\n"
        "- Add tests/test_config.py for the new config field",
        "TBD",
    )
    blocking, _ = runner._run_phase_minus_one_gates(plan)
    assert any("Testing gate" in e for e in blocking)


def test_phase_minus_one_testing_gate_accepts_valid(config, event_bus):
    """A proper testing strategy passes the testing gate."""
    runner = _make_runner(config, event_bus)
    blocking, _ = runner._run_phase_minus_one_gates(_valid_plan())
    assert not any("Testing gate" in e for e in blocking)


def test_phase_minus_one_constitution_gate_skipped_when_no_file(config, event_bus):
    """No constitution.md = gate passes with no errors."""
    runner = _make_runner(config, event_bus)
    blocking, warnings = runner._run_phase_minus_one_gates(_valid_plan())
    assert not any("Constitution gate" in e for e in blocking)
    assert not any("Constitution gate" in w for w in warnings)


def test_phase_minus_one_constitution_gate_reads_file(event_bus, tmp_path):
    """When constitution.md exists, its principles are checked against the plan."""
    cfg = ConfigFactory.create(repo_root=tmp_path)
    (tmp_path / "constitution.md").write_text(
        "# Principles\n\n- never delete user data\n- always validate input\n"
    )
    runner = _make_runner(cfg, event_bus)
    plan = _valid_plan() + "\nWe will never delete user data from the database.\n"
    blocking, _ = runner._run_phase_minus_one_gates(plan)
    assert any("Constitution gate" in e for e in blocking)


# ---------------------------------------------------------------------------
# Retry flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_retries_on_validation_failure(config, event_bus, issue):
    """First attempt fails validation, second succeeds."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    bad_transcript = "PLAN_START\nJust a one-liner.\nPLAN_END\nSUMMARY: bad"
    good_transcript = _valid_transcript()

    call_count = {"n": 0}

    async def mock_execute(cmd, prompt, cwd, event_data, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return bad_transcript
        return good_transcript

    with (
        patch.object(runner, "_execute", side_effect=mock_execute),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is True
    assert call_count["n"] == 2
    assert result.retry_attempted is False


@pytest.mark.asyncio
async def test_plan_retry_prompt_includes_feedback(config, event_bus, issue):
    """Retry prompt contains specific validation errors."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    bad_transcript = "PLAN_START\nJust a one-liner.\nPLAN_END\nSUMMARY: bad"

    prompts_used: list[str] = []

    async def mock_execute(cmd, prompt, cwd, event_data, **kwargs):
        prompts_used.append(prompt)
        if len(prompts_used) == 1:
            return bad_transcript
        return _valid_transcript()

    with (
        patch.object(runner, "_execute", side_effect=mock_execute),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.plan(task, worker_id=0)

    assert len(prompts_used) == 2
    retry_prompt = prompts_used[1]
    assert "Validation Errors" in retry_prompt
    assert "Missing required section" in retry_prompt


@pytest.mark.asyncio
async def test_plan_gives_up_after_two_failures(config, event_bus, issue):
    """Both attempts fail — result has retry_attempted=True."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    bad_transcript = "PLAN_START\nJust a one-liner.\nPLAN_END\nSUMMARY: bad"

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=bad_transcript)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is False
    assert result.retry_attempted is True
    assert len(result.validation_errors) > 0


@pytest.mark.asyncio
async def test_plan_no_retry_on_first_success(config, event_bus, issue):
    """Valid first attempt doesn't trigger retry."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    mock_execute = AsyncMock(return_value=_valid_transcript())

    with (
        patch.object(runner, "_execute", mock_execute),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is True
    assert result.retry_attempted is False
    # _execute called only once
    mock_execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_plan_retry_emits_retrying_status(config, event_bus, issue):
    """RETRYING status event is emitted when retrying."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    bad_transcript = "PLAN_START\nJust a one-liner.\nPLAN_END\nSUMMARY: bad"

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=bad_transcript)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.plan(task, worker_id=0)

    events = event_bus.get_history()
    planner_events = [e for e in events if e.type == EventType.PLANNER_UPDATE]
    statuses = [e.data["status"] for e in planner_events]
    assert PlannerStatus.RETRYING.value in statuses


@pytest.mark.asyncio
async def test_plan_emits_validating_status(config, event_bus, issue):
    """VALIDATING status event is emitted before validation."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=_valid_transcript())),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.plan(task, worker_id=0)

    events = event_bus.get_history()
    planner_events = [e for e in events if e.type == EventType.PLANNER_UPDATE]
    statuses = [e.data["status"] for e in planner_events]
    assert PlannerStatus.VALIDATING.value in statuses


# ---------------------------------------------------------------------------
# _build_retry_prompt
# ---------------------------------------------------------------------------


def test_build_retry_prompt_includes_issue_and_errors(config, event_bus, issue):
    """Retry prompt contains issue title, failed plan, and errors."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    failed_plan = "Some bad plan text"
    errors = ["Missing required section: ## Testing Strategy", "Plan has 10 words"]

    prompt, _stats = runner._build_retry_prompt(task, failed_plan, errors)

    assert f"#{task.id}" in prompt
    assert task.title in prompt
    assert "Some bad plan text" in prompt
    assert "Missing required section: ## Testing Strategy" in prompt
    assert "Plan has 10 words" in prompt
    assert "PLAN_START" in prompt
    assert "PLAN_END" in prompt


def test_build_retry_prompt_truncates_large_context(config, event_bus, issue):
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    failed_plan = "P" * 10000
    errors = ["x" * 1000 for _ in range(20)]

    prompt, stats = runner._build_retry_prompt(task, failed_plan, errors)

    assert "…(truncated)" in prompt
    assert int(stats["pruned_chars_total"]) > 0


# ---------------------------------------------------------------------------
# _build_prompt — schema requirements
# ---------------------------------------------------------------------------


def test_build_prompt_includes_required_schema_headers(config, event_bus, issue):
    """The updated prompt should mention all 7 required section headers."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "## Files to Modify" in prompt
    assert "## New Files" in prompt
    assert "## File Delta" in prompt
    assert "## Implementation Steps" in prompt
    assert "## Testing Strategy" in prompt
    assert "## Acceptance Criteria" in prompt
    assert "## Key Considerations" in prompt
    assert "REQUIRED SCHEMA" in prompt


def test_build_prompt_warns_about_rejection(config, event_bus, issue):
    """The prompt should warn that plans with missing sections will be rejected."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)

    assert "rejected" in prompt.lower()


# ---------------------------------------------------------------------------
# REQUIRED_SECTIONS constant
# ---------------------------------------------------------------------------


def test_required_sections_has_seven_entries(config, event_bus):
    """PlannerRunner.REQUIRED_SECTIONS should have 7 entries (including File Delta)."""
    assert len(PlannerRunner.REQUIRED_SECTIONS) == 7
    assert "## Files to Modify" in PlannerRunner.REQUIRED_SECTIONS
    assert "## New Files" in PlannerRunner.REQUIRED_SECTIONS
    assert "## File Delta" in PlannerRunner.REQUIRED_SECTIONS
    assert "## Implementation Steps" in PlannerRunner.REQUIRED_SECTIONS
    assert "## Testing Strategy" in PlannerRunner.REQUIRED_SECTIONS
    assert "## Acceptance Criteria" in PlannerRunner.REQUIRED_SECTIONS
    assert "## Key Considerations" in PlannerRunner.REQUIRED_SECTIONS


# ---------------------------------------------------------------------------
# [NEEDS CLARIFICATION] markers
# ---------------------------------------------------------------------------


def test_validate_plan_accepts_three_clarification_markers(config, event_bus):
    """Plans with 0-3 [NEEDS CLARIFICATION] markers are acceptable."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix authentication handler")
    plan = _valid_plan() + (
        "\n[NEEDS CLARIFICATION: unclear if OAuth or JWT]\n"
        "[NEEDS CLARIFICATION: which database?]\n"
        "[NEEDS CLARIFICATION: migration strategy?]\n"
    )
    errors = runner._validate_plan(task, plan)
    assert not any("NEEDS CLARIFICATION" in e for e in errors)


def test_validate_plan_rejects_four_clarification_markers(config, event_bus):
    """Plans with 4+ [NEEDS CLARIFICATION] markers escalate."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix authentication handler")
    plan = _valid_plan() + (
        "\n[NEEDS CLARIFICATION: unclear if OAuth or JWT]\n"
        "[NEEDS CLARIFICATION: which database?]\n"
        "[NEEDS CLARIFICATION: migration strategy?]\n"
        "[NEEDS CLARIFICATION: backward compat?]\n"
    )
    errors = runner._validate_plan(task, plan)
    assert any("NEEDS CLARIFICATION" in e for e in errors)
    assert any("4" in e for e in errors if "NEEDS CLARIFICATION" in e)


def test_validate_plan_zero_clarification_markers_ok(config, event_bus):
    """Plans with no [NEEDS CLARIFICATION] markers pass."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix authentication handler")
    errors = runner._validate_plan(task, _valid_plan())
    assert not any("NEEDS CLARIFICATION" in e for e in errors)


# ---------------------------------------------------------------------------
# _build_prompt — [NEEDS CLARIFICATION] instruction
# ---------------------------------------------------------------------------


def test_build_prompt_includes_clarification_instruction(config, event_bus, issue):
    """Prompt should instruct the planner about [NEEDS CLARIFICATION] markers."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task)
    assert "NEEDS CLARIFICATION" in prompt


def test_build_retry_prompt_includes_clarification_instruction(
    config, event_bus, issue
):
    """Retry prompt should also mention [NEEDS CLARIFICATION] markers."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt, _stats = runner._build_retry_prompt(task, "failed plan", ["some error"])
    assert "NEEDS CLARIFICATION" in prompt


# ---------------------------------------------------------------------------
# Scale detection
# ---------------------------------------------------------------------------


def test_detect_plan_scale_lite_by_label(config, event_bus):
    """Issues with a lite-plan tag (e.g. 'bug') get a lite plan."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix crash", tags=["bug"])
    assert runner._detect_plan_scale(task) == "lite"


def test_detect_plan_scale_lite_label_case_insensitive(config, event_bus):
    """Tag matching is case-insensitive."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix typo", tags=["BUG"])
    assert runner._detect_plan_scale(task) == "lite"


def test_detect_plan_scale_lite_by_short_body_and_title(config, event_bus):
    """Short body + small-fix title keyword → lite plan."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix typo in README", body="Small change needed.", tags=[])
    assert runner._detect_plan_scale(task) == "lite"


def test_detect_plan_scale_full_by_default(config, event_bus):
    """Issues without lite tags or short body default to full plan."""
    runner = _make_runner(config, event_bus)
    task = Task(
        id=1,
        title="Add authentication system",
        body="A" * 600,
        tags=["feature"],
    )
    assert runner._detect_plan_scale(task) == "full"


def test_detect_plan_scale_short_body_but_no_fix_keyword(config, event_bus):
    """Short body without small-fix keyword in title → full plan."""
    runner = _make_runner(config, event_bus)
    task = Task(
        id=1,
        title="Implement new auth system",
        body="Short body",
        tags=[],
    )
    assert runner._detect_plan_scale(task) == "full"


def test_detect_plan_scale_custom_lite_labels(event_bus, tmp_path):
    """Custom lite_plan_labels config is respected."""
    cfg = ConfigFactory.create(
        lite_plan_labels=["hotfix", "patch"],
        repo_root=tmp_path,
    )
    runner = _make_runner(cfg, event_bus)
    task = Task(id=1, title="Critical fix", tags=["hotfix"])
    assert runner._detect_plan_scale(task) == "lite"

    task2 = Task(id=2, title="Add authentication", tags=["bug"])
    assert runner._detect_plan_scale(task2) == "full"


# ---------------------------------------------------------------------------
# Lite plan validation
# ---------------------------------------------------------------------------


def _lite_plan() -> str:
    """Return a plan with only lite-required sections."""
    return (
        "## Files to Modify\n\n"
        "- src/app.py — fix the crash\n\n"
        "## Implementation Steps\n\n"
        "1. Identify the root cause in app.py\n"
        "2. Apply the fix to the affected function\n"
        "3. Add error handling for edge case\n\n"
        "## Testing Strategy\n\n"
        "- Add tests/test_app.py for the crash scenario\n"
    )


def test_validate_lite_plan_accepts_three_sections(config, event_bus):
    """A lite plan with only 3 sections passes validation."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix crash")
    errors = runner._validate_plan(task, _lite_plan(), scale="lite")
    assert errors == []


def test_validate_lite_plan_no_minimum_word_count(config, event_bus):
    """Lite plans skip the minimum word count check."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix crash")
    # _lite_plan() is well under 200 words
    errors = runner._validate_plan(task, _lite_plan(), scale="lite")
    assert not any("words" in e for e in errors)


def test_validate_lite_plan_rejects_missing_required_section(config, event_bus):
    """Lite plan missing a required section (e.g. Testing Strategy) is rejected."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix crash")
    plan = _lite_plan().replace("## Testing Strategy", "## Tests")
    errors = runner._validate_plan(task, plan, scale="lite")
    assert any("Testing Strategy" in e for e in errors)


def test_validate_full_plan_rejects_lite_sections_only(config, event_bus):
    """A full plan with only 3 sections fails (missing Acceptance Criteria etc.)."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Add feature")
    errors = runner._validate_plan(task, _lite_plan(), scale="full")
    missing = [e for e in errors if "Missing required section" in e]
    assert (
        len(missing) >= 3
    )  # Missing New Files, Acceptance Criteria, Key Considerations


# ---------------------------------------------------------------------------
# Lite plan — Phase -1 gates skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lite_plan_skips_phase_minus_one_gates(config, event_bus):
    """Lite plan issues should not run Phase -1 gates."""
    runner = _make_runner(config, event_bus)
    task = Task(id=1, title="Fix typo", tags=["bug"])

    lite_transcript = f"PLAN_START\n{_lite_plan()}\nPLAN_END\nSUMMARY: Fix the crash"

    with (
        patch.object(runner, "_execute", AsyncMock(return_value=lite_transcript)),
        patch.object(runner, "_save_transcript"),
        patch.object(runner, "_run_phase_minus_one_gates") as mock_gates,
    ):
        result = await runner.plan(task, worker_id=0)

    assert result.success is True
    mock_gates.assert_not_called()


# ---------------------------------------------------------------------------
# Pre-mortem prompt
# ---------------------------------------------------------------------------


def test_build_prompt_includes_pre_mortem_for_full(config, event_bus, issue):
    """Full plan prompt includes the pre-mortem section."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task, scale="full")
    assert "pre-mortem" in prompt.lower()
    assert "top 3 most likely reasons" in prompt.lower()


def test_build_prompt_no_pre_mortem_for_lite(config, event_bus, issue):
    """Lite plan prompt does NOT include the pre-mortem section."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt = runner._build_prompt(task, scale="lite")
    assert "pre-mortem" not in prompt.lower()


def test_build_prompt_indicates_plan_mode(config, event_bus, issue):
    """Prompt indicates the plan mode (LITE or FULL)."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()

    full_prompt = runner._build_prompt(task, scale="full")
    assert "FULL" in full_prompt

    lite_prompt = runner._build_prompt(task, scale="lite")
    assert "LITE" in lite_prompt


# ---------------------------------------------------------------------------
# Lite plan retry prompt
# ---------------------------------------------------------------------------


def test_build_retry_prompt_lite_has_fewer_sections(config, event_bus, issue):
    """Retry prompt for lite plan only lists 3 required sections."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt, _stats = runner._build_retry_prompt(
        task, "failed plan", ["some error"], scale="lite"
    )
    assert "## Files to Modify" in prompt
    assert "## Implementation Steps" in prompt
    assert "## Testing Strategy" in prompt
    assert "## Acceptance Criteria" not in prompt
    assert "## Key Considerations" not in prompt


def test_build_retry_prompt_full_has_all_sections(config, event_bus, issue):
    """Retry prompt for full plan lists all 7 required sections."""
    runner = _make_runner(config, event_bus)
    task = issue.to_task()
    prompt, _stats = runner._build_retry_prompt(
        task, "failed plan", ["some error"], scale="full"
    )
    assert "## Files to Modify" in prompt
    assert "## Acceptance Criteria" in prompt
    assert "## Key Considerations" in prompt


# ---------------------------------------------------------------------------
# Section descriptions constant — drift guard
# ---------------------------------------------------------------------------


def test_section_descriptions_cover_all_required_sections():
    """Every header in REQUIRED_SECTIONS has a corresponding entry in _PLAN_SECTION_DESCRIPTIONS."""
    from planner import _PLAN_SECTION_DESCRIPTIONS

    desc_headers = {h for h, _ in _PLAN_SECTION_DESCRIPTIONS}
    for header in PlannerRunner.REQUIRED_SECTIONS:
        assert header in desc_headers, (
            f"{header} missing from _PLAN_SECTION_DESCRIPTIONS"
        )


def test_section_descriptions_cover_all_lite_sections():
    """Every header in LITE_REQUIRED_SECTIONS has a corresponding entry in _PLAN_SECTION_DESCRIPTIONS."""
    from planner import _PLAN_SECTION_DESCRIPTIONS

    desc_headers = {h for h, _ in _PLAN_SECTION_DESCRIPTIONS}
    for header in PlannerRunner.LITE_REQUIRED_SECTIONS:
        assert header in desc_headers, (
            f"{header} missing from _PLAN_SECTION_DESCRIPTIONS"
        )


def test_format_sections_list_full_has_all_sections():
    """_format_sections_list('full') includes all required section headers."""
    result = PlannerRunner._format_sections_list("full")
    for header in PlannerRunner.REQUIRED_SECTIONS:
        assert header in result, f"{header} missing from full sections list"


def test_format_sections_list_lite_has_only_three_sections():
    """_format_sections_list('lite') includes only the 3 lite-required headers."""
    result = PlannerRunner._format_sections_list("lite")
    for header in PlannerRunner.LITE_REQUIRED_SECTIONS:
        assert header in result, f"{header} missing from lite sections list"

    # Full-only headers should be absent
    full_only = set(PlannerRunner.REQUIRED_SECTIONS) - set(
        PlannerRunner.LITE_REQUIRED_SECTIONS
    )
    for header in full_only:
        assert header not in result, f"{header} should not be in lite sections list"


# ---------------------------------------------------------------------------
# validate_already_satisfied_evidence
# ---------------------------------------------------------------------------


class TestValidateAlreadySatisfiedEvidence:
    """Tests for PlannerRunner.validate_already_satisfied_evidence()."""

    def test_valid_evidence_returns_empty_errors(self) -> None:
        summary = (
            "Evidence:\n"
            "- Feature: MyClass at src/models.py:42 implements this\n"
            "- Tests: test_my_class verifies the behavior\n"
            "- Criteria: All acceptance criteria are met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert errors == []

    def test_empty_input_returns_error(self) -> None:
        errors = PlannerRunner.validate_already_satisfied_evidence("")
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_whitespace_only_input_returns_error(self) -> None:
        errors = PlannerRunner.validate_already_satisfied_evidence("   \n  ")
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_missing_feature_field(self) -> None:
        summary = "Tests: test_my_class\nCriteria: All criteria met"
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("Feature" in e for e in errors)

    def test_missing_tests_field(self) -> None:
        summary = "Feature: MyClass at src/models.py:42\nCriteria: All criteria met"
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("Tests" in e for e in errors)

    def test_missing_criteria_field(self) -> None:
        summary = "Feature: MyClass at src/models.py:42\nTests: test_my_class"
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("Criteria" in e for e in errors)

    def test_feature_without_file_line_ref(self) -> None:
        summary = (
            "Feature: MyClass implements this\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("file:line" in e.lower() for e in errors)

    def test_all_fields_missing(self) -> None:
        summary = "The feature already exists and is working."
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert len(errors) >= 3  # Feature, Tests, Criteria all missing

    def test_feature_field_with_description_colon_but_no_file_ref_fails(self) -> None:
        """A Feature field with a colon but no file:line ref should fail."""
        summary = (
            "Feature: some description of the feature\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("file:line" in e.lower() for e in errors)

    def test_feature_field_with_valid_file_line_passes(self) -> None:
        """A Feature field with a valid file:line reference should pass."""
        summary = (
            "Feature: MyClass at src/foo.py:42 handles this\n"
            "Tests: test_foo verifies it\n"
            "Criteria: All criteria met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert errors == []

    def test_feature_field_with_url_colon_fails(self) -> None:
        """A Feature field with a URL (has colon but no file:line) should fail."""
        summary = (
            "Feature: see http://example.com for details\n"
            "Tests: test_example\n"
            "Criteria: All criteria met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("file:line" in e.lower() for e in errors)

    def test_feature_field_with_url_port_fails(self) -> None:
        """A URL with a port (e.g. :8080) should NOT pass as a file:line ref."""
        summary = (
            "Feature: see http://example.com:8080 for details\n"
            "Tests: test_example\n"
            "Criteria: All criteria met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert any("file:line" in e.lower() for e in errors)

    def test_multiple_file_refs_all_valid(self) -> None:
        """Multiple file:line references should all pass."""
        summary = (
            "Feature: implemented in src/models.py:10 and src/config.py:20\n"
            "Tests: test_models and test_config\n"
            "Criteria: All criteria met"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(summary)
        assert errors == []

    def test_rejects_when_issue_has_many_acceptance_criteria(self) -> None:
        """Issues with 5+ unchecked criteria are too complex for 'already satisfied'."""
        summary = (
            "Feature: MyClass at src/models.py:42\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        issue_body = (
            "## Acceptance Criteria\n\n"
            "- [ ] First criterion\n"
            "- [ ] Second criterion\n"
            "- [ ] Third criterion\n"
            "- [ ] Fourth criterion\n"
            "- [ ] Fifth criterion\n"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(
            summary, issue_body=issue_body
        )
        assert any("acceptance criteria" in e.lower() for e in errors)

    def test_accepts_when_few_acceptance_criteria(self) -> None:
        """Issues with <5 criteria should pass the criteria count check."""
        summary = (
            "Feature: MyClass at src/models.py:42\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        issue_body = (
            "## Acceptance Criteria\n\n- [ ] First criterion\n- [ ] Second criterion\n"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(
            summary, issue_body=issue_body
        )
        assert errors == []

    def test_rejects_when_new_files_do_not_exist(self, tmp_path) -> None:
        """Already-satisfied claim is invalid when issue describes new files that don't exist."""
        summary = (
            "Feature: MyClass at src/models.py:42\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        issue_body = (
            "## New Files\n\n- `src/new_feature.py`\n- `tests/test_new_feature.py`\n"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(
            summary, issue_body=issue_body, repo_root=tmp_path
        )
        assert any("do not exist" in e for e in errors)

    def test_accepts_when_new_files_exist(self, tmp_path) -> None:
        """No error when described new files actually exist on disk."""
        summary = (
            "Feature: MyClass at src/models.py:42\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "existing.py").write_text("# exists")
        issue_body = "## New Files\n\n- `src/existing.py`\n"
        errors = PlannerRunner.validate_already_satisfied_evidence(
            summary, issue_body=issue_body, repo_root=tmp_path
        )
        assert errors == []

    def test_rejects_file_delta_added_lines(self, tmp_path) -> None:
        """ADDED: lines in File Delta should be checked for existence."""
        summary = (
            "Feature: MyClass at src/models.py:42\n"
            "Tests: test_my_class\n"
            "Criteria: All criteria met"
        )
        issue_body = (
            "## File Delta\n\n"
            "```\n"
            "MODIFIED: src/config.py\n"
            "ADDED: src/brand_new.py\n"
            "ADDED: tests/test_brand_new.py\n"
            "```\n"
        )
        errors = PlannerRunner.validate_already_satisfied_evidence(
            summary, issue_body=issue_body, repo_root=tmp_path
        )
        assert any("do not exist" in e for e in errors)
