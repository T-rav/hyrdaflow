"""Pre-commit hook scaffolding for target repositories.

Creates language-appropriate `.githooks/pre-commit` hooks and configures
git to use them.  Designed to be called by the future ``hydraflow prep`` CLI
command (epic #561).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel

from manifest import PYTHON_MARKERS
from subprocess_util import run_subprocess

logger = logging.getLogger("hydraflow.prep_hooks")

# ---------------------------------------------------------------------------
# Hook templates
# ---------------------------------------------------------------------------

_PYTHON_HOOK = """\
#!/bin/sh
ruff check . && ruff format . --check
"""

_JS_HOOK = """\
#!/bin/sh
npx eslint .
"""

_UNKNOWN_HOOK = """\
#!/bin/sh
# Add your lint command here
exit 0
"""

_HOOK_TEMPLATES: dict[str, str] = {
    "python": _PYTHON_HOOK,
    "javascript": _JS_HOOK,
    "typescript": _JS_HOOK,
    "unknown": _UNKNOWN_HOOK,
}

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class PrepHookResult(BaseModel):
    """Outcome of a hook scaffolding operation."""

    created: bool = False
    skipped: bool = False
    warned: bool = False
    language: str = "unknown"
    message: str = ""
    hook_path: Path | None = None


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


# ---------------------------------------------------------------------------
# Hook scaffolding
# ---------------------------------------------------------------------------


def scaffold_pre_commit_hook(
    repo_root: Path, language: str | None = None
) -> PrepHookResult:
    """Create a ``.githooks/pre-commit`` hook with language-appropriate lint commands.

    If *language* is ``None``, auto-detects from the repository contents.
    Skips creation when the hook already exists.  Warns (but still creates)
    when a ``.husky/`` directory is found.
    """
    detected = detect_language(repo_root) if language is None else language
    hook_path = repo_root / ".githooks" / "pre-commit"

    # Skip if hook already exists
    if hook_path.exists():
        return PrepHookResult(
            skipped=True,
            language=detected,
            message=f"Pre-commit hook already exists at {hook_path}",
            hook_path=hook_path,
        )

    # Warn if Husky is present
    warned = False
    warn_msg = ""
    if (repo_root / ".husky").is_dir():
        warned = True
        warn_msg = "Existing .husky/ directory found; creating .githooks/ hook anyway"
        logger.warning(warn_msg)

    # Create hook
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_content = _HOOK_TEMPLATES.get(detected, _UNKNOWN_HOOK)
    hook_path.write_text(hook_content)
    os.chmod(hook_path, 0o755)  # noqa: S103  # nosec B103

    message = (
        f"{warn_msg}; created hook at {hook_path}"
        if warned
        else f"Created {detected} pre-commit hook at {hook_path}"
    )
    return PrepHookResult(
        created=True,
        warned=warned,
        language=detected,
        message=message,
        hook_path=hook_path,
    )


# ---------------------------------------------------------------------------
# Git configuration
# ---------------------------------------------------------------------------


async def configure_hooks_path(repo_root: Path) -> None:
    """Run ``git config core.hooksPath .githooks`` in *repo_root*."""
    try:
        await run_subprocess(
            "git", "config", "core.hooksPath", ".githooks", cwd=repo_root
        )
    except RuntimeError as exc:
        logger.warning("Failed to configure git hooks path: %s", exc)


# ---------------------------------------------------------------------------
# Combined entry point
# ---------------------------------------------------------------------------


async def setup_hooks(repo_root: Path, language: str | None = None) -> PrepHookResult:
    """Scaffold a pre-commit hook and configure git to use it.

    This is the main entry point that the future ``hydraflow prep`` CLI will call.
    """
    result = scaffold_pre_commit_hook(repo_root, language=language)
    await configure_hooks_path(repo_root)
    return result
