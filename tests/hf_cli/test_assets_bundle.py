from __future__ import annotations

import tarfile
from pathlib import Path
from typing import NamedTuple

from scripts.bundle_assets import bundle_assets

from hf_cli.assets_manifest import ASSET_PATHS


class _TarEntry(NamedTuple):
    name: str
    payload: bytes | None


def _snapshot(archive: Path) -> list[_TarEntry]:
    with tarfile.open(archive) as tar:
        entries: list[_TarEntry] = []
        for member in sorted(tar.getmembers(), key=lambda m: m.name):
            if member.isdir():
                entries.append(_TarEntry(member.name, None))
                continue
            raw = tar.extractfile(member)
            assert raw is not None
            entries.append(_TarEntry(member.name, raw.read()))
    return entries


def test_assets_bundle_contains_manifest_entries(tmp_path: Path) -> None:
    """bundle_assets should package every manifest path deterministically."""
    repo_root = Path(__file__).resolve().parents[2]
    first = tmp_path / "assets-1.tar.gz"
    second = tmp_path / "assets-2.tar.gz"

    bundle_assets(first, repo_root)
    bundle_assets(second, repo_root)

    assert _snapshot(first) == _snapshot(second), "bundle must be deterministic"

    names = [Path(entry.name) for entry in _snapshot(first)]
    for rel_path in ASSET_PATHS:
        assert any(
            entry == rel_path or str(entry).startswith(f"{rel_path}/")
            for entry in names
        ), f"{rel_path} missing from bundled assets"
