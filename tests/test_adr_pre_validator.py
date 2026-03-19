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


def _adr_with_number(
    num: int,
    *,
    status: str = "Accepted",
    decision: str = "We decided to do the thing.",
) -> str:
    return f"""# ADR-{num:04d}: Test ADR {num}

**Status:** {status}

## Context

Some context.

## Decision

{decision}

## Consequences

Some consequences.
"""


class TestCheckSupersession:
    def test_valid_supersession_passes(self) -> None:
        content = _adr_with_number(2, decision="This supersedes ADR-0001.")
        target = _adr_with_number(
            1, status="Superseded", decision="Superseded by ADR-0002."
        )
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" not in codes
        assert "missing_reciprocal_supersession" not in codes

    def test_invalid_supersession_detected(self) -> None:
        content = _adr_with_number(2, decision="This supersedes ADR-9999.")
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
        result = validator.validate(content, None)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes

    # --- Bidirectional reciprocity tests ---

    def test_missing_reciprocal_supersedes_detected(self) -> None:
        """If ADR-0002 supersedes ADR-0001, ADR-0001 must say 'Superseded by ADR-0002'."""
        content = _adr_with_number(2, decision="This supersedes ADR-0001.")
        target = _adr_with_number(1, decision="No back-reference here.")
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "missing_reciprocal_supersession" in codes
        issue = next(
            i for i in result.issues if i.code == "missing_reciprocal_supersession"
        )
        assert "ADR-0001" in issue.message
        assert "Superseded by ADR-0002" in issue.message
        assert issue.fixable is True

    def test_missing_reciprocal_superseded_by_detected(self) -> None:
        """If ADR-0001 says 'Superseded by ADR-0002', ADR-0002 must say 'Supersedes ADR-0001'."""
        content = _adr_with_number(
            1, status="Superseded", decision="Superseded by ADR-0002."
        )
        target = _adr_with_number(2, decision="No back-reference here.")
        all_adrs = [(2, "Test ADR 2", target, "0002-new-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "missing_reciprocal_supersession" in codes
        issue = next(
            i for i in result.issues if i.code == "missing_reciprocal_supersession"
        )
        assert "ADR-0002" in issue.message
        assert "Supersedes ADR-0001" in issue.message

    def test_reciprocal_superseded_by_present_passes(self) -> None:
        """No issue when both sides have matching references."""
        content = _adr_with_number(
            1, status="Superseded", decision="Superseded by ADR-0002."
        )
        target = _adr_with_number(2, decision="This supersedes ADR-0001.")
        all_adrs = [(2, "Test ADR 2", target, "0002-new-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "missing_reciprocal_supersession" not in codes

    def test_superseded_by_nonexistent_adr_detected(self) -> None:
        """'Superseded by ADR-9999' where ADR-9999 doesn't exist is flagged."""
        content = _adr_with_number(
            1, status="Superseded", decision="Superseded by ADR-9999."
        )
        all_adrs = [(1, "Test ADR 1", content, "0001-test.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" in codes

    # --- Status coherence tests ---

    def test_proposed_cannot_supersede_accepted(self) -> None:
        """A Proposed ADR cannot formally supersede an Accepted ADR."""
        content = _adr_with_number(
            2, status="Proposed", decision="This supersedes ADR-0001."
        )
        target = _adr_with_number(1, status="Accepted", decision="Original decision.")
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "status_incoherent_supersession" in codes
        issue = next(
            i for i in result.issues if i.code == "status_incoherent_supersession"
        )
        assert "Proposed" in issue.message
        assert "Accepted" in issue.message
        assert issue.fixable is True

    def test_proposed_cannot_supersede_deprecated(self) -> None:
        """A Proposed ADR cannot supersede a Deprecated ADR either."""
        content = _adr_with_number(
            2, status="Proposed", decision="This supersedes ADR-0001."
        )
        target = _adr_with_number(1, status="Deprecated", decision="Old decision.")
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "status_incoherent_supersession" in codes
        issue = next(
            i for i in result.issues if i.code == "status_incoherent_supersession"
        )
        assert "Deprecated" in issue.message

    def test_accepted_can_supersede_accepted(self) -> None:
        """An Accepted ADR can formally supersede another Accepted ADR."""
        content = _adr_with_number(
            2, status="Accepted", decision="This supersedes ADR-0001."
        )
        target = _adr_with_number(
            1, status="Accepted", decision="Superseded by ADR-0002."
        )
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "status_incoherent_supersession" not in codes

    def test_accepted_superseded_by_proposed_flagged(self) -> None:
        """If ADR-0001 (Accepted) says 'Superseded by ADR-0002' but ADR-0002 is Proposed, flag it."""
        content = _adr_with_number(
            1, status="Accepted", decision="Superseded by ADR-0002."
        )
        target = _adr_with_number(
            2, status="Proposed", decision="This supersedes ADR-0001."
        )
        all_adrs = [(2, "Test ADR 2", target, "0002-new-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "status_incoherent_supersession" in codes
        issue = next(
            i for i in result.issues if i.code == "status_incoherent_supersession"
        )
        assert "Proposed" in issue.message
        assert "Accepted" in issue.message
        assert issue.fixable is True

    def test_duplicate_supersedes_ref_produces_single_issue(self) -> None:
        """Same ADR number mentioned twice in 'supersedes' should not double-report."""
        content = _adr_with_number(
            2, decision="This supersedes ADR-0001 and also supersedes ADR-0001."
        )
        target = _adr_with_number(1, decision="No back-reference here.")
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        issues = [
            i for i in result.issues if i.code == "missing_reciprocal_supersession"
        ]
        assert len(issues) == 1

    def test_bidirectional_check_skipped_when_no_heading(self) -> None:
        """When ADR has no standard heading, self_number is None and reciprocity checks are skipped."""
        content = (
            "**Status:** Accepted\n\n"
            "## Context\n\nSome context.\n\n"
            "## Decision\n\nThis supersedes ADR-0001.\n\n"
            "## Consequences\n\nSome consequences.\n"
        )
        target = _adr_with_number(1, decision="No back-reference here.")
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        # Existence check still runs; reciprocity check is silently skipped (self_number=None)
        codes = [i.code for i in result.issues]
        assert "invalid_supersession" not in codes
        assert "missing_reciprocal_supersession" not in codes

    def test_proposed_can_supersede_proposed(self) -> None:
        """A Proposed ADR can supersede another Proposed ADR (neither is settled)."""
        content = _adr_with_number(
            2, status="Proposed", decision="This supersedes ADR-0001."
        )
        target = _adr_with_number(
            1, status="Proposed", decision="Superseded by ADR-0002."
        )
        all_adrs = [(1, "Test ADR 1", target, "0001-old-adr.md")]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "status_incoherent_supersession" not in codes


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

    def test_inline_line_number_in_symbol_position_detected(self) -> None:
        """A digit-only 'symbol' like `src/foo.py:419` is a volatile line citation."""
        content = _valid_adr(
            consequences="- `src/implement_phase.py:419` — implemented counter\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "volatile_line_citation" in codes

    def test_inline_line_number_not_treated_as_phantom_symbol(self) -> None:
        """Digit-only symbol positions should NOT produce phantom_source_symbol."""
        content = _valid_adr(
            consequences="- `src/implement_phase.py:419` — implemented counter\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=Path("/fake"))
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_inline_comma_separated_line_numbers_detected(self) -> None:
        """Comma-separated line numbers like `src/foo.py:97,121` are detected."""
        content = _valid_adr(
            consequences="- `src/triage_phase.py:97,121` — triaged counter\n"
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "volatile_line_citation" in codes

    def test_mixed_paren_and_inline_citations_counted_together(self) -> None:
        """Both (line N) and `src/foo.py:N` formats are summed in one issue."""
        content = _valid_adr(
            consequences=(
                "- `src/foo.py:bar` (line 42) — paren style\n"
                "- `src/baz.py:99` — inline style\n"
            )
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        issue = next(i for i in result.issues if i.code == "volatile_line_citation")
        assert "2 line-number citation(s)" in issue.message


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

    def test_emdash_with_double_dash_captures_trailing_prose_as_title(self) -> None:
        """Em-dash citation with a second em-dash captures trailing prose, causing mismatch.

        Regression test for issue #3241: ADR-0023 cited ADR-0004 as
        'ADR-0004 — CLI-based Agent Runtime (Claude / Codex / Pi.dev) — related...'
        which captured everything after the first em-dash as the title.
        The fix is to use the parenthesized format instead.
        """
        # The em-dash format captures through the second em-dash — this IS a mismatch
        content = _valid_adr(
            decision=("See ADR-0004 — Wrong Title Here — related but distinct"),
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (4, "agent cli as runtime", "content", "0004-agent-cli-as-runtime.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" in codes

    def test_paren_title_matching_filename_slug_passes(self) -> None:
        """Parenthesized title matching the filename-derived slug passes validation.

        Regression test for issue #3241: the fix converts em-dash citations
        to the parenthesized format so the title is clearly delimited.
        """
        content = _valid_adr(
            decision=("See ADR-0004 (agent cli as runtime) — related but distinct"),
        )
        all_adrs = [
            (1, "Test ADR", "content", "0001-test.md"),
            (4, "agent cli as runtime", "content", "0004-agent-cli-as-runtime.md"),
        ]
        validator = ADRPreValidator()
        result = validator.validate(content, all_adrs)
        codes = [i.code for i in result.issues]
        assert "mismatched_adr_title" not in codes


class TestCheckSourceFunctionRefs:
    """Tests for phantom source symbol detection."""

    def test_valid_function_reference_passes(self, tmp_path: Path) -> None:
        """A cited function that exists in the source file is not flagged."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("def _resolve_paths():\n    pass\n")
        content = _valid_adr(context="See `src/config.py:_resolve_paths` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_phantom_function_detected(self, tmp_path: Path) -> None:
        """A cited function that does NOT exist in the source file is flagged."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("def _resolve_repo_scoped_paths():\n    pass\n")
        content = _valid_adr(
            context="See `src/config.py:_namespace_repo_paths` for details."
        )
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" in codes
        issue = next(i for i in result.issues if i.code == "phantom_source_symbol")
        assert "_namespace_repo_paths" in issue.message
        assert "config.py" in issue.message

    def test_class_name_reference_passes(self, tmp_path: Path) -> None:
        """A cited class name that exists in the source file is not flagged."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("class HydraFlowConfig:\n    pass\n")
        content = _valid_adr(context="See `src/config.py:HydraFlowConfig` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_indented_method_definition_passes(self, tmp_path: Path) -> None:
        """An indented class method definition is correctly found (not a false positive)."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text(
            "class Foo:\n    def _resolve_paths(self):\n        pass\n"
        )
        content = _valid_adr(context="See `src/config.py:_resolve_paths` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_missing_source_file_skipped(self, tmp_path: Path) -> None:
        """A reference to a non-existent file does not produce an issue."""
        src = tmp_path / "src"
        src.mkdir()
        content = _valid_adr(context="See `src/nonexistent.py:some_func` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_no_repo_root_skips_check(self) -> None:
        """When repo_root is None, phantom symbol checks are skipped entirely."""
        content = _valid_adr(
            context="See `src/config.py:_namespace_repo_paths` for details."
        )
        validator = ADRPreValidator()
        result = validator.validate(content)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_phantom_symbol_is_not_fixable(self, tmp_path: Path) -> None:
        """Phantom source symbol issues are NOT auto-fixable: the correct name requires human judgment."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("def real_func():\n    pass\n")
        content = _valid_adr(context="See `src/config.py:fake_func` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        issue = next(i for i in result.issues if i.code == "phantom_source_symbol")
        assert issue.fixable is False

    def test_module_level_constant_flagged_as_phantom(self, tmp_path: Path) -> None:
        """A cited module-level constant (not def/class) is flagged as phantom.

        ADRs should cite only functions or classes, not constants or type aliases.
        This documents the expected behavior for authors who accidentally cite a constant.
        """
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("MY_CONSTANT = 42\n")
        content = _valid_adr(context="See `src/config.py:MY_CONSTANT` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" in codes

    def test_multiple_phantom_symbols_detected(self, tmp_path: Path) -> None:
        """Multiple phantom symbols from different files are each flagged."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("def real_func():\n    pass\n")
        (src / "models.py").write_text("class RealModel:\n    pass\n")
        content = _valid_adr(
            context=(
                "See `src/config.py:phantom_one` and "
                "`src/models.py:phantom_two` for details."
            )
        )
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        phantom_issues = [i for i in result.issues if i.code == "phantom_source_symbol"]
        assert len(phantom_issues) == 2

    def test_non_src_path_not_matched(self) -> None:
        """References to files outside src/ are not checked."""
        content = _valid_adr(context="See `docs/config.py:some_func` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=Path("/fake"))
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_deeply_indented_method_passes(self, tmp_path: Path) -> None:
        """A method nested inside a class inside another block is still found."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text(
            "class Outer:\n"
            "    class Inner:\n"
            "        def deeply_nested(self):\n"
            "            pass\n"
        )
        content = _valid_adr(context="See `src/config.py:deeply_nested` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_async_function_reference_passes(self, tmp_path: Path) -> None:
        """An async def function is found and not flagged as phantom."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("async def fetch_data():\n    pass\n")
        content = _valid_adr(context="See `src/config.py:fetch_data` for details.")
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        codes = [i.code for i in result.issues]
        assert "phantom_source_symbol" not in codes

    def test_duplicate_references_produce_one_issue(self, tmp_path: Path) -> None:
        """The same phantom symbol cited twice produces only one issue."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "config.py").write_text("def real():\n    pass\n")
        content = _valid_adr(
            context=("See `src/config.py:phantom` and also `src/config.py:phantom`.")
        )
        validator = ADRPreValidator()
        result = validator.validate(content, repo_root=tmp_path)
        phantom_issues = [i for i in result.issues if i.code == "phantom_source_symbol"]
        assert len(phantom_issues) == 1


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
