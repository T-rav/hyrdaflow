"""Implementation of the `hf init` command."""

from __future__ import annotations

import argparse
import base64
import io
import logging
import tarfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from hf_cli.assets_manifest import ASSET_PATHS

try:
    from . import embedded_assets
except ImportError:  # pragma: no cover - optional module
    embedded_assets = None

_GITIGNORE_ENTRY = ".hydraflow/prep"
logger = logging.getLogger("hydraflow.hf_cli.init")


def _detect_repo_root() -> Path:
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if all((candidate / rel).exists() for rel in ASSET_PATHS):
            return candidate
    # Conservative fallback for standard src/hf_cli layout.
    return module_path.parents[2]


def _extract_assets_from_fileobj(
    target: Path, force: bool, fileobj: BinaryIO
) -> tuple[int, int]:
    created = 0
    skipped = 0
    rejected = 0
    with tarfile.open(fileobj=fileobj) as tar:
        for member in tar.getmembers():
            rel = PurePosixPath(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                rejected += 1
                logger.warning("Skipping unsafe archive entry: %s", member.name)
                continue
            dest = (target / Path(*rel.parts)).resolve()
            try:
                dest.relative_to(target)
            except ValueError:
                rejected += 1
                logger.warning("Skipping escaping archive entry: %s", member.name)
                continue
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                rejected += 1
                logger.warning(
                    "Skipping unsupported archive entry type: %s", member.name
                )
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
    if rejected:
        logger.info("Skipped %d unsafe/unsupported archive entries", rejected)
    return created, skipped


def _extract_assets_from_embedded_data(target: Path, force: bool) -> tuple[int, int]:
    if embedded_assets is None:
        return 0, 0
    data = getattr(embedded_assets, "ASSET_ARCHIVE_B64", "").strip()
    if not data:
        return 0, 0
    buffer = io.BytesIO(base64.b64decode(data))
    return _extract_assets_from_fileobj(target, force, buffer)


def _extract_assets_from_source_tree(target: Path, force: bool) -> tuple[int, int]:
    repo_root = _detect_repo_root()
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
    embedded_created, embedded_skipped = _extract_assets_from_embedded_data(
        target, force
    )
    if embedded_created or embedded_skipped:
        return embedded_created, embedded_skipped
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
