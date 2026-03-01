"""Manifest of repo assets bundled with the `hf init` command."""

from __future__ import annotations

from pathlib import Path

# Relative paths (from repo root) to include in the bundled assets archive.
ASSET_PATHS = [
    Path(".claude"),
    Path(".codex"),
    Path(".pi"),
    Path(".githooks"),
]
