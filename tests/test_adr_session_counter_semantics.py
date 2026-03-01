"""Tests for ADR-0014: Session Counter Forward-Progression Semantics."""

from __future__ import annotations

import re
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
ADR_FILE = ADR_DIR / "0014-session-counter-forward-progression-semantics.md"
README_FILE = ADR_DIR / "README.md"


class TestAdr0009Exists:
    """ADR-0014 file exists and is referenced in the index."""

    def test_adr_file_exists(self) -> None:
        assert ADR_FILE.exists(), f"ADR file missing: {ADR_FILE}"

    def test_adr_file_is_not_empty(self) -> None:
        content = ADR_FILE.read_text()
        assert len(content.strip()) > 100, "ADR file appears empty or trivially short"

    def test_readme_references_adr(self) -> None:
        readme = README_FILE.read_text()
        assert "0014" in readme, "README.md does not reference ADR-0014"
        assert "session-counter-forward-progression-semantics" in readme, (
            "README.md missing ADR-0014 filename link"
        )


class TestAdr0009Format:
    """ADR-0014 follows the required format."""

    def setup_method(self) -> None:
        self.content = ADR_FILE.read_text()

    def test_has_title(self) -> None:
        assert self.content.startswith("# ADR-0014:"), (
            "ADR must start with '# ADR-0014:'"
        )

    def test_has_status(self) -> None:
        assert re.search(
            r"\*\*Status:\*\*\s+(Proposed|Accepted|Superseded)", self.content
        ), "ADR must have a valid Status field"

    def test_has_date(self) -> None:
        assert re.search(r"\*\*Date:\*\*\s+\d{4}-\d{2}-\d{2}", self.content), (
            "ADR must have a Date field in YYYY-MM-DD format"
        )

    def test_has_context_section(self) -> None:
        assert "## Context" in self.content, "ADR must have a Context section"

    def test_has_decision_section(self) -> None:
        assert "## Decision" in self.content, "ADR must have a Decision section"

    def test_has_consequences_section(self) -> None:
        assert "## Consequences" in self.content, "ADR must have a Consequences section"


class TestAdr0009Content:
    """ADR-0014 contains the required domain-specific content."""

    def setup_method(self) -> None:
        self.content = ADR_FILE.read_text()

    def test_references_session_counters(self) -> None:
        assert "SessionCounters" in self.content, (
            "ADR must reference SessionCounters model"
        )

    def test_references_forward_progression(self) -> None:
        assert (
            "forward-progression" in self.content.lower()
            or "forward progression" in self.content.lower()
        ), "ADR must discuss forward-progression semantics"

    def test_references_source_memory(self) -> None:
        assert "#1697" in self.content, (
            "ADR must link back to source memory issue #1697"
        )

    def test_references_implementation_pr(self) -> None:
        assert "#1689" in self.content, "ADR must reference implementation PR #1689"

    def test_references_session_counter_map(self) -> None:
        assert "session_counter_map" in self.content, (
            "ADR must discuss session_counter_map mapping"
        )

    def test_discusses_unknown_stage_mapping(self) -> None:
        assert "map" in self.content.lower() and (
            "empty string" in self.content.lower() or '""' in self.content
        ), "ADR must discuss mapping unknown stages to empty string"

    def test_discusses_review_counter(self) -> None:
        assert "review" in self.content.lower() and "APPROVE" in self.content, (
            "ADR must discuss the review counter APPROVE guard"
        )

    def test_has_alternatives_section(self) -> None:
        assert "## Alternatives considered" in self.content, (
            "ADR should include Alternatives considered"
        )

    def test_has_related_section(self) -> None:
        assert "## Related" in self.content, "ADR should include Related links"
