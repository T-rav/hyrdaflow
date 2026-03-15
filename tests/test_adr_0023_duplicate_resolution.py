"""Tests for ADR-0023 duplicate resolution (#2731).

Verifies that the duplicate ADR (gate-triage-call-not-hitl-fallback) was
properly superseded and its unique content merged into the survivor ADR
(auto-triage-toggle-must-gate-routing).
"""

from __future__ import annotations

from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
DUPLICATE = ADR_DIR / "0023-gate-triage-call-not-hitl-fallback.md"
SURVIVOR = ADR_DIR / "0023-auto-triage-toggle-must-gate-routing.md"
README = ADR_DIR / "README.md"


class TestDuplicateADRSuperseded:
    """The duplicate ADR must be marked Superseded."""

    def test_duplicate_adr_exists_on_disk(self) -> None:
        assert DUPLICATE.exists(), (
            "Duplicate ADR file should still exist (superseded, not deleted)"
        )

    def test_duplicate_adr_status_is_superseded(self) -> None:
        content = DUPLICATE.read_text()
        assert "**Status:** Superseded" in content

    def test_duplicate_adr_references_survivor(self) -> None:
        content = DUPLICATE.read_text()
        assert "0023-auto-triage-toggle-must-gate-routing.md" in content


class TestSurvivorADRMergedContent:
    """The survivor ADR must contain merged content from the duplicate."""

    def test_survivor_has_verification_checklist(self) -> None:
        content = SURVIVOR.read_text()
        assert "### Verification checklist" in content

    def test_survivor_checklist_has_toggle_before_triage(self) -> None:
        content = SURVIVOR.read_text()
        assert "toggle is checked **before** the triage call" in content

    def test_survivor_checklist_has_hitl_without_triage(self) -> None:
        content = SURVIVOR.read_text()
        assert (
            "toggle-off path calls HITL and returns without invoking triage" in content
        )

    def test_survivor_checklist_has_test_toggle_guidance(self) -> None:
        content = SURVIVOR.read_text()
        assert "tests enable the toggle when asserting triage is called" in content

    def test_survivor_references_issue_2731(self) -> None:
        content = SURVIVOR.read_text()
        assert "#2731" in content

    def test_survivor_references_superseded_adr(self) -> None:
        content = SURVIVOR.read_text()
        assert "0023-gate-triage-call-not-hitl-fallback.md" in content


class TestREADMEUpdated:
    """README.md must reflect the superseded status."""

    def test_readme_shows_duplicate_as_superseded(self) -> None:
        content = README.read_text()
        for line in content.splitlines():
            if "gate-triage-call-not-hitl-fallback" in line:
                assert "Superseded" in line
                return
        raise AssertionError("gate-triage-call-not-hitl-fallback not found in README")  # noqa: TRY003
