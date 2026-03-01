"""Tests that ADR files under docs/adr/ follow the required format."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"

REQUIRED_SECTIONS = ["## Context", "## Decision", "## Consequences"]
OPTIONAL_SECTIONS = ["## Alternatives considered", "## Related"]

STATUS_VALUES = {"Proposed", "Accepted", "Deprecated", "Superseded"}


def _adr_files() -> list[Path]:
    """Return all numbered ADR markdown files (excluding README)."""
    return sorted(ADR_DIR.glob("[0-9]*.md"))


class TestADRFileStructure:
    """Validate that every ADR file follows the required format from README.md."""

    @pytest.fixture(params=_adr_files(), ids=lambda p: p.name)
    def adr_path(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_has_title_heading(self, adr_path: Path) -> None:
        content = adr_path.read_text()
        assert content.startswith("# ADR-"), (
            f"{adr_path.name} must start with '# ADR-NNNN: Title'"
        )

    def test_has_status_metadata(self, adr_path: Path) -> None:
        content = adr_path.read_text()
        match = re.search(r"\*\*Status:\*\*\s*(\w+)", content)
        assert match, f"{adr_path.name} missing **Status:** metadata"
        assert match.group(1) in STATUS_VALUES, (
            f"{adr_path.name} has unrecognised status '{match.group(1)}'"
        )

    def test_has_date_metadata(self, adr_path: Path) -> None:
        content = adr_path.read_text()
        assert re.search(r"\*\*Date:\*\*\s*\d{4}-\d{2}-\d{2}", content), (
            f"{adr_path.name} missing **Date:** YYYY-MM-DD metadata"
        )

    def test_has_required_sections(self, adr_path: Path) -> None:
        content = adr_path.read_text()
        for section in REQUIRED_SECTIONS:
            assert section in content, (
                f"{adr_path.name} missing required section '{section}'"
            )

    def test_required_sections_are_non_empty(self, adr_path: Path) -> None:
        content = adr_path.read_text()
        for section in REQUIRED_SECTIONS:
            idx = content.find(section)
            if idx == -1:
                pytest.skip(f"Section '{section}' not found")
            after = content[idx + len(section) :]
            next_heading = re.search(r"\n## ", after)
            body = after[: next_heading.start()] if next_heading else after
            stripped = body.strip()
            assert len(stripped) > 10, (
                f"{adr_path.name} section '{section}' is too short"
            )


class TestADRReadmeIndex:
    """Validate that the README index lists all ADR files."""

    def test_all_adr_files_listed_in_readme(self) -> None:
        readme = (ADR_DIR / "README.md").read_text()
        for adr_file in _adr_files():
            assert adr_file.name in readme, (
                f"{adr_file.name} is not listed in docs/adr/README.md index"
            )

    def test_readme_links_are_not_broken(self) -> None:
        readme = (ADR_DIR / "README.md").read_text()
        links = re.findall(r"\[(\d{4})\]\(([^)]+)\)", readme)
        for number, filename in links:
            path = ADR_DIR / filename
            assert path.exists(), f"README links to {filename} but file does not exist"
            assert number in filename, (
                f"README link number {number} does not match filename {filename}"
            )


class TestADR0018ScreenshotPipeline:
    """Specific content tests for ADR-0018."""

    @pytest.fixture
    def content(self) -> str:
        return (ADR_DIR / "0018-screenshot-capture-pipeline.md").read_text()

    def test_links_to_source_memory(self, content: str) -> None:
        assert "#1734" in content, "ADR-0018 must reference source memory #1734"

    def test_links_to_adr_issue(self, content: str) -> None:
        assert "#1749" in content, "ADR-0018 must reference ADR issue #1749"

    def test_documents_frontend_redaction(self, content: str) -> None:
        assert "data-sensitive" in content
        assert "redactSensitiveElements" in content

    def test_documents_fallback_strategy(self, content: str) -> None:
        assert "fallback" in content.lower()
        assert "html2canvas" in content

    def test_documents_backend_scan(self, content: str) -> None:
        assert "scan_base64_for_secrets" in content
        assert "screenshot_scanner" in content

    def test_documents_gist_visibility(self, content: str) -> None:
        assert "screenshot_gist_public" in content
        assert "upload_screenshot_gist" in content

    def test_documents_config_knobs(self, content: str) -> None:
        assert "screenshot_redaction_enabled" in content
        assert "HYDRAFLOW_SCREENSHOT_REDACTION_ENABLED" in content
        assert "HYDRAFLOW_SCREENSHOT_GIST_PUBLIC" in content
