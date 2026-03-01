"""Tests for ADR-0010: Worktree and Path Isolation Architecture."""

from __future__ import annotations

from pathlib import Path

import pytest

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"
ADR_FILE = ADR_DIR / "0010-worktree-and-path-isolation.md"
README_FILE = ADR_DIR / "README.md"


@pytest.fixture()
def adr_content() -> str:
    """Read the ADR file content."""
    return ADR_FILE.read_text()


@pytest.fixture()
def readme_content() -> str:
    """Read the README index content."""
    return README_FILE.read_text()


class TestADR0010Exists:
    """Verify the ADR file and README entry exist."""

    def test_adr_file_exists(self) -> None:
        assert ADR_FILE.exists(), f"ADR file not found at {ADR_FILE}"

    def test_readme_references_adr(self, readme_content: str) -> None:
        assert "0010" in readme_content
        assert "0010-worktree-and-path-isolation.md" in readme_content


class TestADR0010Metadata:
    """Verify required ADR metadata fields."""

    def test_has_title(self, adr_content: str) -> None:
        assert "# ADR-0010:" in adr_content

    def test_has_status(self, adr_content: str) -> None:
        assert "**Status:** Proposed" in adr_content

    def test_has_date(self, adr_content: str) -> None:
        assert "**Date:** 2026-02-28" in adr_content


class TestADR0010RequiredSections:
    """Verify all required ADR sections are present."""

    def test_has_context_section(self, adr_content: str) -> None:
        assert "## Context" in adr_content

    def test_has_decision_section(self, adr_content: str) -> None:
        assert "## Decision" in adr_content

    def test_has_consequences_section(self, adr_content: str) -> None:
        assert "## Consequences" in adr_content

    def test_has_positive_consequences(self, adr_content: str) -> None:
        assert "**Positive:**" in adr_content

    def test_has_tradeoffs(self, adr_content: str) -> None:
        assert "**Trade-offs:**" in adr_content

    def test_has_related_section(self, adr_content: str) -> None:
        assert "## Related" in adr_content


class TestADR0010SourceReferences:
    """Verify the ADR links back to source memory and related issues."""

    def test_references_source_memory_issue(self, adr_content: str) -> None:
        assert "#1635" in adr_content

    def test_references_implementation_issue(self, adr_content: str) -> None:
        assert "#1677" in adr_content

    def test_references_related_adr_0003(self, adr_content: str) -> None:
        assert "ADR-0003" in adr_content

    def test_references_related_adr_0006(self, adr_content: str) -> None:
        assert "ADR-0006" in adr_content


class TestADR0010KeyContent:
    """Verify the ADR captures the essential architectural details."""

    def test_mentions_worktree_base_default(self, adr_content: str) -> None:
        assert "worktree_base" in adr_content

    def test_mentions_repo_slug_scoping(self, adr_content: str) -> None:
        assert "repo_slug" in adr_content

    def test_mentions_collision_risk(self, adr_content: str) -> None:
        assert "collision" in adr_content.lower()

    def test_mentions_log_dir(self, adr_content: str) -> None:
        assert "log_dir" in adr_content

    def test_mentions_plans_dir(self, adr_content: str) -> None:
        assert "plans_dir" in adr_content

    def test_mentions_config_py(self, adr_content: str) -> None:
        assert "config.py" in adr_content

    def test_mentions_worktree_manager(self, adr_content: str) -> None:
        assert "WorktreeManager" in adr_content

    def test_mentions_docker_mounts(self, adr_content: str) -> None:
        assert "DockerRunner" in adr_content or "docker" in adr_content.lower()

    def test_mentions_metrics_manager_pattern(self, adr_content: str) -> None:
        assert "metrics" in adr_content.lower()

    def test_has_alternatives_considered(self, adr_content: str) -> None:
        assert "## Alternatives considered" in adr_content
