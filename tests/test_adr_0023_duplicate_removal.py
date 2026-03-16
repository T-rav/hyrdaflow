"""Tests verifying duplicate ADR-0023 (gate-triage-call-not-hitl-fallback) was removed."""

from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"


class TestDuplicateAdrRemoval:
    """Verify the duplicate ADR file is gone and the README is consistent."""

    def test_duplicate_adr_file_does_not_exist(self) -> None:
        duplicate = ADR_DIR / "0023-gate-triage-call-not-hitl-fallback.md"
        assert not duplicate.exists(), f"Duplicate ADR should be removed: {duplicate}"

    def test_canonical_adr_still_exists(self) -> None:
        canonical = ADR_DIR / "0023-auto-triage-toggle-must-gate-routing.md"
        assert canonical.exists(), f"Canonical ADR must remain: {canonical}"

    def test_readme_has_no_reference_to_duplicate(self) -> None:
        readme = ADR_DIR / "README.md"
        content = readme.read_text()
        assert "gate-triage-call-not-hitl-fallback" not in content

    def test_readme_retains_canonical_entry(self) -> None:
        readme = ADR_DIR / "README.md"
        content = readme.read_text()
        assert "0023-auto-triage-toggle-must-gate-routing.md" in content
