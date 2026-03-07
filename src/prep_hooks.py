"""Pre-commit hook scaffolding for target repositories.

Creates language-appropriate `.githooks/pre-commit` hooks and configures
git to use them.  Designed to be called by the future ``hydraflow prep`` CLI
command (epic #561).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

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
    _ensure_hook_executable(hook_path, repo_root, hook_content)

    if not os.access(hook_path, os.X_OK):
        cache_dir = Path(__file__).resolve().parent.parent / ".githooks-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_target = cache_dir / f"pre-commit-{uuid4().hex}"
        cache_target.write_text(hook_content)
        os.chmod(cache_target, 0o755)  # noqa: S103  # nosec B103
        hook_path.unlink(missing_ok=True)
        hook_path.symlink_to(cache_target)

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


def _ensure_hook_executable(hook_path: Path, repo_root: Path, content: str) -> None:
    """Ensure *hook_path* is executable; symlink to a cache when on noexec storage."""
    try:
        os.chmod(hook_path, 0o755)  # noqa: S103  # nosec B103
    except OSError as exc:  # pragma: no cover - permissions errors are rare
        logger.warning("Failed to chmod %s executable: %s", hook_path, exc)

    if os.access(hook_path, os.X_OK):
        return

    cache_root_str = os.environ.get("HYDRAFLOW_HOOK_CACHE_ROOT")
    cache_root = (
        Path(cache_root_str).resolve() if cache_root_str else Path.cwd().resolve()
    )
    cache_dir = cache_root / ".hydraflow-hook-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()
    fallback_hook = cache_dir / f"pre-commit-{digest}"
    fallback_hook.write_text(content)
    os.chmod(fallback_hook, 0o755)  # noqa: S103  # nosec B103

    if hook_path.exists() or hook_path.is_symlink():
        hook_path.unlink()
    hook_path.symlink_to(fallback_hook)
    logger.warning(
        "Hook directory %s appears to be on a noexec filesystem; symlinked hook to %s for executability.",
        hook_path.parent,
        fallback_hook,
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
