from __future__ import annotations

from pathlib import Path

from scripts.bundle_assets import bundle_assets

from hf_cli.assets_manifest import ASSET_PATHS


def test_assets_bundle_contains_manifest_entries(tmp_path: Path) -> None:
    """bundle_assets should package every manifest path deterministically."""
    repo_root = Path(__file__).resolve().parents[2]
    first = tmp_path / "assets-1.tar.gz"
    second = tmp_path / "assets-2.tar.gz"

    bundle_assets(first, repo_root)
    bundle_assets(second, repo_root)

    assert first.read_bytes() == second.read_bytes(), "bundle must be deterministic"

    import tarfile

    with tarfile.open(first) as tar:
        names = [Path(member.name) for member in tar.getmembers()]

    for rel_path in ASSET_PATHS:
        assert any(
            entry == rel_path or str(entry).startswith(f"{rel_path}/")
            for entry in names
        ), f"{rel_path} missing from bundled assets"
