"""Tests for verification.py - verification issue body formatting."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import JudgeResult, VerificationCriterion
from tests.conftest import PRInfoFactory, TaskFactory
from verification import format_verification_issue_body


def _make_judge_result(
    issue_number: int = 42,
    pr_number: int = 101,
    criteria: list[VerificationCriterion] | None = None,
    verification_instructions: str = "1. Run the app\n2. Click the button",
    summary: str = "All good",
) -> JudgeResult:
    if criteria is None:
        criteria = [
            VerificationCriterion(
                description="Unit tests pass", passed=True, details="All 42 tests pass"
            ),
            VerificationCriterion(
                description="Linting passes", passed=True, details="No issues"
            ),
        ]
    return JudgeResult(
        issue_number=issue_number,
        pr_number=pr_number,
        criteria=criteria,
        verification_instructions=verification_instructions,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFormatVerificationIssueBody:
    """Tests for format_verification_issue_body."""

    def test_all_criteria_passed(self) -> None:
        """When all criteria pass, body contains the 'all passed' note."""
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        body = format_verification_issue_body(judge, issue, pr)

        assert "All criteria passed at code level" in body
        assert "\u26a0\ufe0f" not in body  # No warning icon
        assert "\u2705 PASS" in body

    def test_some_criteria_failed(self) -> None:
        """When some criteria fail, body highlights failures with warning."""
        criteria = [
            VerificationCriterion(description="Tests pass", passed=True, details="OK"),
            VerificationCriterion(
                description="No lint errors", passed=False, details="3 errors found"
            ),
            VerificationCriterion(
                description="Type check passes", passed=False, details="2 type errors"
            ),
        ]
        judge = _make_judge_result(criteria=criteria)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "2 criteria failed at code level" in body
        assert "\u274c FAIL" in body
        assert "\u2705 PASS" in body
        assert "pay extra attention" in body
        assert "All criteria passed" not in body

    def test_single_criterion_failed_uses_singular(self) -> None:
        """When exactly one criterion fails, uses singular 'criterion'."""
        criteria = [
            VerificationCriterion(description="Tests pass", passed=True, details="OK"),
            VerificationCriterion(
                description="Lint check", passed=False, details="Failed"
            ),
        ]
        judge = _make_judge_result(criteria=criteria)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "1 criterion failed" in body

    def test_no_criteria(self) -> None:
        """Edge case: empty criteria list still produces valid body."""
        judge = _make_judge_result(criteria=[])
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "No acceptance criteria were evaluated" in body
        assert "Verification Instructions" in body

    def test_empty_verification_instructions(self) -> None:
        """When no instructions, that section is omitted."""
        judge = _make_judge_result(verification_instructions="")
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "Verification Instructions" not in body

    def test_includes_issue_and_pr_links(self) -> None:
        """Body contains references to original issue and PR."""
        issue = TaskFactory.create(id=99)
        pr = PRInfoFactory.create(number=200, issue_number=99)
        judge = _make_judge_result(issue_number=99, pr_number=200)

        body = format_verification_issue_body(judge, issue, pr)

        assert "#99" in body
        assert "#200" in body
        assert "Original issue:" in body
        assert "Merged PR:" in body

    def test_includes_verification_instructions(self) -> None:
        """Body includes the verification instructions text."""
        instructions = "1. Start the server\n2. Visit /health\n3. Verify 200 OK"
        judge = _make_judge_result(verification_instructions=instructions)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "Verification Instructions" in body
        assert "Start the server" in body
        assert "Visit /health" in body

    def test_includes_issue_title_in_header(self) -> None:
        """Body header includes the issue title."""
        issue = TaskFactory.create(title="Add user authentication")
        pr = PRInfoFactory.create()
        judge = _make_judge_result()

        body = format_verification_issue_body(judge, issue, pr)

        assert "Verification: Add user authentication" in body

    def test_pipe_characters_in_criteria_escaped(self) -> None:
        """Pipe characters in criteria text are escaped to avoid breaking tables."""
        criteria = [
            VerificationCriterion(
                description="Check A | B",
                passed=True,
                details="Result: pass | ok",
            ),
        ]
        judge = _make_judge_result(criteria=criteria)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "Check A \\| B" in body
        assert "pass \\| ok" in body

    def test_long_instructions_truncated(self) -> None:
        """Very long instructions are truncated to prevent exceeding GitHub limits."""
        long_text = "x" * 60_000
        judge = _make_judge_result(verification_instructions=long_text)
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert len(body) < 65_536
        assert "...truncated" in body

    def test_footer_present(self) -> None:
        """Body ends with the HydraFlow footer."""
        judge = _make_judge_result()
        issue = TaskFactory.create()
        pr = PRInfoFactory.create()

        body = format_verification_issue_body(judge, issue, pr)

        assert "*Generated by HydraFlow*" in body
