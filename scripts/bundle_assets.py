"""Build the bundled assets archive used by `hf init`."""

from __future__ import annotations

import argparse
import gzip
import tarfile
from pathlib import Path

from hf_cli.assets_manifest import ASSET_PATHS


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    """Normalize metadata for deterministic archives."""
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = ""
    tarinfo.gname = ""
    tarinfo.mtime = 0
    return tarinfo


def _gather_paths(root: Path, rel_path: Path) -> list[Path]:
    """Return a deterministic, depth-first listing for rel_path under root."""
    abs_path = root / rel_path
    if abs_path.is_dir():
        entries = [rel_path]
        for child in sorted(abs_path.iterdir(), key=lambda p: p.name):
            entries.extend(_gather_paths(root, rel_path / child.name))
        return entries
    return [rel_path]


def bundle_assets(output: Path, root: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for rel_path in ASSET_PATHS:
            abs_path = root / rel_path
            if not abs_path.exists():
                raise FileNotFoundError(f"Asset path missing: {abs_path}")
            for entry in _gather_paths(root, rel_path):
                tar.add(
                    root / entry,
                    arcname=str(entry),
                    recursive=False,
                    filter=_tar_filter,
                )
    print(f"Bundled assets → {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle HydraFlow assets for hf init")
    parser.add_argument(
        "--output",
        default=Path("dist/hf_cli-assets.tar.gz"),
        type=Path,
        help="Path to the generated tar.gz",
    )
    parser.add_argument(
        "--root",
        default=Path.cwd(),
        type=Path,
        help="Repo root containing asset directories",
    )
    args = parser.parse_args()
    bundle_assets(args.output, args.root)


if __name__ == "__main__":
    main()
