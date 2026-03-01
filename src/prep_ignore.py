"""Shared ignore policy for prep scaffolding and discovery."""

from __future__ import annotations

import re
from pathlib import Path

PREP_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".github",
        ".hydraflow",
        ".idea",
        ".next",
        ".pytest_cache",
        ".turbo",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "hydra",
        "hydraflow",
        "node_modules",
        "target",
        "venv",
    }
)
"""Directory names prep discovery/scaffolding should ignore."""


def load_git_submodule_roots(repo_root: Path) -> tuple[Path, ...]:
    """Return absolute paths for git submodule roots declared in `.gitmodules`."""
    gitmodules = repo_root / ".gitmodules"
    if not gitmodules.is_file():
        return ()

    roots: list[Path] = []
    try:
        for line in gitmodules.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*path\s*=\s*(.+?)\s*$", line)
            if not match:
                continue
            rel = match.group(1).strip()
            if rel:
                roots.append((repo_root / rel).resolve())
    except OSError:
        return ()
    return tuple(roots)
