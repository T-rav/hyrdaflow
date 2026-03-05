"""Tests for ADR-0020: autoApproveRow borderTop Context Awareness."""

from pathlib import Path

import pytest

from phase_utils import adr_validation_reasons

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = REPO_ROOT / "docs" / "adr"
ADR_FILE = ADR_DIR / "0020-autoApproveRow-border-context-awareness.md"
README_FILE = ADR_DIR / "README.md"


class TestADR0020Exists:
    """Verify the ADR file exists and is registered in the index."""

    def test_adr_file_exists(self) -> None:
        assert ADR_FILE.exists(), f"ADR file not found: {ADR_FILE}"

    def test_adr_listed_in_readme_index(self) -> None:
        readme = README_FILE.read_text()
        assert "0020" in readme
        assert "autoApproveRow" in readme


class TestADR0020Format:
    """Verify the ADR passes shape validation and has required metadata."""

    @pytest.fixture()
    def content(self) -> str:
        return ADR_FILE.read_text()

    def test_passes_adr_validation(self, content: str) -> None:
        reasons = adr_validation_reasons(content)
        assert reasons == [], f"Validation failures: {reasons}"

    def test_has_status_superseded(self, content: str) -> None:
        assert "**Status:** Superseded" in content

    def test_has_date(self, content: str) -> None:
        assert "**Date:** 2026-03-01" in content

    def test_has_context_section(self, content: str) -> None:
        assert "## Context" in content

    def test_has_decision_section(self, content: str) -> None:
        assert "## Decision" in content

    def test_has_consequences_section(self, content: str) -> None:
        assert "## Consequences" in content

    def test_has_alternatives_considered(self, content: str) -> None:
        assert "## Alternatives considered" in content

    def test_has_related_section(self, content: str) -> None:
        assert "## Related" in content


class TestADR0020Content:
    """Verify the ADR references the correct source memory and code paths."""

    @pytest.fixture()
    def content(self) -> str:
        return ADR_FILE.read_text()

    def test_references_source_memory_issue(self, content: str) -> None:
        assert "#1805" in content

    def test_references_current_issue(self, content: str) -> None:
        assert "#1818" in content

    def test_references_system_panel(self, content: str) -> None:
        assert "SystemPanel.jsx" in content

    def test_references_autoApproveRow_style(self, content: str) -> None:
        assert "autoApproveRow" in content

    def test_is_superseded(self, content: str) -> None:
        assert "Superseded" in content
