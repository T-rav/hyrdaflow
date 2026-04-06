"""Tests for plan_compliance module — prompt builder and result parser."""

from __future__ import annotations

from plan_compliance import build_plan_compliance_prompt, parse_plan_compliance_result


class TestBuildPlanCompliancePrompt:
    def test_includes_issue_context(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=42,
            issue_title="Add plan compliance",
            diff="--- a/f\n+++ b/f",
            plan_text="## File Delta\nMODIFIED: src/agent.py",
        )
        assert "#42" in prompt
        assert "Add plan compliance" in prompt

    def test_includes_plan_text(self) -> None:
        plan = "## File Delta\nMODIFIED: src/config.py\nADDED: src/new_feature.py"
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="Test",
            diff="+ some code",
            plan_text=plan,
        )
        assert plan in prompt

    def test_includes_diff(self) -> None:
        diff = "+import os\n-import sys"
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="Test",
            diff=diff,
            plan_text="some plan",
        )
        assert diff in prompt

    def test_includes_structured_output_markers(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
            plan_text="plan",
        )
        assert "PLAN_COMPLIANCE_RESULT: OK" in prompt
        assert "PLAN_COMPLIANCE_RESULT: RETRY" in prompt

    def test_empty_plan_returns_empty_prompt(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
            plan_text="",
        )
        assert prompt == ""

    def test_whitespace_only_plan_returns_empty_prompt(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
            plan_text="   \n  ",
        )
        assert prompt == ""

    def test_default_plan_text_is_empty(self) -> None:
        """plan_text defaults to empty string — auto-pass."""
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
        )
        assert prompt == ""

    def test_mentions_scope_creep(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
            plan_text="plan text here",
        )
        assert "scope creep" in prompt.lower() or "Scope creep" in prompt

    def test_mentions_incomplete_implementation(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
            plan_text="plan text here",
        )
        assert "incomplete" in prompt.lower() or "Incomplete" in prompt

    def test_mentions_test_specs(self) -> None:
        prompt = build_plan_compliance_prompt(
            issue_number=1,
            issue_title="T",
            diff="diff",
            plan_text="plan text here",
        )
        assert "test spec" in prompt.lower() or "test" in prompt.lower()


class TestParsePlanComplianceResult:
    def test_ok_result(self) -> None:
        transcript = (
            "PLAN_COMPLIANCE_RESULT: OK\n"
            "SUMMARY: Implementation matches the plan\n"
            "SCORE: 95"
        )
        passed, summary, findings = parse_plan_compliance_result(transcript)
        assert passed is True
        assert "matches" in summary.lower()
        assert findings == []

    def test_retry_result_with_findings(self) -> None:
        transcript = (
            "PLAN_COMPLIANCE_RESULT: RETRY\n"
            "SUMMARY: scope creep, incomplete implementation\n"
            "SCORE: 60\n"
            "FINDINGS:\n"
            "- src/extra.py — not in plan (scope creep)\n"
            "- src/missing.py — planned but not implemented\n"
        )
        passed, summary, findings = parse_plan_compliance_result(transcript)
        assert passed is False
        assert "scope creep" in summary
        assert len(findings) == 2
        assert "src/extra.py" in findings[0]
        assert "src/missing.py" in findings[1]

    def test_missing_marker_defaults_to_pass(self) -> None:
        passed, summary, findings = parse_plan_compliance_result("no markers here")
        assert passed is True
        assert findings == []

    def test_retry_without_findings_section(self) -> None:
        transcript = "PLAN_COMPLIANCE_RESULT: RETRY\nSUMMARY: incomplete"
        passed, summary, findings = parse_plan_compliance_result(transcript)
        assert passed is False
        assert summary == "incomplete"
        assert findings == []

    def test_case_insensitive_marker(self) -> None:
        transcript = "plan_compliance_result: ok\nsummary: all good"
        passed, summary, _ = parse_plan_compliance_result(transcript)
        assert passed is True
        assert summary == "all good"

    def test_empty_transcript_auto_passes(self) -> None:
        passed, summary, findings = parse_plan_compliance_result("")
        assert passed is True
        assert "skipped" in summary.lower() or "no plan" in summary.lower()
        assert findings == []

    def test_whitespace_only_transcript_auto_passes(self) -> None:
        passed, summary, findings = parse_plan_compliance_result("   \n  ")
        assert passed is True
        assert findings == []

    def test_multiple_findings_parsed(self) -> None:
        transcript = (
            "PLAN_COMPLIANCE_RESULT: RETRY\n"
            "SUMMARY: multiple issues\n"
            "FINDINGS:\n"
            "- file1.py — unplanned\n"
            "- file2.py — missing from diff\n"
            "- test_spec_auth — no corresponding test\n"
        )
        passed, summary, findings = parse_plan_compliance_result(transcript)
        assert passed is False
        assert len(findings) == 3

    def test_ok_with_score(self) -> None:
        transcript = "PLAN_COMPLIANCE_RESULT: OK\nSUMMARY: Full match\nSCORE: 100"
        passed, summary, findings = parse_plan_compliance_result(transcript)
        assert passed is True
        assert summary == "Full match"
