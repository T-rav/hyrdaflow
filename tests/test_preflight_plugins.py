"""Tests for the plugin preflight check."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig
from preflight import CheckStatus, _check_plugins


def _make_plugin(cache_root: Path, plugin: str, skill: str = "some-skill") -> None:
    """Create a minimal plugin with one well-formed skill."""
    skill_dir = cache_root / "official" / plugin / "skills" / skill
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: A skill description\n---\n\nBody.\n"
    )


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    root.mkdir()
    return root


class TestCheckPlugins:
    """Verify _check_plugins gates on allowlist + skill count."""

    def test_passes_when_all_required_present(self, cache_root: Path) -> None:
        """PASS when every Tier-1 plugin exists and at least one skill loads."""
        _make_plugin(cache_root, "superpowers")
        _make_plugin(cache_root, "code-review")

        config = HydraFlowConfig(
            required_plugins=["superpowers", "code-review"],
            language_plugins={},
        )
        result = _check_plugins(config, cache_root=cache_root, detected_languages=set())

        assert result.status == CheckStatus.PASS

    def test_fails_when_tier1_plugin_missing(self, cache_root: Path) -> None:
        """FAIL when a Tier-1 plugin directory is not present."""
        _make_plugin(cache_root, "superpowers")

        config = HydraFlowConfig(
            required_plugins=["superpowers", "code-review"],
            language_plugins={},
        )
        result = _check_plugins(config, cache_root=cache_root, detected_languages=set())

        assert result.status == CheckStatus.FAIL
        assert "code-review" in result.message

    def test_fails_when_zero_skills_discovered(self, cache_root: Path) -> None:
        """FAIL when the allowlisted plugin has no skills."""
        (cache_root / "official" / "superpowers").mkdir(parents=True)

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={},
        )
        result = _check_plugins(config, cache_root=cache_root, detected_languages=set())

        assert result.status == CheckStatus.FAIL
        assert "0 skills" in result.message

    def test_warns_when_tier2_missing_and_language_detected(
        self, cache_root: Path
    ) -> None:
        """WARN when a language-conditional plugin is missing for a detected language."""
        _make_plugin(cache_root, "superpowers")

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={"python": ["pyright-lsp"]},
        )
        result = _check_plugins(
            config, cache_root=cache_root, detected_languages={"python"}
        )

        assert result.status == CheckStatus.WARN
        assert "pyright-lsp" in result.message

    def test_silent_when_tier2_missing_and_language_absent(
        self, cache_root: Path
    ) -> None:
        """PASS silently when a Tier-2 plugin is missing but its language was not detected."""
        _make_plugin(cache_root, "superpowers")

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={"python": ["pyright-lsp"]},
        )
        result = _check_plugins(config, cache_root=cache_root, detected_languages=set())

        assert result.status == CheckStatus.PASS
