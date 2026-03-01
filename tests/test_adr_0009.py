"""Tests for ADR-0009: Auto-Decompose Triage Counter Exclusion."""

from __future__ import annotations

from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
ADR_PATH = ADR_DIR / "0009-auto-decompose-triage-counter-exclusion.md"
README_PATH = ADR_DIR / "README.md"


class TestADR0009Exists:
    """ADR-0009 file must exist and be indexed in the README."""

    def test_adr_file_exists(self) -> None:
        assert ADR_PATH.exists(), "ADR-0009 markdown file must exist"

    def test_adr_indexed_in_readme(self) -> None:
        readme = README_PATH.read_text()
        assert "0009" in readme, "ADR-0009 must be listed in the README index"
        assert "0009-auto-decompose-triage-counter-exclusion.md" in readme, (
            "README must link to the ADR-0009 file"
        )


class TestADR0009Structure:
    """ADR-0009 must follow the project's ADR format."""

    @pytest.fixture()
    def content(self) -> str:
        return ADR_PATH.read_text()

    def test_has_title(self, content: str) -> None:
        assert content.startswith("# ADR-0009:")

    def test_has_status_proposed(self, content: str) -> None:
        assert "**Status:** Proposed" in content

    def test_has_date(self, content: str) -> None:
        assert "**Date:** 2026-" in content

    @pytest.mark.parametrize(
        "section",
        ["## Context", "## Decision", "## Consequences", "## Related"],
    )
    def test_has_required_section(self, content: str, section: str) -> None:
        assert section in content, f"ADR-0009 must contain a '{section}' section"

    def test_has_alternatives_considered(self, content: str) -> None:
        assert "## Alternatives considered" in content


class TestADR0009Content:
    """ADR-0009 must reference the correct source material and code paths."""

    @pytest.fixture()
    def content(self) -> str:
        return ADR_PATH.read_text()

    def test_references_source_memory_issue(self, content: str) -> None:
        assert "#1729" in content, "Must reference source memory issue #1729"

    def test_references_original_pr(self, content: str) -> None:
        assert "#1689" in content, "Must reference original PR #1689"

    def test_references_original_issue(self, content: str) -> None:
        assert "#1542" in content, "Must reference original issue #1542"

    def test_references_triage_phase(self, content: str) -> None:
        assert "triage_phase.py" in content

    def test_references_maybe_decompose(self, content: str) -> None:
        assert "_maybe_decompose" in content

    def test_references_increment_session_counter(self, content: str) -> None:
        assert "increment_session_counter" in content

    def test_references_state_tracker(self, content: str) -> None:
        assert "state.py" in content or "StateTracker" in content

    def test_decision_is_intentional_exclusion(self, content: str) -> None:
        assert "intentional" in content.lower(), (
            "Decision must explicitly state the exclusion is intentional"
        )

    def test_mentions_double_counting_rationale(self, content: str) -> None:
        assert (
            "double-counting" in content.lower() or "double counting" in content.lower()
        ), "Must explain the double-counting avoidance rationale"
