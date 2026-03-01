from __future__ import annotations

from pathlib import Path

from hf_cli.assets_manifest import ASSET_PATHS


def test_assets_manifest_paths_exist_in_repo() -> None:
    """Manifest entries should point to real source assets in the repo tree."""
    repo_root = Path(__file__).resolve().parents[2]
    missing = [str(path) for path in ASSET_PATHS if not (repo_root / path).exists()]
    assert not missing, f"Missing asset paths referenced in manifest: {missing}"


def test_assets_manifest_entries_are_relative() -> None:
    """Manifest entries must remain relative paths."""
    assert all(not path.is_absolute() for path in ASSET_PATHS)
