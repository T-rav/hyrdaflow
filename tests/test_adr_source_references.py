"""Tests that ADR source code references are accurate and follow conventions.

These tests validate cross-reference correctness (function names match actual code)
and convention compliance (no stale line numbers), NOT prose content.
"""

from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_adr(filename: str) -> str:
    return (ADR_DIR / filename).read_text()


def _get_section(content: str, heading: str) -> str:
    """Extract the text under a given ## heading until the next ## heading."""
    lines = content.splitlines()
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if line.startswith("## ") and in_section:
            break
        if line.startswith(f"## {heading}"):
            in_section = True
            continue
        if in_section:
            section_lines.append(line)
    return "\n".join(section_lines)


# ---------------------------------------------------------------------------
# P1 — No stale line-number references in ADRs
# ---------------------------------------------------------------------------


class TestNoStaleLineNumbers:
    """ADR source references must omit line numbers (they drift as code evolves)."""

    def test_adr_0021_related_has_no_line_numbers(self) -> None:
        related = _get_section(
            _read_adr("0021-persistence-architecture-and-data-layout.md"),
            "Related",
        )
        assert "(line " not in related

    def test_adr_0023_related_has_no_line_numbers(self) -> None:
        related = _get_section(
            _read_adr("0023-adr-reviewer-proposed-only-filter.md"),
            "Related",
        )
        assert "(line " not in related

    def test_adr_0017_context_has_no_line_numbers(self) -> None:
        content = _read_adr("0017-auto-decompose-triage-counter-exclusion.md")
        context = _get_section(content, "Context")
        assert "(line " not in context


# ---------------------------------------------------------------------------
# P1 — ADR-0021 references the correct function name
# ---------------------------------------------------------------------------


class TestAdr0021FunctionReference:
    """ADR-0021 must reference _resolve_base_paths (not the stale _resolve_paths)."""

    def test_related_references_resolve_base_paths(self) -> None:
        related = _get_section(
            _read_adr("0021-persistence-architecture-and-data-layout.md"),
            "Related",
        )
        assert "_resolve_base_paths" in related

    def test_related_does_not_reference_stale_resolve_paths(self) -> None:
        related = _get_section(
            _read_adr("0021-persistence-architecture-and-data-layout.md"),
            "Related",
        )
        # _resolve_base_paths contains _resolve_paths as a substring, so check
        # that every occurrence of _resolve_paths is part of _resolve_base_paths.
        remainder = related.replace("_resolve_base_paths", "")
        assert "_resolve_paths" not in remainder

    def test_decision_references_resolve_base_paths(self) -> None:
        decision = _get_section(
            _read_adr("0021-persistence-architecture-and-data-layout.md"),
            "Decision",
        )
        assert "_resolve_base_paths" in decision

    def test_function_exists_in_config(self) -> None:
        """The referenced function must actually exist in the codebase."""
        src_dir = Path(__file__).resolve().parent.parent / "src"
        config_py = (src_dir / "config.py").read_text()
        assert "def _resolve_base_paths" in config_py


# ---------------------------------------------------------------------------
# P2 — ADR README contains line-number guidance
# ---------------------------------------------------------------------------


class TestAdrReadmeGuidance:
    """The ADR README must include guidance about omitting line numbers."""

    def test_readme_contains_line_number_guidance(self) -> None:
        readme = _read_adr("README.md")
        assert "line number" in readme.lower()

    def test_guidance_near_format_section(self) -> None:
        format_section = _get_section(_read_adr("README.md"), "Format")
        assert "line number" in format_section.lower()
