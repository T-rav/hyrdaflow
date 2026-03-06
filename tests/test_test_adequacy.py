"""Tests for test_adequacy module — prompt builder and result parser."""

from __future__ import annotations

from test_adequacy import build_test_adequacy_prompt, parse_test_adequacy_result


class TestBuildTestAdequacyPrompt:
    def test_includes_issue_context(self) -> None:
        prompt = build_test_adequacy_prompt(
            issue_number=99, issue_title="Add new feature", diff="--- a/f\n+++ b/f"
        )
        assert "#99" in prompt
        assert "Add new feature" in prompt

    def test_includes_diff(self) -> None:
        diff = "+def new_func():\n+    return 42"
        prompt = build_test_adequacy_prompt(issue_number=1, issue_title="T", diff=diff)
        assert diff in prompt

    def test_includes_structured_output_markers(self) -> None:
        prompt = build_test_adequacy_prompt(issue_number=1, issue_title="T", diff="")
        assert "TEST_ADEQUACY_RESULT: OK" in prompt
        assert "TEST_ADEQUACY_RESULT: RETRY" in prompt


class TestParseTestAdequacyResult:
    def test_ok_result(self) -> None:
        transcript = (
            "TEST_ADEQUACY_RESULT: OK\n"
            "SUMMARY: All changed code has adequate test coverage"
        )
        passed, summary, gaps = parse_test_adequacy_result(transcript)
        assert passed is True
        assert "adequate" in summary
        assert gaps == []

    def test_retry_result_with_gaps(self) -> None:
        transcript = (
            "TEST_ADEQUACY_RESULT: RETRY\n"
            "SUMMARY: missing edge case tests\n"
            "GAPS:\n"
            "- src/agent.py:run — no test for empty worktree\n"
            "- src/config.py:validate — no test for invalid env var\n"
        )
        passed, summary, gaps = parse_test_adequacy_result(transcript)
        assert passed is False
        assert "missing edge case" in summary
        assert len(gaps) == 2
        assert "empty worktree" in gaps[0]

    def test_missing_marker_defaults_to_pass(self) -> None:
        passed, summary, gaps = parse_test_adequacy_result("just some output")
        assert passed is True
        assert gaps == []

    def test_retry_without_gaps_section(self) -> None:
        transcript = "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: no tests at all"
        passed, summary, gaps = parse_test_adequacy_result(transcript)
        assert passed is False
        assert summary == "no tests at all"
        assert gaps == []

    def test_case_insensitive_marker(self) -> None:
        transcript = "test_adequacy_result: ok\nsummary: covered"
        passed, summary, _ = parse_test_adequacy_result(transcript)
        assert passed is True
        assert summary == "covered"
