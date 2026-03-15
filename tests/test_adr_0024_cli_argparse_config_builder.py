"""Tests for ADR-0024: CLI argparse config builder pattern.

Validates the council-requested changes:
1. Renumbered from 0023 to 0024 (no file collision)
2. Naming accuracy: cli_explicit_fields used correctly
3. Forward-looking qualifier for feature-branch files
4. Status set to Deferred
"""

from __future__ import annotations

from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
ADR_FILE = ADR_DIR / "0024-cli-argparse-config-builder-pattern.md"


class TestAdr0024Renumbering:
    """Verify the ADR was renumbered from 0023 to 0024."""

    def test_old_0023_file_does_not_exist(self) -> None:
        old = ADR_DIR / "0023-cli-argparse-config-builder-pattern.md"
        assert not old.exists(), "Old ADR-0023 cli file should have been removed"

    def test_new_0024_file_exists(self) -> None:
        assert ADR_FILE.exists(), "ADR-0024 cli file must exist"

    def test_heading_contains_adr_0024(self) -> None:
        text = ADR_FILE.read_text()
        assert "# ADR-0024:" in text, "Heading must reference ADR-0024"

    def test_no_other_0024_collision(self) -> None:
        matches = list(ADR_DIR.glob("0024-*.md"))
        assert len(matches) == 1, (
            f"Expected exactly one 0024 ADR, found {len(matches)}: {matches}"
        )


class TestAdr0024NamingAccuracy:
    """Verify cli_explicit vs cli_explicit_fields distinction."""

    def test_uses_cli_explicit_fields_for_config_field(self) -> None:
        text = ADR_FILE.read_text()
        assert "cli_explicit_fields" in text, (
            "ADR must reference the actual config field name cli_explicit_fields"
        )

    def test_no_bare_cli_explicit_as_set_name(self) -> None:
        """The ADR should not refer to a bare 'cli_explicit set' — the config
        field is cli_explicit_fields (a frozenset)."""
        text = ADR_FILE.read_text()
        assert "`cli_explicit` set)" not in text, (
            "Should not reference 'cli_explicit set' — the field is cli_explicit_fields"
        )
        assert "`cli_explicit` tracking" not in text, (
            "Should not reference 'cli_explicit tracking' — the field is cli_explicit_fields"
        )


class TestAdr0024ForwardLooking:
    """Verify forward-looking qualifier for feature-branch files."""

    def test_status_is_deferred(self) -> None:
        text = ADR_FILE.read_text()
        assert "**Status:** Deferred" in text, "Status must be Deferred"

    def test_forward_looking_note_present(self) -> None:
        text = ADR_FILE.read_text()
        assert "feature branch" in text.lower(), (
            "ADR must contain a forward-looking note about feature branch"
        )

    def test_cli_py_marked_as_feature_branch(self) -> None:
        text = ADR_FILE.read_text()
        # The Related section should note src/cli.py is on a feature branch
        assert "feature branch" in text, (
            "src/cli.py reference must note it's on a feature branch"
        )

    @pytest.mark.parametrize("filename", ["src/cli.py", "src/hf_cli/__main__.py"])
    def test_feature_branch_files_annotated(self, filename: str) -> None:
        text = ADR_FILE.read_text()
        # Find the line mentioning this file and verify it has a feature branch note
        lines = text.split("\n")
        file_lines = [line for line in lines if filename in line]
        assert file_lines, f"{filename} should be referenced in the ADR"
        annotated = any("feature branch" in line.lower() for line in file_lines)
        # Also accept a top-level note that covers both files
        has_top_note = "feature branch" in text[:500].lower()
        assert annotated or has_top_note, (
            f"{filename} must be annotated as being on a feature branch"
        )
