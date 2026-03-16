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


class TestCheckVolatileLineCitations:
    def test_no_line_citations_passes(self) -> None:
        content = _valid_adr(
            consequences="- `src/config.py:_resolve_paths` — path resolution\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "volatile_line_citation" not in codes

    def test_single_line_citation_detected(self) -> None:
        content = _valid_adr(
            consequences="- `src/config.py:_resolve_paths` (line 1122) — path resolution\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "volatile_line_citation" in codes

    def test_multiple_line_citations_counted(self) -> None:
        content = _valid_adr(
            consequences=(
                "- `src/config.py:foo` (line 42) — one\n"
                "- `src/config.py:bar` (line 99) — two\n"
            )
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        issue = next(i for i in result.issues if i.code == "volatile_line_citation")
        assert "2 line-number citation(s)" in issue.message

    def test_line_citation_is_fixable(self) -> None:
        content = _valid_adr(consequences="- `src/foo.py:bar` (line 10) — something\n")
        validator = ADRPreValidator()
        result = validator.validate(content)
        issue = next(i for i in result.issues if i.code == "volatile_line_citation")
        assert issue.fixable is True

    def test_lines_range_citation_detected(self) -> None:
        content = _valid_adr(consequences="- `src/foo.py` (lines 10-20) — something\n")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "volatile_line_citation" in codes

    def test_lines_and_citation_detected(self) -> None:
        content = _valid_adr(
            consequences="- `src/foo.py` (lines 51 and 127) — something\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "volatile_line_citation" in codes


class TestCheckStaleAmendmentNotes:
    """Tests for cross-reference-aware stale amendment note detection."""

    def _adr_entry(
        self, num: int, title: str, status: str = "Proposed"
    ) -> tuple[int, str, str, str]:
        """Helper to build an all_adrs tuple with a given status."""
        content = f"# ADR-{num:04d}: {title}\n\n**Status:** {status}\n"
        return (num, title, content, f"{num:04d}-{title.lower().replace(' ', '-')}.md")

    def test_stale_note_when_referenced_adr_accepted(self) -> None:
        """'requires amending ADR-0021' is stale when ADR-0021 is Accepted."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0021.\n"
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Accepted")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" in codes
        issue = next(i for i in result.issues if i.code == "stale_amendment_note")
        assert issue.fixable is True

    def test_no_issue_when_referenced_adr_proposed(self) -> None:
        """'requires amending ADR-0021' is NOT stale when ADR-0021 is Proposed."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0021.\n"
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Proposed")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes

    def test_no_amending_notes_passes(self) -> None:
        """ADR with no amendment notes produces no stale_amendment_note issue."""
        content = _valid_adr(
            consequences="- ADR-0021 — amended to reflect repo-scoped paths.\n"
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Accepted")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes

    def test_nonexistent_adr_gracefully_skipped(self) -> None:
        """Amendment note referencing an ADR not in all_adrs is skipped."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0099.\n"
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Accepted")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes

    def test_two_stale_notes_produce_two_issues(self) -> None:
        """Two stale amendment notes referencing different Accepted ADRs."""
        content = _valid_adr(
            consequences=(
                "- Requires amending ADR-0021.\n- Also requires amending ADR-0003.\n"
            )
        )
        all_adrs = [
            self._adr_entry(21, "Persistence", status="Accepted"),
            self._adr_entry(3, "Worktrees", status="Accepted"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        stale_issues = [i for i in result.issues if i.code == "stale_amendment_note"]
        assert len(stale_issues) == 2
        messages = {i.message for i in stale_issues}
        assert any("ADR-0021" in m for m in messages)
        assert any("ADR-0003" in m for m in messages)

    def test_case_insensitive_detection(self) -> None:
        """Pattern matching is case-insensitive."""
        content = _valid_adr(consequences="This REQUIRES AMENDING ADR-0021.\n")
        all_adrs = [self._adr_entry(21, "Persistence", status="Accepted")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" in codes

    def test_no_all_adrs_produces_no_issues(self) -> None:
        """When all_adrs is None/empty, no stale_amendment_note issues are produced."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0021.\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes

    def test_duplicate_stale_notes_for_same_adr_deduplicated(self) -> None:
        """Two 'requires amending' phrases for the same Accepted ADR produce one issue."""
        content = _valid_adr(
            consequences=(
                "- Requires amending ADR-0021.\n"
                "- Also requires amending ADR-0021 in section 2.\n"
            )
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Accepted")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        stale_issues = [i for i in result.issues if i.code == "stale_amendment_note"]
        assert len(stale_issues) == 1

    def test_referenced_adr_without_status_field_skipped(self) -> None:
        """Amendment note referencing an ADR with no **Status:** field is silently skipped."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0021.\n"
        )
        # ADR-0021 entry has no **Status:** line — validator should not crash or flag
        all_adrs = [
            (
                21,
                "Persistence",
                "# ADR-0021: Persistence\n\nNo status here.\n",
                "0021-persistence.md",
            )
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes

    def test_no_issue_when_referenced_adr_superseded(self) -> None:
        """'requires amending ADR-0021' is NOT flagged when ADR-0021 is Superseded."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0021.\n"
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Superseded")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes

    def test_no_issue_when_referenced_adr_deprecated(self) -> None:
        """'requires amending ADR-0021' is NOT flagged when ADR-0021 is Deprecated."""
        content = _valid_adr(
            consequences="Accepting this ADR requires amending ADR-0021.\n"
        )
        all_adrs = [self._adr_entry(21, "Persistence", status="Deprecated")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "stale_amendment_note" not in codes


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


class TestCheckCrossReferenceTitles:
    """Tests for _check_cross_reference_titles — abbreviated title detection."""

    def test_exact_title_match_passes(self) -> None:
        """A cross-reference with the exact full title produces no issue."""
        content = _valid_adr(
            decision="See ADR-0023 (Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking)."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_abbreviated_title_flagged(self) -> None:
        """A cross-reference with an abbreviated title is flagged."""
        content = _valid_adr(
            decision="See ADR-0023 (Auto-Triage Toggle Must Gate Routing)."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" in codes
        issue = next(
            i for i in result.issues if i.code == "abbreviated_cross_ref_title"
        )
        assert "abbreviated" in issue.message.lower()
        assert "Not Just Stat Tracking" in issue.message

    def test_abbreviated_title_is_fixable(self) -> None:
        """Abbreviated cross-reference title issues are fixable."""
        content = _valid_adr(decision="See ADR-0023 (Auto-Triage Toggle).")
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (23, "Auto-Triage Toggle Must Gate Routing", "c", "0023-gate.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        issue = next(
            i for i in result.issues if i.code == "abbreviated_cross_ref_title"
        )
        assert issue.fixable is True

    def test_unknown_number_ignored(self) -> None:
        """A cross-reference to an unknown ADR number is not flagged as abbreviated."""
        content = _valid_adr(decision="See ADR-0099 (Some Partial Title).")
        all_adrs = [(1, "Test ADR", "content", "0001-test.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_multiple_shared_numbers_exact_match(self) -> None:
        """When multiple ADRs share a number, exact match to any passes."""
        content = _valid_adr(
            decision="See ADR-0023 (CLI Argparse Config Builder Pattern)."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
            (23, "CLI Argparse Config Builder Pattern", "c", "0023-cli.md"),
            (23, "Multi-Repo Architecture Wiring Pattern", "c", "0023-multi.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_multiple_shared_numbers_abbreviated_flagged(self) -> None:
        """When multiple ADRs share a number, an abbreviated title is flagged."""
        content = _valid_adr(
            decision="See ADR-0023 (Auto-Triage Toggle Must Gate Routing)."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
            (23, "CLI Argparse Config Builder Pattern", "c", "0023-cli.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" in codes

    def test_self_reference_skipped(self) -> None:
        """Cross-references to the ADR's own number are not checked."""
        content = _valid_adr(decision="This ADR-0001 (Test) is self-referencing.")
        all_adrs = [
            (1, "Test ADR With Longer Title", "content", "0001-test.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_no_all_adrs_skips_check(self) -> None:
        """When all_adrs is empty, abbreviated title check is skipped."""
        content = _valid_adr(decision="See ADR-0023 (Short Title).")
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_heading_line_skipped(self) -> None:
        """Cross-references in heading lines are not checked."""
        content = "# ADR-0005: Short\n\n**Status:** Proposed\n\n## Context\nctx\n## Decision\ndec\n## Consequences\ncon\n"
        all_adrs = [
            (5, "Short But Actually Longer Title", "c", "0005-short.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_table_row_skipped(self) -> None:
        """Cross-references in table rows are not checked."""
        content = _valid_adr(
            decision="| ADR-0023 (Short Title) | example |\n\nNormal text."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (23, "Short Title With More Words", "c", "0023-short.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes

    def test_emdash_abbreviated_title_flagged(self) -> None:
        """An em-dash cross-reference with an abbreviated title is flagged."""
        content = _valid_adr(
            decision="See ADR-0023 \u2014 Auto-Triage Toggle Must Gate Routing for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" in codes
        assert "mismatched_adr_title" not in codes

    def test_paren_title_with_nested_parens_not_false_positive(self) -> None:
        """A parenthesized title containing inner parens is not flagged as abbreviated."""
        content = _valid_adr(
            decision="See ADR-0023 (Config (Mode) Architecture Pattern) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (23, "Config (Mode) Architecture Pattern", "c", "0023-config.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" not in codes


class TestWordPrefixOverlap:
    """Tests for _word_prefix_overlap — handles em-dash trailing prose."""

    def test_matching_prefix_returns_true(self) -> None:
        """Strings sharing a word-prefix longer than the real title are detected."""
        assert ADRPreValidator._word_prefix_overlap(
            "auto-triage toggle must gate routing for details.",
            "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
        )

    def test_exact_match_returns_false(self) -> None:
        """Exact match is not an abbreviation."""
        assert not ADRPreValidator._word_prefix_overlap(
            "auto-triage toggle must gate routing",
            "Auto-Triage Toggle Must Gate Routing",
        )

    def test_too_few_common_words_returns_false(self) -> None:
        """Fewer than min_words shared words returns False."""
        assert not ADRPreValidator._word_prefix_overlap(
            "auto-triage toggle different words",
            "Auto-Triage Toggle Must Gate Routing",
        )

    def test_no_overlap_returns_false(self) -> None:
        """Completely different strings return False."""
        assert not ADRPreValidator._word_prefix_overlap(
            "completely different title here",
            "Auto-Triage Toggle Must Gate Routing",
        )

    def test_custom_min_words(self) -> None:
        """Custom min_words threshold is respected."""
        # 3 common words, but min_words=4
        assert not ADRPreValidator._word_prefix_overlap(
            "alpha beta gamma different",
            "Alpha Beta Gamma Delta Epsilon",
            min_words=4,
        )
        # 3 common words, min_words=3
        assert ADRPreValidator._word_prefix_overlap(
            "alpha beta gamma different",
            "Alpha Beta Gamma Delta Epsilon",
            min_words=3,
        )

    def test_emdash_abbreviated_not_double_flagged(self) -> None:
        """Em-dash abbreviated title with trailing prose is not flagged as mismatched."""
        content = _valid_adr(
            decision="See ADR-0023 \u2014 Auto-Triage Toggle Must Gate Routing for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "abbreviated_cross_ref_title" in codes
        assert "mismatched_adr_title" not in codes


class TestDictCollisionSharedNumbers:
    """Tests that title checking handles multiple ADRs sharing the same number."""

    def test_mismatched_title_with_shared_numbers(self) -> None:
        """Title mismatch check works correctly when multiple ADRs share a number."""
        content = _valid_adr(
            decision="See ADR-0023 (Completely Wrong Title) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (23, "Auto-Triage Toggle Must Gate Routing", "c", "0023-gate.md"),
            (23, "CLI Argparse Config Builder Pattern", "c", "0023-cli.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" in codes

    def test_correct_title_with_shared_numbers_passes(self) -> None:
        """Correct title for one of multiple ADRs sharing a number passes."""
        content = _valid_adr(
            decision="See ADR-0023 (CLI Argparse Config Builder Pattern) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (23, "Auto-Triage Toggle Must Gate Routing", "c", "0023-gate.md"),
            (23, "CLI Argparse Config Builder Pattern", "c", "0023-cli.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes

    def test_last_entry_not_favored_in_dict(self) -> None:
        """The first ADR's title for a shared number is still matchable (no dict collision)."""
        content = _valid_adr(decision="See ADR-0023 (First Title) for details.")
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (23, "First Title", "c", "0023-first.md"),
            (23, "Second Title", "c", "0023-second.md"),
            (23, "Third Title", "c", "0023-third.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes

    def test_abbreviated_title_not_double_flagged(self) -> None:
        """Abbreviated titles must not produce both mismatched_adr_title and abbreviated_cross_ref_title."""
        content = _valid_adr(
            decision="See ADR-0023 (Auto-Triage Toggle Must Gate Routing) for details."
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (
                23,
                "Auto-Triage Toggle Must Gate Routing, Not Just Stat Tracking",
                "c",
                "0023-gate.md",
            ),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        # Abbreviated title is flagged exactly once as abbreviated_cross_ref_title
        assert "abbreviated_cross_ref_title" in codes
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
