"""Tests for ADR-0012: Epic Merge Coordination Architecture."""

from __future__ import annotations

from pathlib import Path

import pytest

_ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
_ADR_FILE = _ADR_DIR / "0012-epic-merge-coordination-architecture.md"
_README = _ADR_DIR / "README.md"


class TestADR0012Exists:
    """ADR-0012 file and index entry must exist."""

    def test_adr_file_exists(self) -> None:
        assert _ADR_FILE.exists(), "ADR-0012 markdown file must exist"

    def test_adr_listed_in_readme_index(self) -> None:
        content = _README.read_text()
        assert "0012" in content, "ADR-0012 must be listed in the README index"
        assert "Epic Merge Coordination" in content


class TestADR0012Format:
    """ADR-0012 must follow the required format from docs/adr/README.md."""

    @pytest.fixture()
    def content(self) -> str:
        return _ADR_FILE.read_text()

    def test_has_title(self, content: str) -> None:
        assert content.startswith("# ADR-0012:")

    def test_has_status(self, content: str) -> None:
        assert "**Status:** Proposed" in content

    def test_has_date(self, content: str) -> None:
        assert "**Date:** 2026-" in content

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


class TestADR0012Content:
    """ADR-0012 must capture the epic merge coordination decision accurately."""

    @pytest.fixture()
    def content(self) -> str:
        return _ADR_FILE.read_text()

    def test_references_source_memory_issue(self, content: str) -> None:
        assert "#1684" in content, "Must link back to source memory issue #1684"

    def test_references_adr_issue(self, content: str) -> None:
        assert "#1702" in content, "Must link back to ADR issue #1702"

    def test_describes_four_strategies(self, content: str) -> None:
        for strategy in ("independent", "bundled", "bundled_hitl", "ordered"):
            assert strategy in content, f"Must describe '{strategy}' strategy"

    def test_describes_merge_coordinator(self, content: str) -> None:
        assert "EpicMergeCoordinator" in content

    def test_describes_hold_merge_mechanism(self, content: str) -> None:
        assert "should_hold_merge" in content

    def test_describes_approved_label(self, content: str) -> None:
        assert "hydraflow-approved" in content

    def test_describes_approved_children_field(self, content: str) -> None:
        assert "approved_children" in content

    def test_references_post_merge_handler(self, content: str) -> None:
        assert "PostMergeHandler" in content or "post_merge_handler" in content

    def test_references_epic_state(self, content: str) -> None:
        assert "EpicState" in content

    def test_references_epic_manager(self, content: str) -> None:
        assert "EpicManager" in content

    def test_describes_bundle_readiness(self, content: str) -> None:
        assert "bundle" in content.lower() and "ready" in content.lower()
