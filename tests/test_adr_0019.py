"""Tests for ADR-0019: Background Task Delegation — Call the Right Abstraction Layer."""

from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
ADR_FILE = ADR_DIR / "0019-background-task-delegation-abstraction-layer.md"
README_FILE = ADR_DIR / "README.md"


class TestAdr0009Exists:
    """ADR-0019 file must exist and be listed in the index."""

    def test_adr_file_exists(self) -> None:
        assert ADR_FILE.exists(), f"ADR file not found: {ADR_FILE}"

    def test_adr_listed_in_readme_index(self) -> None:
        readme = README_FILE.read_text()
        assert "0019" in readme, "ADR-0019 not listed in README index"
        assert "0019-background-task-delegation-abstraction-layer.md" in readme, (
            "ADR-0019 filename not linked in README index"
        )


class TestAdr0009Format:
    """ADR-0019 must follow the project's ADR format."""

    @pytest.fixture()
    def content(self) -> str:
        return ADR_FILE.read_text()

    def test_has_title(self, content: str) -> None:
        assert content.startswith("# ADR-0019:")

    def test_has_status_proposed(self, content: str) -> None:
        assert "**Status:** Proposed" in content

    def test_has_date(self, content: str) -> None:
        assert "**Date:** 2026-03-01" in content

    def test_has_context_section(self, content: str) -> None:
        assert "## Context" in content

    def test_has_decision_section(self, content: str) -> None:
        assert "## Decision" in content

    def test_has_consequences_section(self, content: str) -> None:
        assert "## Consequences" in content

    def test_has_alternatives_section(self, content: str) -> None:
        assert "## Alternatives considered" in content

    def test_has_related_section(self, content: str) -> None:
        assert "## Related" in content


class TestAdr0009Content:
    """ADR-0019 must reference the source memory and key code paths."""

    @pytest.fixture()
    def content(self) -> str:
        return ADR_FILE.read_text()

    def test_references_source_memory_issue(self, content: str) -> None:
        assert "#1793" in content, "ADR must link back to source memory issue #1793"

    def test_references_release_epic(self, content: str) -> None:
        assert "release_epic" in content, "ADR must reference release_epic method"

    def test_references_check_and_close_epics(self, content: str) -> None:
        assert "check_and_close_epics" in content, (
            "ADR must reference check_and_close_epics method"
        )

    def test_references_cache_ttl_sentinel(self, content: str) -> None:
        assert "TTL" in content or "ttl" in content or "sentinel" in content, (
            "ADR must discuss cache TTL sentinel pattern"
        )

    def test_references_post_merge_handler(self, content: str) -> None:
        assert "post_merge_handler" in content, (
            "ADR must reference the post_merge_handler delegation call-site"
        )

    def test_references_epic_module(self, content: str) -> None:
        assert "src/epic.py" in content, "ADR must reference src/epic.py"

    def test_decision_rules_are_actionable(self, content: str) -> None:
        """Decision section must contain numbered rules."""
        decision_start = content.index("## Decision")
        consequences_start = content.index("## Consequences")
        decision_text = content[decision_start:consequences_start]
        assert "1." in decision_text, "Decision section should contain numbered rules"
        assert "2." in decision_text, "Decision section should have multiple rules"

    def test_consequences_cover_positives_and_tradeoffs(self, content: str) -> None:
        assert "**Positive:**" in content
        assert "**Trade-offs:**" in content
