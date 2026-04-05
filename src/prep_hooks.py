"""Language detection helpers for target repositories."""

from __future__ import annotations

import json
from pathlib import Path

from polyglot_prep import PYTHON_MARKERS

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def _has_typescript_indicators(package_json: Path) -> bool:
    """Check if a package.json contains TypeScript indicators."""
    try:
        data = json.loads(package_json.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    # Check devDependencies for typescript
    dev_deps = data.get("devDependencies", {})
    if "typescript" in dev_deps:
        return True

    # Check main/types fields for .ts/.tsx extension
    for field in ("main", "types"):
        value = data.get(field, "")
        if isinstance(value, str) and value.endswith((".ts", ".tsx")):
            return True

    return False


def detect_language(repo_root: Path) -> str:
    """Detect the primary language of a repository.

    Returns ``"python"``, ``"javascript"``, ``"typescript"``, or ``"unknown"``.
    """
    # Python markers (checked first — takes precedence)
    for marker in PYTHON_MARKERS:
        if (repo_root / marker).exists():
            return "python"

    # TypeScript (check before plain JS)
    if (repo_root / "tsconfig.json").exists():
        return "typescript"

    package_json = repo_root / "package.json"
    if package_json.exists():
        if _has_typescript_indicators(package_json):
            return "typescript"
        return "javascript"

    return "unknown"
