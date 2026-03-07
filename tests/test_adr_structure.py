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


def _readme_index_entries() -> dict[str, dict[str, str]]:
    """Parse README index rows into a mapping keyed by ADR number."""
    entries: dict[str, dict[str, str]] = {}
    readme_lines = (ADR_DIR / "README.md").read_text().splitlines()
    for line in readme_lines:
        stripped = line.strip()
        if not stripped.startswith("| ["):
            continue
        columns = [col.strip() for col in stripped.strip("|").split("|")]
        if len(columns) < 3:
            continue
        match = re.search(r"\[(\d{4})\]\(([^)]+)\)", columns[0])
        if not match:
            continue
        number = match.group(1)
        filename = match.group(2)
        status = columns[-1]
        entries[number] = {"filename": filename, "status": status}
    return entries


def _status_from_file(path: Path) -> str:
    """Extract the full status string from an ADR markdown file."""
    content = path.read_text()
    match = re.search(r"\*\*Status:\*\*\s*(.+)", content)
    if not match:
        pytest.fail(f"{path.name} missing **Status:** metadata")
    return match.group(1).strip()


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
        match = re.search(r"\*\*Status:\*\*\s*(.+)", content)
        assert match, f"{adr_path.name} missing **Status:** metadata"
        status = match.group(1).strip()
        assert status in STATUS_VALUES, (
            f"{adr_path.name} has unrecognised status '{status}'"
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
                pytest.fail(f"Section '{section}' not found")
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
        entries = _readme_index_entries()
        missing_numbers: list[str] = []
        filename_mismatches: list[str] = []
        for adr_file in _adr_files():
            number = adr_file.stem.split("-")[0]
            entry = entries.get(number)
            if not entry:
                missing_numbers.append(number)
                continue
            if entry["filename"] != adr_file.name:
                filename_mismatches.append(
                    f"ADR-{number}: README links to {entry['filename']} but file is {adr_file.name}"
                )
        if missing_numbers:
            pytest.fail(
                "README missing ADRs: "
                + ", ".join(f"ADR-{num}" for num in missing_numbers)
            )
        if filename_mismatches:
            pytest.fail("Filename mismatches:\n" + "\n".join(filename_mismatches))

    def test_readme_links_are_not_broken(self) -> None:
        for number, entry in _readme_index_entries().items():
            path = ADR_DIR / entry["filename"]
            assert path.exists(), (
                f"README links to {entry['filename']} for ADR-{number} but file does not exist"
            )
            assert entry["filename"].startswith(number), (
                f"README link number {number} does not match filename {entry['filename']}"
            )

    def test_readme_statuses_match_adr_files(self) -> None:
        mismatches: list[str] = []
        entries = _readme_index_entries()
        for number, entry in sorted(entries.items()):
            path = ADR_DIR / entry["filename"]
            if not path.exists():
                # File existence is validated separately.
                continue
            file_status = _status_from_file(path)
            readme_status = entry["status"]
            if file_status != readme_status:
                mismatches.append(
                    f"ADR-{number}: README '{readme_status}' vs file '{file_status}'"
                )
        if mismatches:
            pytest.fail("Status mismatches detected:\n" + "\n".join(mismatches))

    def test_no_unindexed_adr_files(self) -> None:
        """Ensure every ADR markdown file has an index entry."""
        entries = _readme_index_entries()
        indexed_filenames = {info["filename"] for info in entries.values()}
        missing = [
            path.name for path in _adr_files() if path.name not in indexed_filenames
        ]
        if missing:
            pytest.fail(
                "ADR files missing from README index:\n" + "\n".join(sorted(missing))
            )
