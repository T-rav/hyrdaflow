"""Tests for ADR-0016: VisualValidation SKIPPED Override Semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

_ADR_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "adr"
    / "0016-visual-validation-skipped-override-semantics.md"
)
_README_PATH = _ADR_PATH.parent / "README.md"


class TestAdr0009Exists:
    """ADR-0016 file must exist and be indexed."""

    def test_adr_file_exists(self) -> None:
        assert _ADR_PATH.exists(), f"ADR file not found at {_ADR_PATH}"

    def test_adr_indexed_in_readme(self) -> None:
        readme = _README_PATH.read_text()
        assert "0016" in readme
        assert "visual-validation-skipped-override-semantics" in readme


class TestAdr0009RequiredSections:
    """ADR-0016 must contain all required sections per docs/adr/README.md."""

    @pytest.fixture()
    def content(self) -> str:
        return _ADR_PATH.read_text()

    def test_has_status(self, content: str) -> None:
        assert "**Status:**" in content

    def test_has_date(self, content: str) -> None:
        assert "**Date:**" in content

    def test_has_context_section(self, content: str) -> None:
        assert "## Context" in content

    def test_has_decision_section(self, content: str) -> None:
        assert "## Decision" in content

    def test_has_consequences_section(self, content: str) -> None:
        assert "## Consequences" in content


class TestAdr0009ContentAccuracy:
    """ADR-0016 content must reference the correct code and concepts."""

    @pytest.fixture()
    def content(self) -> str:
        return _ADR_PATH.read_text()

    def test_references_source_memory_issue(self, content: str) -> None:
        assert "#1725" in content

    def test_references_tracking_issue(self, content: str) -> None:
        assert "#1747" in content

    def test_references_post_merge_handler(self, content: str) -> None:
        assert "post_merge_handler" in content

    def test_references_should_create_verification_issue(self, content: str) -> None:
        assert "_should_create_verification_issue" in content

    def test_references_manual_verify_keywords(self, content: str) -> None:
        assert "_MANUAL_VERIFY_KEYWORDS" in content

    def test_references_user_surface_diff_re(self, content: str) -> None:
        assert "_USER_SURFACE_DIFF_RE" in content

    def test_documents_skipped_suppresses_diff_check(self, content: str) -> None:
        assert "SKIPPED" in content
        assert "diff" in content.lower()

    def test_documents_skipped_does_not_suppress_keyword_cues(
        self, content: str
    ) -> None:
        assert "keyword" in content.lower()
        # Partial suppression is the key concept
        assert "partial" in content.lower() or "still honours" in content.lower()

    def test_status_is_proposed(self, content: str) -> None:
        assert "Proposed" in content
