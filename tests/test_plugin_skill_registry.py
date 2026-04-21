"""Tests for plugin skill discovery and prompt formatting."""

from __future__ import annotations

from pathlib import Path

import pytest

from plugin_skill_registry import (
    PluginSkill,
    discover_plugin_skills,
    format_plugin_skills_for_prompt,
)
from tests.conftest import write_plugin_skill as _write_skill


@pytest.fixture(autouse=True)
def _reset_skill_cache():
    """Clear the discovery cache before every test to prevent cross-test leakage."""
    from plugin_skill_registry import clear_plugin_skill_cache

    clear_plugin_skill_cache()
    yield
    clear_plugin_skill_cache()


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    root.mkdir()
    return root


class TestDiscoverPluginSkills:
    """Verify discover_plugin_skills scans the cache correctly."""

    def test_finds_skills_in_allowlisted_plugins(self, cache_root: Path) -> None:
        """Return skills from allowlisted plugins with qualified names."""
        _write_skill(cache_root, "official", "superpowers", "brainstorming")
        _write_skill(cache_root, "official", "superpowers", "writing-plans")

        result = discover_plugin_skills(["superpowers"], cache_root=cache_root)

        names = {s.qualified_name for s in result}
        assert names == {"superpowers:brainstorming", "superpowers:writing-plans"}

    def test_skips_non_allowlisted_plugins(self, cache_root: Path) -> None:
        """Omit plugins that are not in the allowlist."""
        _write_skill(cache_root, "official", "superpowers", "brainstorming")
        _write_skill(cache_root, "official", "other-plugin", "some-skill")

        result = discover_plugin_skills(["superpowers"], cache_root=cache_root)

        assert {s.plugin for s in result} == {"superpowers"}

    def test_parses_folded_multiline_description(self, cache_root: Path) -> None:
        """Join indented continuation lines of a description with spaces."""
        _write_skill(
            cache_root,
            "official",
            "superpowers",
            "multi",
            frontmatter=(
                "name: multi\n"
                "description: First line of description\n"
                "  continues here\n"
                "  and here"
            ),
        )

        result = discover_plugin_skills(["superpowers"], cache_root=cache_root)

        assert len(result) == 1
        assert (
            result[0].description == "First line of description continues here and here"
        )

    def test_skips_malformed_frontmatter(
        self, cache_root: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Skip skills whose SKILL.md lacks name or description and warn."""
        _write_skill(cache_root, "official", "superpowers", "good")
        _write_skill(
            cache_root,
            "official",
            "superpowers",
            "missing-desc",
            frontmatter="name: broken",
        )

        with caplog.at_level("WARNING"):
            result = discover_plugin_skills(["superpowers"], cache_root=cache_root)

        assert {s.name for s in result} == {"good"}
        assert any("missing-desc" in record.message for record in caplog.records)

    def test_filters_using_superpowers_meta_skill(self, cache_root: Path) -> None:
        """Always exclude the using-superpowers meta-skill."""
        _write_skill(cache_root, "official", "superpowers", "brainstorming")
        _write_skill(cache_root, "official", "superpowers", "using-superpowers")

        result = discover_plugin_skills(["superpowers"], cache_root=cache_root)

        assert {s.name for s in result} == {"brainstorming"}

    def test_returns_empty_when_cache_root_missing(self, tmp_path: Path) -> None:
        """Do not raise when the cache root does not exist."""
        missing = tmp_path / "does-not-exist"
        assert discover_plugin_skills(["superpowers"], cache_root=missing) == []

    def test_returns_empty_when_plugin_dir_missing(self, cache_root: Path) -> None:
        """Return empty list when the allowlisted plugin is not installed."""
        assert discover_plugin_skills(["superpowers"], cache_root=cache_root) == []

    def test_handles_plugin_with_no_skills_dir(self, cache_root: Path) -> None:
        """Return empty list when a plugin has no version/skills subdirectory."""
        (cache_root / "official" / "empty-plugin").mkdir(parents=True)
        assert discover_plugin_skills(["empty-plugin"], cache_root=cache_root) == []

    def test_dedupes_skills_across_plugin_versions(self, cache_root: Path) -> None:
        """Return one entry per skill name even when multiple versions exist."""
        _write_skill(
            cache_root,
            "official",
            "frontend-design",
            "frontend-design",
            version="1.0.0",
        )
        _write_skill(
            cache_root,
            "official",
            "frontend-design",
            "frontend-design",
            version="unknown",
        )

        result = discover_plugin_skills(["frontend-design"], cache_root=cache_root)

        assert len(result) == 1
        assert result[0].qualified_name == "frontend-design:frontend-design"

    def test_skips_plugin_version_without_skills_dir(self, cache_root: Path) -> None:
        """Skip version directories that have no skills/ (e.g. commands-only)."""
        # Create one version without skills/ and one with.
        (cache_root / "official" / "multi" / "unknown" / "commands").mkdir(parents=True)
        _write_skill(cache_root, "official", "multi", "real-skill", version="2.0.0")

        result = discover_plugin_skills(["multi"], cache_root=cache_root)

        assert {s.name for s in result} == {"real-skill"}


class TestPluginSkillQualifiedName:
    """Verify the qualified_name property formats correctly."""

    def test_qualified_name_format(self) -> None:
        """qualified_name is 'plugin:name' with a colon separator."""
        skill = PluginSkill(
            plugin="superpowers",
            name="brainstorming",
            description="Use when...",
        )
        assert skill.qualified_name == "superpowers:brainstorming"


def test_format_plugin_skills_for_prompt_carries_discipline_preamble():
    skills = [
        PluginSkill(
            plugin="superpowers",
            name="test-driven-development",
            description="Use when implementing any feature or bugfix",
        ),
    ]
    out = format_plugin_skills_for_prompt(skills)
    assert "## Available Skills" in out
    # Discipline phrasing — subagents need the 1% rule.
    assert "1% confidence" in out
    assert "MUST invoke" in out
    assert "Process skills first" in out
    assert "Implementation skills second" in out
    # Skill body still rendered verbatim from frontmatter.
    assert (
        "**superpowers:test-driven-development** — Use when implementing any feature or bugfix"
        in out
    )


def test_format_plugin_skills_for_prompt_empty_returns_empty_string():
    assert format_plugin_skills_for_prompt([]) == ""


class TestDiscoveryCache:
    """Verify discover_plugin_skills caches results and clear_plugin_skill_cache resets state."""

    def test_second_call_is_cached(self, cache_root: Path) -> None:
        """Repeated calls with the same args do not re-scan the filesystem."""
        from plugin_skill_registry import clear_plugin_skill_cache

        clear_plugin_skill_cache()
        _write_skill(cache_root, "official", "superpowers", "brainstorming")

        first = discover_plugin_skills(["superpowers"], cache_root=cache_root)
        assert len(first) == 1

        # Remove the SKILL.md — cache should still serve the old result.
        (
            cache_root
            / "official"
            / "superpowers"
            / "1.0.0"
            / "skills"
            / "brainstorming"
            / "SKILL.md"
        ).unlink()

        second = discover_plugin_skills(["superpowers"], cache_root=cache_root)
        assert second == first  # cache hit

    def test_clear_cache_forces_rescan(self, cache_root: Path) -> None:
        """clear_plugin_skill_cache drops the cache so next call rescans."""
        from plugin_skill_registry import clear_plugin_skill_cache

        clear_plugin_skill_cache()
        _write_skill(cache_root, "official", "superpowers", "brainstorming")
        discover_plugin_skills(["superpowers"], cache_root=cache_root)

        # Drop the file and clear the cache — now we should see 0.
        (
            cache_root
            / "official"
            / "superpowers"
            / "1.0.0"
            / "skills"
            / "brainstorming"
            / "SKILL.md"
        ).unlink()
        clear_plugin_skill_cache()

        assert discover_plugin_skills(["superpowers"], cache_root=cache_root) == []
