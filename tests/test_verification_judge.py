"""Tests for verification_judge.py — VerificationJudge class."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus, EventType
from models import (
    CriterionResult,
    CriterionVerdict,
    InstructionsQuality,
    JudgeVerdict,
)
from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory
from tests.helpers import ConfigFactory
from verification_judge import VerificationJudge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CRITERIA_FILE = """\
# Verification — Issue #42

## Acceptance Criteria

- [ ] Button renders correctly in the sidebar
- [ ] API endpoint returns 200 with correct schema
- [x] Edge case for empty input is handled

## Verification Instructions

1. Open the sidebar and click the new button
2. Verify the button has the correct label "Submit"
3. Send a GET request to /api/items and verify 200 response
4. Submit an empty form and verify error message appears

## Notes

Some additional notes here.
"""

SAMPLE_CODE_VALIDATION_TRANSCRIPT = """\
Looking at the diff...

CRITERIA_RESULTS_START
AC-1: PASS — Button component renders in sidebar, covered by test_sidebar.py::test_render
AC-2: FAIL — No test for API endpoint schema validation
AC-3: PASS — Empty input handling added in form_handler.py with test coverage
CRITERIA_RESULTS_END

SUMMARY: 2 of 3 criteria passed, API schema test missing.
"""

SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT = """\
The verification instructions are clear and actionable.

INSTRUCTIONS_QUALITY: READY
"""

SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT = """\
Several issues found with the instructions.

INSTRUCTIONS_QUALITY: NEEDS_REFINEMENT
INSTRUCTIONS_FEEDBACK: Step 2 does not specify which page. Step 4 is ambiguous about expected error message.
"""

SAMPLE_REFINEMENT_TRANSCRIPT = """\
Here are the refined instructions:

