"""Tests for ADR pre-review validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_pre_validator import ADRPreValidator, ADRValidationIssue, ADRValidationResult


def _valid_adr(
    *,
    status: str = "Proposed",
    context: str = "Some context.",
    decision: str = "We decided to do the thing.",
    consequences: str = "Some consequences.",
) -> str:
    return f"""# ADR-0001: Test ADR

**Status:** {status}

## Context

{context}

## Decision

{decision}

## Consequences

{consequences}
"""


class TestADRValidationResult:
    def test_passed_when_no_issues(self) -> None:
        result = ADRValidationResult()
        assert result.passed is True
        assert result.has_fixable_only is False

    def test_not_passed_with_issues(self) -> None:
        result = ADRValidationResult(
            issues=[ADRValidationIssue(code="test", message="test issue")]
        )
        assert result.passed is False

    def test_has_fixable_only_all_fixable(self) -> None:
        result = ADRValidationResult(
            issues=[ADRValidationIssue(code="a", message="a", fixable=True)]
        )
        assert result.has_fixable_only is True

    def test_has_fixable_only_mixed(self) -> None:
        result = ADRValidationResult(
            issues=[
                ADRValidationIssue(code="a", message="a", fixable=True),
                ADRValidationIssue(code="b", message="b", fixable=False),
            ]
        )
        assert result.has_fixable_only is False


class TestCheckStatusField:
    def test_valid_status_passes(self) -> None:
        validator = ADRPreValidator()
        result = validator.validate(_valid_adr())
        assert result.passed is True

    def test_missing_status_detected(self) -> None:
        content = "# ADR\n\n## Context\nctx\n## Decision\ndec\n## Consequences\ncon\n"
        validator = ADRPreValidator()
        result = validator.validate(content)
        assert not result.passed
        codes = [i.code for i in result.issues]
        assert "missing_status" in codes
        # Missing status is fixable
        status_issue = next(i for i in result.issues if i.code == "missing_status")
        assert status_issue.fixable is True


class TestCheckRequiredSections:
    def test_all_sections_present(self) -> None:
        validator = ADRPreValidator()
        result = validator.validate(_valid_adr())
        assert result.passed is True

    def test_missing_context(self) -> None:
        content = (
            "# ADR\n**Status:** Proposed\n## Decision\ndec\n## Consequences\ncon\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        assert not result.passed
        codes = [i.code for i in result.issues]
        assert "missing_section_context" in codes

    def test_missing_decision(self) -> None:
        content = "# ADR\n**Status:** Proposed\n## Context\nctx\n## Consequences\ncon\n"
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "missing_section_decision" in codes

    def test_missing_consequences(self) -> None:
        content = "# ADR\n**Status:** Proposed\n## Context\nctx\n## Decision\ndec\n"
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "missing_section_consequences" in codes

    def test_missing_section_not_fixable(self) -> None:
        content = (
            "# ADR\n**Status:** Proposed\n## Decision\ndec\n## Consequences\ncon\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        issue = next(i for i in result.issues if i.code == "missing_section_context")
        assert issue.fixable is False


class TestCheckEmptySections:
    def test_empty_context_detected(self) -> None:
        content = (
            "# ADR\n**Status:** Proposed\n"
            "## Context\n\n## Decision\ndec\n## Consequences\ncon\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "empty_section_context" in codes

    def test_empty_decision_detected(self) -> None:
        content = (
            "# ADR\n**Status:** Proposed\n"
            "## Context\nctx\n## Decision\n\n## Consequences\ncon\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "empty_section_decision" in codes

    def test_empty_consequences_detected(self) -> None:
        content = (
            "# ADR\n**Status:** Proposed\n"
            "## Context\nctx\n## Decision\ndec\n## Consequences\n\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "empty_section_consequences" in codes

    def test_nonempty_sections_pass(self) -> None:
        validator = ADRPreValidator()
        result = validator.validate(_valid_adr())
        codes = [i.code for i in result.issues]
        assert not any(c.startswith("empty_section_") for c in codes)


class TestCheckSupersession:
    def test_valid_supersession_passes(self) -> None:
        content = _valid_adr(decision="This supersedes ADR-0001.")
        all_adrs = [(1, "Old ADR", "old content", "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" not in codes

    def test_invalid_supersession_detected(self) -> None:
        content = _valid_adr(decision="This supersedes ADR-9999.")
        all_adrs = [(1, "Old ADR", "old content", "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes

    def test_no_supersession_reference_passes(self) -> None:
        validator = ADRPreValidator()
        result = validator.validate(_valid_adr())
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" not in codes

    def test_superseding_variant_detected(self) -> None:
        """Regex matches 'superseding' variant."""
        content = _valid_adr(decision="This is superseding ADR-8888.")
        all_adrs = [(1, "Old ADR", "old content", "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes

    def test_superseded_past_tense_detected(self) -> None:
        """Regex matches 'superseded' past-tense variant."""
        content = _valid_adr(decision="This ADR superseded ADR-7777.")
        all_adrs = [(1, "Old ADR", "old content", "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes

    def test_supersession_with_null_adr_list_treated_as_empty(self) -> None:
        content = _valid_adr(decision="This supersedes ADR-9999.")
        validator = ADRPreValidator()
        # When all_adrs is None it is coerced to [], so any supersession reference
        # is flagged invalid because no existing ADRs are known.
        result = validator.validate(content, None)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes


class TestCheckBareADRReferences:
    def test_bare_reference_detected(self) -> None:
        """A plain ADR-NNNN without title annotation is flagged."""
        content = _valid_adr(decision="See ADR-0006 for details.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" in codes
        issue = next(i for i in result.issues if i.code == "bare_adr_reference")
        assert "ADR-0006" in issue.message

    def test_parenthesized_title_passes(self) -> None:
        """ADR-NNNN (Title) is not flagged."""
        content = _valid_adr(
            decision="See ADR-0006 (RepoRuntime Isolation Architecture) for details."
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" not in codes

    def test_em_dash_title_passes(self) -> None:
        """ADR-NNNN — Title is not flagged."""
        content = _valid_adr(
            decision="See ADR-0006 — RepoRuntime Isolation Architecture for details."
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" not in codes

    def test_self_reference_skipped(self) -> None:
        """References to the ADR's own number are not flagged."""
        content = _valid_adr(decision="ADR-0001 intentionally does this.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" not in codes

    def test_heading_line_skipped(self) -> None:
        """The ADR heading line '# ADR-NNNN: Title' is never flagged."""
        content = _valid_adr(decision="Some text here.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" not in codes

    def test_table_row_skipped(self) -> None:
        """ADR references inside markdown table rows are not flagged."""
        content = _valid_adr(
            decision="| **example** | ADR-0006 is used here |\n\nNormal text."
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" not in codes

    def test_multiple_bare_refs_deduplicated(self) -> None:
        """Multiple bare references to the same ADR produce one issue."""
        content = _valid_adr(decision="See ADR-0006. Also ADR-0006 again.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        bare_issues = [i for i in result.issues if i.code == "bare_adr_reference"]
        assert len(bare_issues) == 1

    def test_bare_reference_is_fixable(self) -> None:
        """Bare reference issues are marked as fixable."""
        content = _valid_adr(decision="See ADR-0006.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        issue = next(i for i in result.issues if i.code == "bare_adr_reference")
        assert issue.fixable is True

    def test_no_cross_references_passes(self) -> None:
        """An ADR with no cross-references produces no bare_adr_reference issue."""
        content = _valid_adr()
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" not in codes


class TestNonexistentADRReference:
    def test_nonexistent_reference_detected(self) -> None:
        """Referencing an ADR that doesn't exist in the index is flagged."""
        content = _valid_adr(decision="See ADR-0099 (Some Made Up Title) for details.")
        all_adrs = [(1, "Test ADR", "content", "0001-test.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "nonexistent_adr_reference" in codes
        issue = next(i for i in result.issues if i.code == "nonexistent_adr_reference")
        assert "ADR-0099" in issue.message

    def test_nonexistent_reference_not_fixable(self) -> None:
        """Nonexistent ADR references are not fixable."""
        content = _valid_adr(decision="See ADR-0099 (Some Made Up Title) for details.")
        all_adrs = [(1, "Test ADR", "content", "0001-test.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        issue = next(i for i in result.issues if i.code == "nonexistent_adr_reference")
        assert issue.fixable is False

    def test_existing_reference_not_flagged(self) -> None:
        """Referencing an ADR that exists is not flagged as nonexistent."""
        content = _valid_adr(
            decision="See ADR-0006 (Isolation Architecture) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (6, "Isolation Architecture", "content", "0006-isolation.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "nonexistent_adr_reference" not in codes

    def test_no_all_adrs_skips_existence_check(self) -> None:
        """When all_adrs is not provided, existence checks are skipped."""
        content = _valid_adr(decision="See ADR-0099 (Some Made Up Title) for details.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "nonexistent_adr_reference" not in codes

    def test_bare_nonexistent_ref_produces_both_issues(self) -> None:
        """A bare reference to a nonexistent ADR produces both issue codes."""
        content = _valid_adr(decision="See ADR-0099 for details.")
        all_adrs = [(1, "Test ADR", "content", "0001-test.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "bare_adr_reference" in codes
        assert "nonexistent_adr_reference" in codes


class TestMismatchedADRTitle:
    def test_wrong_title_detected(self) -> None:
        """A title annotation that doesn't match the real ADR title is flagged."""
        content = _valid_adr(
            decision="See ADR-0022 (Registry Lifecycle Tracker) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (22, "Pipeline Integration Harness", "content", "0022-harness.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" in codes
        issue = next(i for i in result.issues if i.code == "mismatched_adr_title")
        assert "Registry Lifecycle Tracker" in issue.message
        assert "Pipeline Integration Harness" in issue.message

    def test_correct_title_not_flagged(self) -> None:
        """A title annotation matching the real ADR title passes."""
        content = _valid_adr(
            decision="See ADR-0022 (Pipeline Integration Harness) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (22, "Pipeline Integration Harness", "content", "0022-harness.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes

    def test_case_insensitive_title_match(self) -> None:
        """Title comparison is case-insensitive."""
        content = _valid_adr(
            decision="See ADR-0022 (pipeline integration harness) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (22, "Pipeline Integration Harness", "content", "0022-harness.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes

    def test_em_dash_title_mismatch_detected(self) -> None:
        """Em-dash title annotations are also checked for accuracy."""
        content = _valid_adr(decision="See ADR-0022 — Wrong Title for details.")
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (22, "Pipeline Integration Harness", "content", "0022-harness.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" in codes

    def test_em_dash_correct_title_passes(self) -> None:
        """Em-dash title annotations with correct title pass."""
        content = _valid_adr(
            decision="See ADR-0022 — Pipeline Integration Harness for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (22, "Pipeline Integration Harness", "content", "0022-harness.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes

    def test_mismatch_is_fixable(self) -> None:
        """Mismatched title issues are marked as fixable."""
        content = _valid_adr(decision="See ADR-0022 (Wrong Title) for details.")
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (22, "Pipeline Integration Harness", "content", "0022-harness.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        issue = next(i for i in result.issues if i.code == "mismatched_adr_title")
        assert issue.fixable is True

    def test_no_all_adrs_skips_title_check(self) -> None:
        """When all_adrs is not provided, title mismatch checks are skipped."""
        content = _valid_adr(decision="See ADR-0022 (Wrong Title) for details.")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes

    def test_nonexistent_ref_skips_title_check(self) -> None:
        """When the referenced ADR doesn't exist, title check is skipped."""
        content = _valid_adr(decision="See ADR-0099 (Anything) for details.")
        all_adrs = [(1, "Test ADR", "content", "0001-test.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "nonexistent_adr_reference" in codes
        assert "mismatched_adr_title" not in codes


class TestMultipleIssues:
    def test_multiple_issues_collected(self) -> None:
        """An ADR with multiple problems should report all issues."""
        content = "# ADR\n## Decision\ndec\n"
        validator = ADRPreValidator()
        result = validator.validate(content)
        # Missing status, missing Context, missing Consequences
        assert len(result.issues) >= 3
        codes = {i.code for i in result.issues}
        assert "missing_status" in codes
        assert "missing_section_context" in codes
        assert "missing_section_consequences" in codes
