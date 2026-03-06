"""Tests for diff_sanity module — prompt builder and result parser."""

from __future__ import annotations

from diff_sanity import build_diff_sanity_prompt, parse_diff_sanity_result


class TestBuildDiffSanityPrompt:
    def test_includes_issue_context(self) -> None:
        prompt = build_diff_sanity_prompt(
            issue_number=42, issue_title="Fix the widget", diff="--- a/f\n+++ b/f"
        )
        assert "#42" in prompt
        assert "Fix the widget" in prompt

    def test_includes_diff(self) -> None:
        diff = "+import os\n-import sys"
        prompt = build_diff_sanity_prompt(issue_number=1, issue_title="T", diff=diff)
        assert diff in prompt

    def test_includes_structured_output_markers(self) -> None:
        prompt = build_diff_sanity_prompt(issue_number=1, issue_title="T", diff="")
        assert "DIFF_SANITY_RESULT: OK" in prompt
        assert "DIFF_SANITY_RESULT: RETRY" in prompt


class TestParseDiffSanityResult:
    def test_ok_result(self) -> None:
        transcript = "DIFF_SANITY_RESULT: OK\nSUMMARY: No issues found"
        passed, summary, findings = parse_diff_sanity_result(transcript)
        assert passed is True
        assert summary == "No issues found"
        assert findings == []

    def test_retry_result_with_findings(self) -> None:
        transcript = (
            "DIFF_SANITY_RESULT: RETRY\n"
            "SUMMARY: debug code, missing imports\n"
            "FINDINGS:\n"
            "- src/agent.py:42 — leftover print()\n"
            "- src/config.py:10 — missing import for Path\n"
        )
        passed, summary, findings = parse_diff_sanity_result(transcript)
        assert passed is False
        assert "debug code" in summary
        assert len(findings) == 2
        assert "leftover print()" in findings[0]

    def test_missing_marker_defaults_to_pass(self) -> None:
        passed, summary, findings = parse_diff_sanity_result("no markers here")
        assert passed is True
        assert findings == []

    def test_retry_without_findings_section(self) -> None:
        transcript = "DIFF_SANITY_RESULT: RETRY\nSUMMARY: scope creep"
        passed, summary, findings = parse_diff_sanity_result(transcript)
        assert passed is False
        assert summary == "scope creep"
        assert findings == []

    def test_case_insensitive_marker(self) -> None:
        transcript = "diff_sanity_result: ok\nsummary: all good"
        passed, summary, _ = parse_diff_sanity_result(transcript)
        assert passed is True
        assert summary == "all good"
