"""Tests for ADR-0009: Multi-Repo Process-Per-Repo Model."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_ADR_PATH = _ADR_DIR / "0009-multi-repo-process-per-repo-model.md"
_README_PATH = _ADR_DIR / "README.md"


class TestAdr0009Exists:
    """ADR-0009 file exists and is well-formed."""

    def test_adr_file_exists(self) -> None:
        assert _ADR_PATH.exists(), "ADR-0009 markdown file must exist"

    def test_adr_file_is_not_empty(self) -> None:
        content = _ADR_PATH.read_text()
        assert len(content.strip()) > 0, "ADR-0009 must not be empty"


class TestAdr0009RequiredSections:
    """ADR-0009 contains all required sections per README format."""

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

    def test_has_alternatives_considered(self, content: str) -> None:
        assert "## Alternatives considered" in content

    def test_has_related_section(self, content: str) -> None:
        assert "## Related" in content


class TestAdr0009Content:
    """ADR-0009 captures the process-per-repo architecture accurately."""

    @pytest.fixture()
    def content(self) -> str:
        return _ADR_PATH.read_text()

    def test_title_references_process_per_repo(self, content: str) -> None:
        assert "Process-Per-Repo" in content

    def test_references_supervisor(self, content: str) -> None:
        assert "supervisor" in content.lower()

    def test_references_subprocess_isolation(self, content: str) -> None:
        assert "subprocess" in content.lower()

    def test_references_tcp_protocol(self, content: str) -> None:
        assert "TCP" in content

    def test_references_hydraflow_home(self, content: str) -> None:
        assert "HYDRAFLOW_HOME" in content

    def test_references_source_memory_issue(self, content: str) -> None:
        assert "#1627" in content

    def test_references_repo_slug_scoping(self, content: str) -> None:
        assert "repo_slug" in content

    def test_references_worktree_isolation(self, content: str) -> None:
        assert "worktree" in content.lower()

    def test_status_is_proposed(self, content: str) -> None:
        assert "Proposed" in content

    def test_references_related_adrs(self, content: str) -> None:
        assert "ADR-0001" in content
        assert "ADR-0006" in content


class TestAdr0009InReadmeIndex:
    """ADR-0009 is listed in the README index."""

    @pytest.fixture()
    def readme(self) -> str:
        return _README_PATH.read_text()

    def test_readme_lists_adr_0009(self, readme: str) -> None:
        assert "0009" in readme

    def test_readme_links_to_adr_file(self, readme: str) -> None:
        assert "0009-multi-repo-process-per-repo-model.md" in readme

    def test_readme_shows_proposed_status(self, readme: str) -> None:
        for line in readme.splitlines():
            if "0009" in line:
                assert "Proposed" in line
                break
        else:
            pytest.fail("ADR-0009 entry not found in README index")
