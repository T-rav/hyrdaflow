"""Tests for plugin-related fields on HydraFlowConfig."""

from __future__ import annotations

from config import HydraFlowConfig


def test_required_plugins_has_tier1_defaults() -> None:
    config = HydraFlowConfig()
    assert config.required_plugins == [
        "superpowers",
        "code-review",
        "code-simplifier",
        "frontend-design",
        "playwright",
    ]


def test_language_plugins_has_all_five_languages() -> None:
    config = HydraFlowConfig()
    assert set(config.language_plugins.keys()) == {
        "python",
        "typescript",
        "csharp",
        "go",
        "rust",
    }


def test_language_plugins_python_maps_to_pyright_lsp() -> None:
    config = HydraFlowConfig()
    assert config.language_plugins["python"] == ["pyright-lsp"]


def test_required_plugins_override() -> None:
    config = HydraFlowConfig(required_plugins=["superpowers"])
    assert config.required_plugins == ["superpowers"]


def test_language_plugins_override() -> None:
    config = HydraFlowConfig(language_plugins={"python": ["mypy-lsp"]})
    assert config.language_plugins == {"python": ["mypy-lsp"]}
