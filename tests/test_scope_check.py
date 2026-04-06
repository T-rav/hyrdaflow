"""Tests for scope_check — plan adherence skill."""

from __future__ import annotations

from scope_check import build_scope_check_prompt, parse_scope_check_result


class TestBuildScopeCheckPrompt:
    """Prompt builder tests."""

    def test_empty_plan_auto_passes(self):
        prompt = build_scope_check_prompt(
            issue_number=1, issue_title="Add feature", diff="+ line", plan_text=""
        )
        assert "SCOPE_CHECK_RESULT: OK" in prompt
        assert "No plan available" in prompt

    def test_whitespace_only_plan_auto_passes(self):
        prompt = build_scope_check_prompt(
            issue_number=1,
            issue_title="Add feature",
            diff="+ line",
            plan_text="   \n  ",
        )
        assert "SCOPE_CHECK_RESULT: OK" in prompt

    def test_plan_with_file_delta(self):
        plan = "## File Delta\nMODIFIED: src/users.py\nADDED: src/pagination.py\n"
        prompt = build_scope_check_prompt(
            issue_number=42, issue_title="Add pagination", diff="+ code", plan_text=plan
        )
        assert "src/users.py" in prompt
        assert "src/pagination.py" in prompt
        assert "#42" in prompt
        assert "SCOPE_CHECK_RESULT: OK|RETRY" in prompt

    def test_includes_diff_in_prompt(self):
        plan = "## File Delta\nMODIFIED: src/foo.py\n"
        diff = "+++ b/src/foo.py\n+ new_line()"
        prompt = build_scope_check_prompt(
            issue_number=10, issue_title="Fix bug", diff=diff, plan_text=plan
        )
        assert "new_line()" in prompt

    def test_no_file_delta_section_shows_none_extracted(self):
        plan = "## Implementation Plan\nDo stuff\n"
        prompt = build_scope_check_prompt(
            issue_number=5, issue_title="Refactor", diff="+ x", plan_text=plan
        )
        assert "_(none extracted)_" in prompt

    def test_includes_classification_rules(self):
        plan = "## File Delta\nMODIFIED: src/a.py\n"
        prompt = build_scope_check_prompt(
            issue_number=1, issue_title="T", diff="+", plan_text=plan
        )
        assert "OK" in prompt
        assert "WARN" in prompt
        assert "FAIL" in prompt

    def test_default_plan_text_is_empty(self):
        """plan_text defaults to empty string when not provided."""
        prompt = build_scope_check_prompt(issue_number=1, issue_title="T", diff="+")
        assert "SCOPE_CHECK_RESULT: OK" in prompt
        assert "No plan available" in prompt


class TestParseScopeCheckResult:
    """Result parser tests."""

    def test_ok_result(self):
        transcript = "SCOPE_CHECK_RESULT: OK\nSUMMARY: All files planned"
        passed, summary, unplanned = parse_scope_check_result(transcript)
        assert passed is True
        assert summary == "All files planned"
        assert unplanned == []

    def test_retry_result(self):
        transcript = (
            "SCOPE_CHECK_RESULT: RETRY\n"
            "SUMMARY: Unrelated scope creep detected\n"
            "UNPLANNED_FILES:\n"
            "- [FAIL] src/auth.py — unrelated module\n"
            "- [OK] tests/test_users.py — test for planned file\n"
        )
        passed, summary, unplanned = parse_scope_check_result(transcript)
        assert passed is False
        assert "scope creep" in summary.lower()
        assert len(unplanned) == 2
        assert "[FAIL] src/auth.py" in unplanned[0]

    def test_no_marker_defaults_to_pass(self):
        passed, summary, unplanned = parse_scope_check_result(
            "No structured output here"
        )
        assert passed is True
        assert unplanned == []

    def test_case_insensitive_marker(self):
        transcript = "scope_check_result: ok\nsummary: fine"
        passed, summary, _ = parse_scope_check_result(transcript)
        assert passed is True

    def test_retry_without_unplanned_files(self):
        transcript = "SCOPE_CHECK_RESULT: RETRY\nSUMMARY: issues found"
        passed, summary, unplanned = parse_scope_check_result(transcript)
        assert passed is False
        assert unplanned == []

    def test_ok_with_warn_files(self):
        transcript = (
            "SCOPE_CHECK_RESULT: OK\n"
            "SUMMARY: Minor side-effects only\n"
            "UNPLANNED_FILES:\n"
            "- [WARN] src/utils.py — shared utility\n"
        )
        passed, summary, unplanned = parse_scope_check_result(transcript)
        assert passed is True
        assert len(unplanned) == 1

    def test_empty_transcript(self):
        passed, summary, unplanned = parse_scope_check_result("")
        assert passed is True
        assert unplanned == []
