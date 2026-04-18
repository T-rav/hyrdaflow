"""Tests for plugin skill discovery and prompt formatting."""

from __future__ import annotations

from pathlib import Path

import pytest

from plugin_skill_registry import (
    PluginSkill,
    discover_plugin_skills,
)


def _write_skill(
    cache_root: Path,
    marketplace: str,
    plugin: str,
    skill: str,
    *,
    name: str | None = None,
    description: str | None = None,
    frontmatter: str | None = None,
) -> Path:
    """Create a SKILL.md under the cache layout and return its path."""
    skill_dir = cache_root / marketplace / plugin / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    if frontmatter is not None:
        content = f"---\n{frontmatter}\n---\n\nBody here.\n"
    else:
        content = (
            "---\n"
            f"name: {name or skill}\n"
            f"description: {description or f'{skill} description'}\n"
            "---\n\nBody here.\n"
        )
    skill_md.write_text(content)
    return skill_md


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
        """Return empty list when a plugin has no skills/ subdirectory."""
        (cache_root / "official" / "empty-plugin").mkdir(parents=True)
        assert discover_plugin_skills(["empty-plugin"], cache_root=cache_root) == []


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
