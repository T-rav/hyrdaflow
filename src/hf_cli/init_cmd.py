"""Implementation of the `hf init` command."""

from __future__ import annotations

import argparse
import tarfile
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from hf_cli.assets_manifest import ASSET_PATHS

_GITIGNORE_ENTRY = ".hydraflow/prep"


def _extract_assets_from_archive(
    target: Path, force: bool, asset_path: Path
) -> tuple[int, int]:
    created = 0
    skipped = 0
    with tarfile.open(str(asset_path)) as tar:
        for member in tar.getmembers():
            dest = target / member.name
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if dest.exists() and not force:
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            raw = tar.extractfile(member)
            assert raw is not None
            with raw as src, open(dest, "wb") as dst:
                dst.write(src.read())
            created += 1
    return created, skipped


def _extract_assets_from_source_tree(target: Path, force: bool) -> tuple[int, int]:
    repo_root = Path(__file__).resolve().parents[1]
    created = 0
    skipped = 0
    for rel_path in ASSET_PATHS:
        src_root = repo_root / rel_path
        if not src_root.exists():
            continue
        if src_root.is_dir():
            for src in sorted(src_root.rglob("*")):
                if src.is_dir():
                    continue
                dest = target / src.relative_to(repo_root)
                if dest.exists() and not force:
                    skipped += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
                created += 1
            continue
        dest = target / rel_path
        if dest.exists() and not force:
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src_root.read_bytes())
        created += 1
    return created, skipped


def _extract_assets(target: Path, force: bool) -> tuple[int, int]:
    asset_entry = resources.files("hf_cli").joinpath("assets.tar.gz")
    if asset_entry.is_file():
        with resources.as_file(asset_entry) as asset_path:
            return _extract_assets_from_archive(target, force, asset_path)
    return _extract_assets_from_source_tree(target, force)


def _ensure_gitignore(target: Path) -> None:
    gitignore = target / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(f"{_GITIGNORE_ENTRY}\n")
        print(f"  created {gitignore} (added {_GITIGNORE_ENTRY})")
        return
    content = gitignore.read_text().splitlines()
    if _GITIGNORE_ENTRY in (line.strip() for line in content):
        return
    with gitignore.open("a") as fh:
        if content and content[-1].strip():
            fh.write("\n")
        fh.write(f"{_GITIGNORE_ENTRY}\n")
    print(f"  updated {gitignore} (added {_GITIGNORE_ENTRY})")


def run_init(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hf init", description="Bootstrap HydraFlow assets in a repo"
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Repository root where assets should be installed (default: current directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    target = args.target.resolve()
    created, skipped = _extract_assets(target, force=args.force)
    _ensure_gitignore(target)
    print(f"Installed hf assets into {target}")
    print(f"  created {created} files, skipped {skipped}")
    return 0
