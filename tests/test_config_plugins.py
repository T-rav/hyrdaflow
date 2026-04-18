"""Tests for plugin-related fields on HydraFlowConfig."""

from __future__ import annotations

from config import HydraFlowConfig


class TestPluginFields:
    """Tests for the required_plugins and language_plugins fields on HydraFlowConfig."""

    def test_required_plugins_defaults(self) -> None:
        """required_plugins should default to the five tier-1 plugin names."""
        config = HydraFlowConfig()
        assert config.required_plugins == [
            "superpowers",
            "code-review",
            "code-simplifier",
            "frontend-design",
            "playwright",
        ]

    def test_language_plugins_defaults(self) -> None:
        """language_plugins should default to all five language-to-plugin mappings."""
        config = HydraFlowConfig()
        assert config.language_plugins == {
            "python": ["pyright-lsp"],
            "typescript": ["typescript-lsp"],
            "csharp": ["csharp-lsp"],
            "go": ["gopls"],
            "rust": ["rust-analyzer"],
        }

    def test_required_plugins_override(self) -> None:
        """required_plugins should accept a custom list at construction time."""
        config = HydraFlowConfig(required_plugins=["superpowers"])
        assert config.required_plugins == ["superpowers"]

    def test_language_plugins_override(self) -> None:
        """language_plugins should accept a custom mapping at construction time."""
        config = HydraFlowConfig(language_plugins={"python": ["mypy-lsp"]})
        assert config.language_plugins == {"python": ["mypy-lsp"]}
