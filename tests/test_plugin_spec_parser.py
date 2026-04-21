"""Tests for plugin_skill_registry.parse_plugin_spec."""

from __future__ import annotations

import pytest

from plugin_skill_registry import parse_plugin_spec

DEFAULT_MARKETPLACE = "claude-plugins-official"


def test_bare_name_gets_default_marketplace():
    assert parse_plugin_spec("superpowers") == ("superpowers", DEFAULT_MARKETPLACE)


def test_explicit_marketplace():
    assert parse_plugin_spec("craft-plugin@craft") == ("craft-plugin", "craft")


def test_whitespace_stripped():
    assert parse_plugin_spec("  superpowers  ") == ("superpowers", DEFAULT_MARKETPLACE)
    assert parse_plugin_spec("foo @ bar") == ("foo", "bar")


@pytest.mark.parametrize("spec", ["", "@market", "name@", "a@b@c"])
def test_malformed_raises(spec: str):
    with pytest.raises(ValueError):
        parse_plugin_spec(spec)
