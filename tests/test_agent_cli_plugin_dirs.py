"""Tests for agent_cli._plugin_dir_flags — dynamic --plugin-dir emission."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import agent_cli


def _with_plugin_root(root: Path):
    """Patch the module's _PRE_CLONED_PLUGIN_ROOT to point at ``root``."""
    return patch.object(agent_cli, "_PRE_CLONED_PLUGIN_ROOT", root)


def test_missing_root_emits_no_flags(tmp_path: Path):
    # tmp_path exists but we point at a child that doesn't.
    with _with_plugin_root(tmp_path / "does-not-exist"):
        assert agent_cli._plugin_dir_flags() == []


def test_root_not_a_directory_emits_no_flags(tmp_path: Path):
    # Path exists but is a file, not a directory.
    file_path = tmp_path / "plugins-not-dir"
    file_path.write_text("")
    with _with_plugin_root(file_path):
        assert agent_cli._plugin_dir_flags() == []


def test_empty_root_emits_no_flags(tmp_path: Path):
    root = tmp_path / "plugins"
    root.mkdir()
    with _with_plugin_root(root):
        assert agent_cli._plugin_dir_flags() == []


def test_emits_flag_for_each_subdirectory_sorted(tmp_path: Path):
    root = tmp_path / "plugins"
    root.mkdir()
    for name in ["superpowers", "claude-plugins-official", "lightfactory"]:
        (root / name).mkdir()
    with _with_plugin_root(root):
        flags = agent_cli._plugin_dir_flags()
    # Alphabetical order, two tokens per plugin (--plugin-dir PATH).
    assert flags == [
        "--plugin-dir",
        str(root / "claude-plugins-official"),
        "--plugin-dir",
        str(root / "lightfactory"),
        "--plugin-dir",
        str(root / "superpowers"),
    ]


def test_non_directory_entries_ignored(tmp_path: Path):
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "real-plugin").mkdir()
    (root / "README.md").write_text("not a plugin dir")
    with _with_plugin_root(root):
        flags = agent_cli._plugin_dir_flags()
    assert flags == ["--plugin-dir", str(root / "real-plugin")]


def test_pre_cloned_root_constant_points_at_opt_plugins():
    # Regression guard: Dockerfile.agent-base places plugins at /opt/plugins.
    # Any change to that baked-in path must also update this constant.
    assert Path("/opt/plugins") == agent_cli._PRE_CLONED_PLUGIN_ROOT
