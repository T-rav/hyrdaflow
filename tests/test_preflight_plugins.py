"""Tests for the plugin preflight check."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig
from preflight import CheckStatus, _check_plugins


@pytest.fixture(autouse=True)
def _reset_skill_cache():
    """Clear the discovery cache before every test to prevent cross-test leakage."""
    from plugin_skill_registry import clear_plugin_skill_cache

    clear_plugin_skill_cache()
    yield
    clear_plugin_skill_cache()


def _make_plugin(cache_root: Path, plugin: str, skill: str = "some-skill") -> None:
    """Create a minimal plugin with one well-formed skill (thin wrapper around shared helper)."""
    from tests.conftest import write_plugin_skill

    write_plugin_skill(cache_root, "official", plugin, skill)


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
        """FAIL when a Tier-1 plugin directory is not present.

        With ``auto_install_plugins=False`` the check must not touch subprocess
        and falls through to the rich manual-fix FAIL message.
        """
        _make_plugin(cache_root, "superpowers")

        config = HydraFlowConfig(
            required_plugins=["superpowers", "code-review"],
            language_plugins={},
            auto_install_plugins=False,
        )
        result = _check_plugins(config, cache_root=cache_root, detected_languages=set())

        assert result.status == CheckStatus.FAIL
        assert "code-review" in result.message
        assert "claude plugin install" in result.message

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
        """WARN when a language-conditional plugin is missing for a detected language.

        ``auto_install_plugins=False`` keeps this a pure unit test — we do not
        want to shell out to ``claude plugin install`` here.
        """
        _make_plugin(cache_root, "superpowers")

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={"python": ["pyright-lsp"]},
            auto_install_plugins=False,
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

    def test_fails_when_cache_root_is_file(self, tmp_path: Path) -> None:
        """FAIL when cache_root exists but is a regular file, not a directory."""
        cache_file = tmp_path / "cache"
        cache_file.write_text("not a dir")

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={},
        )
        result = _check_plugins(config, cache_root=cache_file, detected_languages=set())

        assert result.status == CheckStatus.FAIL
        assert "not a directory" in result.message

    def test_warn_message_includes_language_context(self, cache_root: Path) -> None:
        """WARN message identifies which language triggered the missing plugin.

        ``auto_install_plugins=False`` keeps this a pure unit test — we do not
        want to shell out to ``claude plugin install`` here.
        """
        _make_plugin(cache_root, "superpowers")

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={"python": ["pyright-lsp"]},
            auto_install_plugins=False,
        )
        result = _check_plugins(
            config, cache_root=cache_root, detected_languages={"python"}
        )

        assert result.status == CheckStatus.WARN
        assert "for python" in result.message
        assert "pyright-lsp" in result.message


class TestRunPreflightChecksWiring:
    """Verify _check_plugins is invoked by run_preflight_checks."""

    @pytest.mark.asyncio
    async def test_plugin_check_appears_in_results_with_pass_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_preflight_checks invokes _check_plugins with the shared default cache root.

        Isolated by monkeypatching plugin_skill_registry._DEFAULT_CACHE_ROOT so the
        test does not depend on the developer's real ~/.claude/plugins/cache.
        """
        import plugin_skill_registry
        from preflight import run_preflight_checks

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        _make_plugin(cache_root, "superpowers")
        monkeypatch.setattr(plugin_skill_registry, "_DEFAULT_CACHE_ROOT", cache_root)

        config = HydraFlowConfig(
            required_plugins=["superpowers"],
            language_plugins={},
            repo_root=str(tmp_path),
            data_root=str(tmp_path),
        )
        results = await run_preflight_checks(config)
        plugin_result = next(r for r in results if r.name == "plugins")
        assert plugin_result.status == CheckStatus.PASS
