"""Implementation of the `hf init` command."""

from __future__ import annotations

import argparse
import tarfile
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

_GITIGNORE_ENTRY = ".hydraflow/prep"


def _extract_assets(target: Path, force: bool) -> tuple[int, int]:
    asset_path = resources.files("hf_cli").joinpath("assets.tar.gz")
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
