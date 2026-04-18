"""Detect programming languages in a target-repo worktree from marker files.

Used by the plugin skill registry to decide which Tier-2 language-conditional
plugins to load for a given repo. See
``docs/superpowers/specs/2026-04-18-dynamic-plugin-skill-registry-design.md``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("hydraflow.language_detector")

# Language → list of literal marker filenames that indicate the language.
_LITERAL_MARKERS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "setup.py", "requirements.txt"),
    "typescript": ("tsconfig.json",),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
}

# Language → list of glob patterns to match (for files like *.csproj).
_GLOB_MARKERS: dict[str, tuple[str, ...]] = {
    "csharp": ("*.csproj", "*.sln"),
}


def detect_languages(repo_root: Path) -> set[str]:
    """Return the set of languages detected in ``repo_root``.

    Detection is marker-based and non-recursive (top-level only).
    Returns an empty set if ``repo_root`` does not exist.
    """
    if not repo_root.is_dir():
        return set()

    detected: set[str] = set()

    for language, markers in _LITERAL_MARKERS.items():
        for marker in markers:
            if (repo_root / marker).is_file():
                detected.add(language)
                break

    for language, patterns in _GLOB_MARKERS.items():
        for pattern in patterns:
            if any(repo_root.glob(pattern)):
                detected.add(language)
                break

    if (repo_root / "package.json").is_file() and _package_json_uses_typescript(
        repo_root / "package.json"
    ):
        detected.add("typescript")

    return detected


def _package_json_uses_typescript(path: Path) -> bool:
    """Return True if package.json declares typescript in deps or devDeps."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    for key in ("dependencies", "devDependencies"):
        deps = data.get(key, {})
        if isinstance(deps, dict) and "typescript" in deps:
            return True
    return False