REFINED_INSTRUCTIONS_START
1. Navigate to /dashboard and open the sidebar panel
2. Click the "Submit" button in the sidebar — it should have blue styling
3. Open a terminal and run: curl -s http://localhost:8000/api/items | jq .
4. Verify the response has status 200 and contains an "items" array
5. On the /dashboard page, submit the form with all fields empty
6. Verify a red error banner appears with text "All fields are required"
REFINED_INSTRUCTIONS_END
"""


def _make_judge(config=None, event_bus=None):
    cfg = config or ConfigFactory.create()
    bus = event_bus or EventBus()
    return VerificationJudge(config=cfg, event_bus=bus)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_criterion_verdict_values(self):
        assert CriterionVerdict.PASS == "pass"
        assert CriterionVerdict.FAIL == "fail"

    def test_instructions_quality_values(self):
        assert InstructionsQuality.READY == "ready"
        assert InstructionsQuality.NEEDS_REFINEMENT == "needs_refinement"

    def test_judge_verdict_defaults(self):
        v = JudgeVerdict(issue_number=42)
        assert v.issue_number == 42
        assert v.criteria_results == []
        assert v.all_criteria_pass is False
        assert v.instructions_quality == InstructionsQuality.NEEDS_REFINEMENT
        assert v.instructions_feedback == ""
        assert v.refined is False
        assert v.summary == ""

    def test_criterion_result_defaults(self):
        cr = CriterionResult(criterion="AC-1")
        assert cr.verdict == CriterionVerdict.FAIL
        assert cr.reasoning == ""


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_uses_review_model(self, config):
        judge = _make_judge(config)
        cmd = judge._build_command()
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == config.review_model

    def test_includes_read_only_tools(self, config):
        judge = _make_judge(config)
        cmd = judge._build_command()
        assert "--disallowedTools" in cmd
        idx = cmd.index("--disallowedTools")
        assert "Write" in cmd[idx + 1]
        assert "Edit" in cmd[idx + 1]
        assert "NotebookEdit" in cmd[idx + 1]

    def test_includes_stream_json_output(self, config):
        judge = _make_judge(config)
        cmd = judge._build_command()
        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "stream-json"

    def test_supports_codex_backend(self, tmp_path):
        cfg = ConfigFactory.create(
            verification_judge_tool="codex",
            review_model="gpt-5-codex",
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        judge = _make_judge(cfg)
        cmd = judge._build_command()
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# _read_criteria_file
# ---------------------------------------------------------------------------


class TestReadCriteriaFile:
    def test_returns_content_when_exists(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        criteria_file = criteria_dir / "issue-42.md"
        criteria_file.write_text(SAMPLE_CRITERIA_FILE)

        result = judge._read_criteria_file(42)
        assert result == SAMPLE_CRITERIA_FILE

    def test_returns_none_when_missing(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)

        result = judge._read_criteria_file(42)
        assert result is None

    def test_returns_none_on_oserror(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        criteria_file = criteria_dir / "issue-42.md"
        criteria_file.write_text("content")

        with patch.object(Path, "read_text", side_effect=OSError("read error")):
            result = judge._read_criteria_file(42)

        assert result is None


# ---------------------------------------------------------------------------
# _parse_criteria
# ---------------------------------------------------------------------------


class TestParseCriteria:
    def test_extracts_checkbox_items(self):
        judge = _make_judge()
        criteria, _ = judge._parse_criteria(SAMPLE_CRITERIA_FILE)
        assert len(criteria) == 3
        assert "Button renders correctly in the sidebar" in criteria[0]
        assert "API endpoint returns 200 with correct schema" in criteria[1]
        assert "Edge case for empty input is handled" in criteria[2]

    def test_extracts_instructions_section(self):
        judge = _make_judge()
        _, instructions = judge._parse_criteria(SAMPLE_CRITERIA_FILE)
        assert "Open the sidebar" in instructions
        assert "Verify the button" in instructions
        assert "GET request" in instructions

    def test_handles_empty_text(self):
        judge = _make_judge()
        criteria, instructions = judge._parse_criteria("")
        assert criteria == []
        assert instructions == ""

    def test_handles_no_criteria_section(self):
        judge = _make_judge()
        text = "# Just a heading\n\nSome text without criteria."
        criteria, instructions = judge._parse_criteria(text)
        assert criteria == []

    def test_handles_no_instructions_section(self):
        judge = _make_judge()
        text = "## Acceptance Criteria\n\n- [ ] First thing\n- [ ] Second thing"
        criteria, instructions = judge._parse_criteria(text)
        assert len(criteria) == 2
        assert instructions == ""

    def test_instructions_stop_at_next_heading(self):
        judge = _make_judge()
        _, instructions = judge._parse_criteria(SAMPLE_CRITERIA_FILE)
        # "Notes" section content should NOT be in instructions
        assert "additional notes" not in instructions

    def test_ignores_checkboxes_outside_criteria_section(self):
        judge = _make_judge()
        text = (
            "## Acceptance Criteria\n\n"
            "- [ ] Real criterion\n\n"
            "## Notes\n\n"
            "- [ ] This is a note checkbox, not a criterion\n"
        )
        criteria, _ = judge._parse_criteria(text)
        assert len(criteria) == 1
        assert "Real criterion" in criteria[0]


# ---------------------------------------------------------------------------
# _build_code_validation_prompt
# ---------------------------------------------------------------------------


class TestBuildCodeValidationPrompt:
    def test_includes_criteria(self, config):
        judge = _make_judge(config)
        criteria = ["Button renders", "API returns 200"]
        prompt = judge._build_code_validation_prompt(criteria, "diff content", 42)
        assert "AC-1: Button renders" in prompt
        assert "AC-2: API returns 200" in prompt

    def test_build_code_validation_prompt_includes_diff(self, config):
        judge = _make_judge(config)
        diff = "diff --git a/foo.py\n+added line"
        prompt = judge._build_code_validation_prompt(["criterion"], diff, 42)
        assert diff in prompt

    def test_includes_output_markers(self, config):
        judge = _make_judge(config)
        prompt = judge._build_code_validation_prompt(["c1"], "diff", 42)
        assert "CRITERIA_RESULTS_START" in prompt
        assert "CRITERIA_RESULTS_END" in prompt

    def test_truncates_long_diff(self, tmp_path):
        cfg = ConfigFactory.create(
            max_review_diff_chars=1_000,
            repo_root=tmp_path,
        )
        judge = _make_judge(cfg)
        long_diff = "x" * 2_000
        prompt = judge._build_code_validation_prompt(["c1"], long_diff, 42)
        assert "x" * 2_000 not in prompt
        assert "Diff truncated" in prompt

    def test_includes_issue_number(self, config):
        judge = _make_judge(config)
        prompt = judge._build_code_validation_prompt(["c1"], "diff", 99)
        assert "#99" in prompt


# ---------------------------------------------------------------------------
# _build_instructions_validation_prompt
# ---------------------------------------------------------------------------


class TestBuildInstructionsValidationPrompt:
    def test_includes_instructions(self, config):
        judge = _make_judge(config)
        prompt = judge._build_instructions_validation_prompt("Click the button", 42)
        assert "Click the button" in prompt

    def test_includes_quality_markers(self, config):
        judge = _make_judge(config)
        prompt = judge._build_instructions_validation_prompt("steps", 42)
        assert "INSTRUCTIONS_QUALITY" in prompt
        assert "READY" in prompt
        assert "NEEDS_REFINEMENT" in prompt

    def test_includes_evaluation_criteria(self, config):
        judge = _make_judge(config)
        prompt = judge._build_instructions_validation_prompt("steps", 42)
        assert "Specific" in prompt or "specific" in prompt.lower()
        assert "expected outcomes" in prompt.lower() or "expected" in prompt.lower()


# ---------------------------------------------------------------------------
# _build_refinement_prompt
# ---------------------------------------------------------------------------


class TestBuildRefinementPrompt:
    def test_includes_original_instructions(self, config):
        judge = _make_judge(config)
        prompt = judge._build_refinement_prompt("Original steps", "too vague", 42)
        assert "Original steps" in prompt

    def test_includes_feedback(self, config):
        judge = _make_judge(config)
        prompt = judge._build_refinement_prompt("steps", "Step 2 is vague", 42)
        assert "Step 2 is vague" in prompt

    def test_includes_refinement_markers(self, config):
        judge = _make_judge(config)
        prompt = judge._build_refinement_prompt("steps", "feedback", 42)
        assert "REFINED_INSTRUCTIONS_START" in prompt
        assert "REFINED_INSTRUCTIONS_END" in prompt


# ---------------------------------------------------------------------------
# _parse_criteria_results
# ---------------------------------------------------------------------------


class TestParseCriteriaResults:
    def test_parses_pass_and_fail(self):
        judge = _make_judge()
        results = judge._parse_criteria_results(SAMPLE_CODE_VALIDATION_TRANSCRIPT)
        assert len(results) == 3
        assert results[0].criterion == "AC-1"
        assert results[0].verdict == CriterionVerdict.PASS
        assert (
            "sidebar" in results[0].reasoning.lower()
            or "Button" in results[0].reasoning
        )
        assert results[1].criterion == "AC-2"
        assert results[1].verdict == CriterionVerdict.FAIL
        assert results[2].criterion == "AC-3"
        assert results[2].verdict == CriterionVerdict.PASS

    def test_no_markers_returns_empty(self):
        judge = _make_judge()
        results = judge._parse_criteria_results("No structured output here.")
        assert results == []

    def test_handles_single_dash_separator(self):
        judge = _make_judge()
        transcript = (
            "CRITERIA_RESULTS_START\n"
            "AC-1: PASS - Button works fine\n"
            "CRITERIA_RESULTS_END"
        )
        results = judge._parse_criteria_results(transcript)
        assert len(results) == 1
        assert results[0].verdict == CriterionVerdict.PASS

    def test_case_insensitive_verdicts(self):
        judge = _make_judge()
        transcript = (
            "CRITERIA_RESULTS_START\n"
            "AC-1: pass — works\n"
            "AC-2: FAIL — broken\n"
            "CRITERIA_RESULTS_END"
        )
        results = judge._parse_criteria_results(transcript)
        assert len(results) == 2
        assert results[0].verdict == CriterionVerdict.PASS
        assert results[1].verdict == CriterionVerdict.FAIL


# ---------------------------------------------------------------------------
# _parse_instructions_quality
# ---------------------------------------------------------------------------


class TestParseInstructionsQuality:
    def test_parse_instructions_quality_detects_ready_status(self):
        judge = _make_judge()
        quality, feedback = judge._parse_instructions_quality(
            SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT
        )
        assert quality == InstructionsQuality.READY
        assert feedback == ""

    def test_parses_needs_refinement_with_feedback(self):
        judge = _make_judge()
        quality, feedback = judge._parse_instructions_quality(
            SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT
        )
        assert quality == InstructionsQuality.NEEDS_REFINEMENT
        assert "Step 2" in feedback

    def test_no_match_defaults_to_needs_refinement(self):
        judge = _make_judge()
        quality, feedback = judge._parse_instructions_quality("No verdict here.")
        assert quality == InstructionsQuality.NEEDS_REFINEMENT
        assert feedback == ""

    def test_captures_multi_paragraph_feedback(self):
        judge = _make_judge()
        transcript = (
            "INSTRUCTIONS_QUALITY: NEEDS_REFINEMENT\n"
            "INSTRUCTIONS_FEEDBACK: Step 2 is vague.\n"
            "\n"
            "Step 4 needs more detail about expected output."
        )
        quality, feedback = judge._parse_instructions_quality(transcript)
        assert quality == InstructionsQuality.NEEDS_REFINEMENT
        assert "Step 2" in feedback
        assert "Step 4" in feedback


# ---------------------------------------------------------------------------
# _extract_refined_instructions
# ---------------------------------------------------------------------------


class TestExtractRefinedInstructions:
    def test_extracts_between_markers(self):
        judge = _make_judge()
        result = judge._extract_refined_instructions(SAMPLE_REFINEMENT_TRANSCRIPT)
        assert "Navigate to /dashboard" in result
        assert "red error banner" in result

    def test_returns_empty_when_no_markers(self):
        judge = _make_judge()
        result = judge._extract_refined_instructions("No markers here.")
        assert result == ""


# ---------------------------------------------------------------------------
# _save_judge_report
# ---------------------------------------------------------------------------


class TestSaveJudgeReport:
    def test_creates_directory_and_file(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        verdict = JudgeVerdict(
            issue_number=42,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Works fine",
                ),
            ],
            all_criteria_pass=True,
            instructions_quality=InstructionsQuality.READY,
            summary="All good",
        )

        judge._save_judge_report(42, verdict)

        path = tmp_path / ".hydraflow" / "verification" / "issue-42-judge.md"
        assert path.exists()
        content = path.read_text()
        assert "Issue #42" in content
        assert "AC-1" in content
        assert "PASS" in content

    def test_formats_criteria_table(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        verdict = JudgeVerdict(
            issue_number=7,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="OK",
                ),
                CriterionResult(
                    criterion="AC-2",
                    verdict=CriterionVerdict.FAIL,
                    reasoning="Missing test",
                ),
            ],
        )

        judge._save_judge_report(7, verdict)

        path = tmp_path / ".hydraflow" / "verification" / "issue-7-judge.md"
        content = path.read_text()
        assert "| AC-1 | PASS |" in content
        assert "| AC-2 | FAIL |" in content
        assert "1/2 criteria passed" in content

    def test_includes_instructions_quality(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        verdict = JudgeVerdict(
            issue_number=5,
            instructions_quality=InstructionsQuality.NEEDS_REFINEMENT,
            instructions_feedback="Steps are vague",
            refined=True,
        )

        judge._save_judge_report(5, verdict)

        path = tmp_path / ".hydraflow" / "verification" / "issue-5-judge.md"
        content = path.read_text()
        assert "needs_refinement" in content
        assert "Steps are vague" in content
        assert "refined" in content.lower()

    def test_save_judge_report_handles_oserror_gracefully(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        verdict = JudgeVerdict(issue_number=42, summary="All good")

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            judge._save_judge_report(42, verdict)  # should not raise


# ---------------------------------------------------------------------------
# _format_judge_report
# ---------------------------------------------------------------------------


class TestFormatJudgeReport:
    def test_format_judge_report_handles_no_criteria(self):
        judge = _make_judge()
        verdict = JudgeVerdict(issue_number=1)
        report = judge._format_judge_report(verdict)
        assert "No criteria evaluated" in report
        assert "0/0 criteria passed" in report

    def test_includes_summary(self):
        judge = _make_judge()
        verdict = JudgeVerdict(issue_number=1, summary="All good")
        report = judge._format_judge_report(verdict)
        assert "All good" in report

    def test_escapes_pipe_in_reasoning(self):
        judge = _make_judge()
        verdict = JudgeVerdict(
            issue_number=1,
            criteria_results=[
                CriterionResult(
                    criterion="AC-1",
                    verdict=CriterionVerdict.PASS,
                    reasoning="Uses curl | jq for parsing",
                ),
            ],
        )
        report = judge._format_judge_report(verdict)
        assert "curl \\| jq" in report

    def test_includes_verification_instructions(self):
        """verification_instructions from verdict appear in the report."""
        judge = _make_judge()
        verdict = JudgeVerdict(
            issue_number=1,
            verification_instructions="1. Open app\n2. Click submit",
        )
        report = judge._format_judge_report(verdict)
        assert "Verification Instructions" in report
        assert "Open app" in report
        assert "Click submit" in report

    def test_omits_verification_instructions_when_empty(self):
        """When verification_instructions is empty, the section is not rendered."""
        judge = _make_judge()
        verdict = JudgeVerdict(issue_number=1)
        report = judge._format_judge_report(verdict)
        assert "Verification Instructions" not in report


# ---------------------------------------------------------------------------
# _update_criteria_file
# ---------------------------------------------------------------------------


class TestUpdateCriteriaFile:
    def test_replaces_instructions_section(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        criteria_file = criteria_dir / "issue-42.md"
        criteria_file.write_text(SAMPLE_CRITERIA_FILE)

        judge._update_criteria_file(42, "New refined instructions here")

        updated = criteria_file.read_text()
        assert "New refined instructions here" in updated
        # Original criteria should still be present
        assert "Acceptance Criteria" in updated
        # Content after the instructions section should be preserved
        assert "## Notes" in updated
        assert "additional notes" in updated
        # Original instructions should be gone
        assert "Open the sidebar" not in updated

    def test_noop_when_file_missing(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        # Should not raise
        judge._update_criteria_file(999, "Refined text")

    def test_appends_instructions_section_when_none_exists(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        criteria_file = criteria_dir / "issue-42.md"
        criteria_file.write_text("## Acceptance Criteria\n\n- [ ] First\n")

        judge._update_criteria_file(42, "New instructions here")

        content = criteria_file.read_text()
        assert "## Verification Instructions" in content
        assert "New instructions here" in content
        assert "Acceptance Criteria" in content

    def test_handles_read_oserror(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        criteria_file = criteria_dir / "issue-42.md"
        criteria_file.write_text(SAMPLE_CRITERIA_FILE)

        with patch.object(Path, "read_text", side_effect=OSError("read error")):
            judge._update_criteria_file(42, "Refined")  # should not raise

    def test_handles_write_oserror(self, tmp_path):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = _make_judge(cfg)
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        criteria_file = criteria_dir / "issue-42.md"
        criteria_file.write_text(SAMPLE_CRITERIA_FILE)

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            judge._update_criteria_file(42, "Refined")  # should not raise


# ---------------------------------------------------------------------------
# judge() — integration tests (async, mocked execution)
# ---------------------------------------------------------------------------


class TestJudgeIntegration:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_criteria_file(self, tmp_path, event_bus):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        result = await judge.judge(issue_number=42, pr_number=101, diff="some diff")
        assert result is None

    @pytest.mark.asyncio
    async def test_dry_run_returns_early(self, tmp_path, event_bus):
        cfg = ConfigFactory.create(dry_run=True, repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        # Create criteria file so we don't skip for missing file
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        result = await judge.judge(issue_number=42, pr_number=101, diff="diff")
        assert result is not None
        assert result.issue_number == 42
        assert result.criteria_results == []

    @pytest.mark.asyncio
    async def test_success_all_pass(self, tmp_path, event_bus):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        # Create criteria file
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        all_pass_transcript = (
            "CRITERIA_RESULTS_START\n"
            "AC-1: PASS — Button renders\n"
            "AC-2: PASS — API works\n"
            "AC-3: PASS — Edge case handled\n"
            "CRITERIA_RESULTS_END\n"
            "SUMMARY: All pass"
        )

        call_count = 0

        async def mock_execute(cmd, prompt, issue_number):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return all_pass_transcript
            return SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.all_criteria_pass is True
        assert len(result.criteria_results) == 3
        assert result.instructions_quality == InstructionsQuality.READY
        assert result.refined is False

    @pytest.mark.asyncio
    async def test_some_criteria_fail(self, tmp_path, event_bus):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0

        async def mock_execute(cmd, prompt, issue_number):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SAMPLE_CODE_VALIDATION_TRANSCRIPT
            return SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.all_criteria_pass is False
        fail_count = sum(
            1 for cr in result.criteria_results if cr.verdict == CriterionVerdict.FAIL
        )
        assert fail_count == 1

    @pytest.mark.asyncio
    async def test_instructions_refined(self, tmp_path, event_bus):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0

        responses = [
            SAMPLE_CODE_VALIDATION_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT,
            SAMPLE_REFINEMENT_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT,
        ]

        async def mock_execute(cmd, prompt, issue_number):
            nonlocal call_count
            call_count += 1
            return responses[call_count - 1]

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.refined is True
        assert result.instructions_quality == InstructionsQuality.READY
        # Verify 4 LLM calls were made
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_refinement_still_fails(self, tmp_path, event_bus):
        """Max 1 retry — if still NEEDS_REFINEMENT after refinement, accept it."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0

        responses = [
            SAMPLE_CODE_VALIDATION_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT,
            SAMPLE_REFINEMENT_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT,
        ]

        async def mock_execute(cmd, prompt, issue_number):
            nonlocal call_count
            call_count += 1
            return responses[call_count - 1]

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.refined is True
        assert result.instructions_quality == InstructionsQuality.NEEDS_REFINEMENT
        # Should NOT retry again — max 1
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_refined_false_when_extraction_fails(self, tmp_path, event_bus):
        """When refinement extraction returns empty, refined should be False."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0
        # Refinement transcript has no markers — extraction will fail
        empty_refinement = "I tried to refine but here's some text without markers."

        responses = [
            SAMPLE_CODE_VALIDATION_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT,
            empty_refinement,
            SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT,
        ]

        async def mock_execute(cmd, prompt, issue_number):
            nonlocal call_count
            call_count += 1
            return responses[call_count - 1]

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.refined is False

    @pytest.mark.asyncio
    async def test_judge_saves_verification_report_to_disk(self, tmp_path, event_bus):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0

        async def mock_execute(cmd, prompt, issue_number):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SAMPLE_CODE_VALIDATION_TRANSCRIPT
            return SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT

        with patch.object(judge, "_execute", side_effect=mock_execute):
            await judge.judge(issue_number=42, pr_number=101, diff="diff")

        report_path = tmp_path / ".hydraflow" / "verification" / "issue-42-judge.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "Issue #42" in content
        assert "| AC-1 | PASS |" in content
        assert "| AC-2 | FAIL |" in content
        assert "criteria passed" in content
        assert "ready" in content

    @pytest.mark.asyncio
    async def test_judge_publishes_verification_complete_event(
        self, tmp_path, event_bus
    ):
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        async def mock_execute(cmd, prompt, issue_number):
            return SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT

        with patch.object(judge, "_execute", side_effect=mock_execute):
            await judge.judge(issue_number=42, pr_number=101, diff="diff")

        events = event_bus.get_history()
        judge_events = [e for e in events if e.type == EventType.VERIFICATION_JUDGE]
        assert len(judge_events) == 1
        assert judge_events[0].data["issue"] == 42
        assert judge_events[0].data["pr"] == 101

    @pytest.mark.asyncio
    async def test_handles_execution_error(self, tmp_path, event_bus):
        """Execution errors should not crash the judge — partial results returned."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        async def mock_execute(cmd, prompt, issue_number):
            raise RuntimeError("LLM call failed")

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        # Should still return a verdict (with empty results)
        assert result is not None
        assert result.criteria_results == []
        assert result.all_criteria_pass is False

    @pytest.mark.asyncio
    async def test_judge_summary_includes_pass_fail_counts(self, tmp_path, event_bus):
        """verdict.summary should follow the expected format."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0

        async def mock_execute(_cmd, _prompt, _issue_number):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SAMPLE_CODE_VALIDATION_TRANSCRIPT
            return SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert result.summary == "2/3 criteria passed, instructions: ready"

    @pytest.mark.asyncio
    async def test_criteria_file_with_no_instructions(self, tmp_path, event_bus):
        """Should handle criteria files without an instructions section."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_text = "## Acceptance Criteria\n\n- [ ] First\n- [ ] Second\n"
        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(criteria_text)

        all_pass = (
            "CRITERIA_RESULTS_START\n"
            "AC-1: PASS — First works\n"
            "AC-2: PASS — Second works\n"
            "CRITERIA_RESULTS_END\n"
        )

        async def mock_execute(cmd, prompt, issue_number):
            return all_pass

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert len(result.criteria_results) == 2
        # Only 1 LLM call (code validation only, no instructions validation)
        assert result.instructions_quality == InstructionsQuality.NEEDS_REFINEMENT

    @pytest.mark.asyncio
    async def test_verification_instructions_populated(self, tmp_path, event_bus):
        """verdict.verification_instructions should contain the parsed instructions."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0

        async def mock_execute(_cmd, _prompt, _issue_number):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return SAMPLE_CODE_VALIDATION_TRANSCRIPT
            return SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        assert "Open the sidebar" in result.verification_instructions
        assert "Submit an empty form" in result.verification_instructions

    @pytest.mark.asyncio
    async def test_verification_instructions_updated_after_refinement(
        self, tmp_path, event_bus
    ):
        """After refinement, verification_instructions should contain refined text."""
        cfg = ConfigFactory.create(repo_root=tmp_path)
        judge = VerificationJudge(cfg, event_bus)

        criteria_dir = tmp_path / ".hydraflow" / "verification"
        criteria_dir.mkdir(parents=True)
        (criteria_dir / "issue-42.md").write_text(SAMPLE_CRITERIA_FILE)

        call_count = 0
        responses = [
            SAMPLE_CODE_VALIDATION_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_NEEDS_REFINEMENT_TRANSCRIPT,
            SAMPLE_REFINEMENT_TRANSCRIPT,
            SAMPLE_INSTRUCTIONS_READY_TRANSCRIPT,
        ]

        async def mock_execute(_cmd, _prompt, _issue_number):
            nonlocal call_count
            call_count += 1
            return responses[call_count - 1]

        with patch.object(judge, "_execute", side_effect=mock_execute):
            result = await judge.judge(issue_number=42, pr_number=101, diff="diff")

        assert result is not None
        # Should contain the refined instructions, not the original
        assert "Navigate to /dashboard" in result.verification_instructions
        assert "red error banner" in result.verification_instructions


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


class TestTerminate:
    def test_kills_active_processes(self, config):
        judge = _make_judge(config)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        judge._active_procs.add(mock_proc)

        with patch("runner_utils.os.killpg") as mock_killpg:
            judge.terminate()

        mock_killpg.assert_called_once()

    def test_no_active_processes(self, config):
        judge = _make_judge(config)
        judge.terminate()  # Should not raise


# ---------------------------------------------------------------------------
# TestPrecheckHighRiskFiles
# ---------------------------------------------------------------------------


class TestPrecheckDiffPassthrough:
    """Verify _run_precheck_context passes diff to the shared precheck module."""

    @pytest.mark.asyncio
    async def test_passes_diff_to_shared_module(self, tmp_path) -> None:
        cfg = ConfigFactory.create(max_subskill_attempts=1, repo_root=tmp_path)
        judge = VerificationJudge(cfg, EventBus())

        with patch(
            "verification_judge.run_precheck_context",
            new_callable=AsyncMock,
            return_value="Precheck risk: low",
        ) as mock_rpc:
            await judge._run_precheck_context(42, "criteria text", "some diff")

        assert mock_rpc.call_args[1]["diff"] == "some diff"


# ---------------------------------------------------------------------------
# ReviewPhase wiring tests
# ---------------------------------------------------------------------------


class TestReviewPhaseWiring:
    @pytest.mark.asyncio
    async def test_review_phase_runs_judge_after_merge(
        self, config, tmp_path, event_bus
    ):
        """When verification_judge is provided, it should be called after merge."""
        from review_phase import ReviewPhase
        from state import StateTracker

        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()

        mock_wt = AsyncMock()
        mock_wt.destroy = AsyncMock()
        mock_wt.merge_main = AsyncMock(return_value=True)

        mock_reviewers = AsyncMock()
        mock_reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                summary="LGTM",
                transcript="THOROUGH_REVIEW_COMPLETE\nVERDICT: APPROVE",
            )
        )

        mock_prs = AsyncMock()
        mock_prs.get_pr_diff = AsyncMock(return_value="diff text")
        mock_prs.push_branch = AsyncMock()
        mock_prs.merge_pr = AsyncMock(return_value=True)
        mock_prs.remove_label = AsyncMock()
        mock_prs.add_labels = AsyncMock()
        mock_prs.post_pr_comment = AsyncMock()
        mock_prs.submit_review = AsyncMock()

        mock_judge = AsyncMock()
        mock_judge.judge = AsyncMock(return_value=JudgeVerdict(issue_number=42))

        # Create worktree dir
        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        phase = ReviewPhase(
            config=config,
            state=state,
            worktrees=mock_wt,
            reviewers=mock_reviewers,
            prs=mock_prs,
            stop_event=stop_event,
            store=MagicMock(),
            event_bus=event_bus,
        )
        phase._post_merge._verification_judge = mock_judge

        pr = PRInfoFactory.create()
        issue = TaskFactory.create(
            id=42, title="Fix bug", body="Details", tags=["ready"]
        )

        await phase.review_prs([pr], [issue])

        mock_judge.judge.assert_called_once_with(
            issue_number=42,
            pr_number=101,
            diff="diff text",
        )

    @pytest.mark.asyncio
    async def test_review_phase_skips_judge_when_none(
        self, config, tmp_path, event_bus
    ):
        """When verification_judge is None, no judge call should happen."""
        from review_phase import ReviewPhase
        from state import StateTracker

        state = StateTracker(config.state_file)
        stop_event = asyncio.Event()

        mock_wt = AsyncMock()
        mock_wt.destroy = AsyncMock()
        mock_wt.merge_main = AsyncMock(return_value=True)

        mock_reviewers = AsyncMock()
        mock_reviewers.review = AsyncMock(
            return_value=ReviewResultFactory.create(
                summary="LGTM",
                transcript="THOROUGH_REVIEW_COMPLETE\nVERDICT: APPROVE",
            )
        )

        mock_prs = AsyncMock()
        mock_prs.get_pr_diff = AsyncMock(return_value="diff text")
        mock_prs.push_branch = AsyncMock()
        mock_prs.merge_pr = AsyncMock(return_value=True)
        mock_prs.remove_label = AsyncMock()
        mock_prs.add_labels = AsyncMock()
        mock_prs.post_pr_comment = AsyncMock()
        mock_prs.submit_review = AsyncMock()

        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        phase = ReviewPhase(
            config=config,
            state=state,
            worktrees=mock_wt,
            reviewers=mock_reviewers,
            prs=mock_prs,
            stop_event=stop_event,
            store=MagicMock(),
            event_bus=event_bus,
            # No verification_judge
        )

        pr = PRInfoFactory.create()
        issue = TaskFactory.create(
            id=42, title="Fix bug", body="Details", tags=["ready"]
        )

        results = await phase.review_prs([pr], [issue])
        # No crash, no judge call — just verify it completed
        assert len(results) == 1


# ---------------------------------------------------------------------------
# _build_precheck_prompt
# ---------------------------------------------------------------------------


class TestBuildPrecheckPrompt:
    """Tests for VerificationJudge._build_precheck_prompt."""

    def test_includes_criteria_and_diff(self, config) -> None:
        judge = _make_judge(config)
        prompt = judge._build_precheck_prompt(42, "AC-1: Button works", "diff content")
        assert "#42" in prompt
        assert "AC-1: Button works" in prompt
        assert "diff content" in prompt

    def test_truncates_criteria_to_2000_chars(self, config) -> None:
        judge = _make_judge(config)
        long_criteria = "C" * 5000
        prompt = judge._build_precheck_prompt(42, long_criteria, "diff")
        assert "C" * 2000 in prompt
        assert "C" * 2001 not in prompt

    def test_truncates_diff_to_3000_chars(self, config) -> None:
        judge = _make_judge(config)
        long_diff = "D" * 5000
        prompt = judge._build_precheck_prompt(42, "criteria", long_diff)
        assert "D" * 3000 in prompt
        assert "D" * 3001 not in prompt


# ---------------------------------------------------------------------------
# _run_precheck_context (wiring tests — shared logic tested in test_precheck.py)
# ---------------------------------------------------------------------------


class TestRunPrecheckContext:
    """Tests for VerificationJudge._run_precheck_context wiring."""

    @pytest.mark.asyncio
    async def test_delegates_to_shared_run_precheck_context(self, config) -> None:
        """Verify VJ delegates to the shared precheck module."""
        judge = _make_judge(config)

        with patch(
            "verification_judge.run_precheck_context",
            new_callable=AsyncMock,
            return_value="Precheck risk: low",
        ) as mock_rpc:
            result = await judge._run_precheck_context(42, "criteria", "diff")

        mock_rpc.assert_awaited_once()
        assert result == "Precheck risk: low"
        call_kwargs = mock_rpc.call_args[1]
        assert call_kwargs["config"] is judge._config
        assert "ambiguity" in call_kwargs["debug_message"]

    @pytest.mark.asyncio
    async def test_execute_closure_calls_self_execute(self, tmp_path) -> None:
        """Verify the execute closure wires through to self._execute."""
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
        )
        judge = _make_judge(cfg)

        captured_execute = {}

        async def capture_rpc(**kwargs):
            captured_execute["fn"] = kwargs["execute"]
            return "Precheck risk: low"

        with patch(
            "verification_judge.run_precheck_context",
            side_effect=capture_rpc,
        ):
            await judge._run_precheck_context(42, "criteria", "diff")

        # Call the captured execute closure
        mock_self_execute = AsyncMock(return_value="transcript")
        with patch.object(judge, "_execute", mock_self_execute):
            result = await captured_execute["fn"](["cmd"], "prompt")

        assert result == "transcript"
        mock_self_execute.assert_called_once_with(["cmd"], "prompt", 42)


class TestExecuteGhToken:
    """Tests for gh_token propagation in VerificationJudge._execute."""

    @pytest.mark.asyncio
    async def test_execute_passes_gh_token_to_stream(self, tmp_path, event_bus):
        """_execute should pass config.gh_token to stream_claude_process."""
        cfg = ConfigFactory.create(repo_root=tmp_path, gh_token="ghp_bot_judge")
        judge = VerificationJudge(cfg, event_bus)

        with patch(
            "verification_judge.stream_claude_process",
            new_callable=AsyncMock,
            return_value="transcript",
        ) as mock_stream:
            await judge._execute(["claude", "-p"], "prompt", 42)

        assert mock_stream.call_args[1]["gh_token"] == "ghp_bot_judge"
