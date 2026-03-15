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
        all_adrs = [(1, "Old ADR", "old content")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" not in codes

    def test_invalid_supersession_detected(self) -> None:
        content = _valid_adr(decision="This supersedes ADR-9999.")
        all_adrs = [(1, "Old ADR", "old content")]
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
        all_adrs = [(1, "Old ADR", "old content")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes

    def test_superseded_past_tense_detected(self) -> None:
        """Regex matches 'superseded' past-tense variant."""
        content = _valid_adr(decision="This ADR superseded ADR-7777.")
        all_adrs = [(1, "Old ADR", "old content")]
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


class TestCheckNumberCollision:
    def test_no_collision_passes(self) -> None:
        validator = ADRPreValidator()
        all_adrs = [
            (1, "ADR One", "content1"),
            (2, "ADR Two", "content2"),
        ]
        result = validator.validate(_valid_adr(), all_adrs, adr_number=1)
        codes = [i.code for i in result.issues]
        assert "number_collision" not in codes

    def test_collision_detected(self) -> None:
        validator = ADRPreValidator()
        all_adrs = [
            (23, "ADR Alpha", "content1"),
            (23, "ADR Beta", "content2"),
            (23, "ADR Gamma", "content3"),
        ]
        result = validator.validate(_valid_adr(), all_adrs, adr_number=23)
        codes = [i.code for i in result.issues]
        assert "number_collision" in codes
        collision_issue = next(i for i in result.issues if i.code == "number_collision")
        assert "0023" in collision_issue.message
        assert "3 files" in collision_issue.message

    def test_collision_not_fixable(self) -> None:
        validator = ADRPreValidator()
        all_adrs = [
            (5, "ADR A", "c1"),
            (5, "ADR B", "c2"),
        ]
        result = validator.validate(_valid_adr(), all_adrs, adr_number=5)
        collision_issue = next(i for i in result.issues if i.code == "number_collision")
        assert collision_issue.fixable is False

    def test_no_collision_check_without_adr_number(self) -> None:
        """When adr_number is not provided, collision check is skipped."""
        validator = ADRPreValidator()
        all_adrs = [
            (1, "ADR A", "c1"),
            (1, "ADR B", "c2"),
        ]
        result = validator.validate(_valid_adr(), all_adrs)
        codes = [i.code for i in result.issues]
        assert "number_collision" not in codes

    def test_single_adr_at_number_no_collision(self) -> None:
        validator = ADRPreValidator()
        all_adrs = [
            (1, "Only ADR", "content"),
        ]
        result = validator.validate(_valid_adr(), all_adrs, adr_number=1)
        codes = [i.code for i in result.issues]
        assert "number_collision" not in codes


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
