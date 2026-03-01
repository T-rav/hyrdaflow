"""Tests for ADR-0015: Protocol-Based Callback Injection for Merge-Phase Gates."""

from __future__ import annotations

from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
ADR_FILE = ADR_DIR / "0015-protocol-callback-gate-pattern.md"
README_FILE = ADR_DIR / "README.md"


@pytest.fixture()
def adr_content() -> str:
    return ADR_FILE.read_text()


@pytest.fixture()
def readme_content() -> str:
    return README_FILE.read_text()


class TestAdr0009Exists:
    def test_adr_file_exists(self) -> None:
        assert ADR_FILE.exists(), "ADR-0015 file must exist"

    def test_readme_references_adr(self, readme_content: str) -> None:
        assert "0015" in readme_content
        assert "0015-protocol-callback-gate-pattern.md" in readme_content


class TestAdr0009Metadata:
    def test_has_status_proposed(self, adr_content: str) -> None:
        assert "**Status:** Proposed" in adr_content

    def test_has_date(self, adr_content: str) -> None:
        assert "**Date:** 2026-03-01" in adr_content

    def test_title_matches(self, adr_content: str) -> None:
        assert (
            "# ADR-0015: Protocol-Based Callback Injection for Merge-Phase Gates"
            in adr_content
        )


class TestAdr0009RequiredSections:
    """Validate the three sections required by the ADR format."""

    def test_has_context_section(self, adr_content: str) -> None:
        assert "## Context" in adr_content

    def test_has_decision_section(self, adr_content: str) -> None:
        assert "## Decision" in adr_content

    def test_has_consequences_section(self, adr_content: str) -> None:
        assert "## Consequences" in adr_content

    def test_has_alternatives_section(self, adr_content: str) -> None:
        assert "## Alternatives considered" in adr_content

    def test_has_related_section(self, adr_content: str) -> None:
        assert "## Related" in adr_content


class TestAdr0009Content:
    """Verify the ADR captures the gate pattern decision accurately."""

    def test_references_source_memory_issue(self, adr_content: str) -> None:
        assert "#1720" in adr_content

    def test_references_this_issue(self, adr_content: str) -> None:
        assert "#1746" in adr_content

    def test_references_ci_gate_fn(self, adr_content: str) -> None:
        assert "CiGateFn" in adr_content

    def test_references_escalate_fn(self, adr_content: str) -> None:
        assert "EscalateFn" in adr_content

    def test_references_visual_validation_decision(self, adr_content: str) -> None:
        assert "VisualValidationDecision" in adr_content

    def test_references_post_merge_handler(self, adr_content: str) -> None:
        assert "post_merge_handler" in adr_content

    def test_references_review_phase(self, adr_content: str) -> None:
        assert "review_phase" in adr_content

    def test_describes_four_phase_protocol(self, adr_content: str) -> None:
        assert "Config guard" in adr_content
        assert "bypass" in adr_content.lower()
        assert "execute" in adr_content.lower()
        assert "telemetry" in adr_content.lower()

    def test_decision_section_is_actionable(self, adr_content: str) -> None:
        """Decision section must be >60 chars per ADR validation rules."""
        marker = "## Decision"
        start = adr_content.index(marker) + len(marker)
        next_section = adr_content.index("## ", start)
        decision_text = adr_content[start:next_section].strip()
        assert len(decision_text) >= 60, (
            f"Decision section too short ({len(decision_text)} chars)"
        )

    def test_body_exceeds_minimum_length(self, adr_content: str) -> None:
        """ADR body must exceed 120 chars per validation rules."""
        assert len(adr_content.strip()) >= 120

    def test_consequences_has_positive_and_tradeoffs(self, adr_content: str) -> None:
        assert "**Positive:**" in adr_content
        assert "**Trade-offs:**" in adr_content

    def test_gate_table_lists_all_gates(self, adr_content: str) -> None:
        assert "CI gate" in adr_content
        assert "Visual validation" in adr_content
        assert "Escalation" in adr_content
        assert "PublishFn" in adr_content


class TestAdr0009PassesProjectValidation:
    """Validate ADR passes the same checks used by phase_utils.adr_validation_reasons."""

    def test_passes_adr_validation(self, adr_content: str) -> None:
        from phase_utils import adr_validation_reasons

        reasons = adr_validation_reasons(adr_content)
        assert reasons == [], f"ADR failed validation: {reasons}"
