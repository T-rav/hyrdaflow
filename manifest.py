"""Project manifest detection and persistence for agent memory.

Scans a repository root for language markers, build systems, test frameworks,
sub-projects/workspaces, and CI/CD configuration. Persists the result to
``.hydraflow/memory/manifest.md`` so agents have grounded project context
from the start of each run.

Consolidates the scattered ``_PYTHON_MARKERS`` / ``_JS_MARKERS`` constants
previously duplicated across ``ci_scaffold.py``, ``lint_scaffold.py``,
``makefile_scaffold.py``, ``test_scaffold.py``, and ``prep_hooks.py``, and
the ``detect_language()`` function previously duplicated across
``ci_scaffold.py``, ``lint_scaffold.py``, ``makefile_scaffold.py``, and
``test_scaffold.py``.  ``prep_hooks.py`` retains its own
``detect_language`` variant that returns ``"typescript"`` as a distinct
value.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from config import HydraFlowConfig
from file_util import atomic_write
from models import ManifestRefreshResult

logger = logging.getLogger("hydraflow.manifest")

# ---------------------------------------------------------------------------
# Centralised marker constants (single source of truth)
# ---------------------------------------------------------------------------

PYTHON_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
)
"""File markers indicating a Python project."""

JS_MARKERS: tuple[str, ...] = ("package.json", "tsconfig.json")
"""File markers indicating a JavaScript/TypeScript project."""

RUST_MARKERS: tuple[str, ...] = ("Cargo.toml",)
"""File markers indicating a Rust project."""

GO_MARKERS: tuple[str, ...] = ("go.mod",)
"""File markers indicating a Go project."""

JAVA_MARKERS: tuple[str, ...] = ("pom.xml", "build.gradle", "build.gradle.kts")
"""File markers indicating a Java/Kotlin project."""

BUILD_SYSTEM_MARKERS: dict[str, tuple[str, ...]] = {
    "make": ("Makefile", "GNUmakefile", "makefile"),
    "cmake": ("CMakeLists.txt",),
    "gradle": ("build.gradle", "build.gradle.kts"),
    "maven": ("pom.xml",),
    "cargo": ("Cargo.toml",),
    "npm": ("package.json",),
    "pip": ("pyproject.toml", "setup.py"),
}
"""Build system name -> marker files mapping."""

TEST_FRAMEWORK_MARKERS: dict[str, tuple[str, ...]] = {
    "pytest": ("pytest.ini", "conftest.py", "pyproject.toml"),
    "vitest": ("vitest.config.ts", "vitest.config.js", "vitest.config.mts"),
    "jest": ("jest.config.js", "jest.config.ts", "jest.config.mjs"),
    "cargo-test": ("Cargo.toml",),
    "go-test": ("go.mod",),
}
"""Test framework -> marker files mapping."""

CI_MARKERS: dict[str, str] = {
    "github-actions": ".github/workflows",
    "gitlab-ci": ".gitlab-ci.yml",
    "circleci": ".circleci/config.yml",
    "jenkins": "Jenkinsfile",
}
"""CI/CD system -> marker path mapping."""


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def detect_languages(repo_root: Path) -> list[str]:
    """Detect programming languages present in the repository.

    Returns a list of language names (e.g. ``["python", "javascript"]``).
    """
    languages: list[str] = []
    if any((repo_root / m).exists() for m in PYTHON_MARKERS):
        languages.append("python")
    if any((repo_root / m).exists() for m in JS_MARKERS):
        languages.append("javascript")
    if any((repo_root / m).exists() for m in RUST_MARKERS):
        languages.append("rust")
    if any((repo_root / m).exists() for m in GO_MARKERS):
        languages.append("go")
    if any((repo_root / m).exists() for m in JAVA_MARKERS):
        languages.append("java")
    return languages


def detect_language(repo_root: Path) -> str:
    """Detect the primary language of a repository from marker files.

    Returns ``"python"``, ``"javascript"``, ``"mixed"``, or ``"unknown"``.
    """
    has_python = any((repo_root / m).exists() for m in PYTHON_MARKERS)
    has_js = any((repo_root / m).exists() for m in JS_MARKERS)

    if has_python and has_js:
        return "mixed"
    if has_python:
        return "python"
    if has_js:
        return "javascript"
    return "unknown"


def detect_build_systems(repo_root: Path) -> list[str]:
    """Detect build systems present in the repository."""
    systems: list[str] = []
    for name, markers in BUILD_SYSTEM_MARKERS.items():
        if any((repo_root / m).exists() for m in markers):
            systems.append(name)
    return systems


def detect_test_frameworks(repo_root: Path) -> list[str]:
    """Detect test frameworks configured in the repository.

    Goes beyond marker-file presence: for ``pytest`` it checks that
    ``pyproject.toml`` actually contains a ``[tool.pytest]`` section or
    that a ``tests/`` directory exists.
    """
    frameworks: list[str] = []

    # --- pytest ---
    if (repo_root / "pytest.ini").exists() or (repo_root / "conftest.py").exists():
        frameworks.append("pytest")
    elif (repo_root / "pyproject.toml").exists():
        try:
            content = (repo_root / "pyproject.toml").read_text()
            if "[tool.pytest" in content:
                frameworks.append("pytest")
        except OSError:
            pass
    if (
        "pytest" not in frameworks
        and (repo_root / "tests").is_dir()
        and any((repo_root / m).exists() for m in PYTHON_MARKERS)
    ):
        # Heuristic: tests/ dir with Python markers => likely pytest
        frameworks.append("pytest")

    # --- vitest ---
    for marker in TEST_FRAMEWORK_MARKERS["vitest"]:
        if (repo_root / marker).exists():
            frameworks.append("vitest")
            break

    # --- jest ---
    if "vitest" not in frameworks:
        for marker in TEST_FRAMEWORK_MARKERS["jest"]:
            if (repo_root / marker).exists():
                frameworks.append("jest")
                break
        # Check package.json for jest config
        if "jest" not in frameworks:
            pkg_json = repo_root / "package.json"
            if pkg_json.exists():
                try:
                    pkg = json.loads(pkg_json.read_text())
                    if "jest" in pkg:
                        frameworks.append("jest")
                except (json.JSONDecodeError, OSError):
                    pass

    # --- cargo test ---
    if (repo_root / "Cargo.toml").exists():
        frameworks.append("cargo-test")

    # --- go test ---
    if (repo_root / "go.mod").exists():
        frameworks.append("go-test")

    return frameworks


def detect_ci_systems(repo_root: Path) -> list[str]:
    """Detect CI/CD systems configured in the repository."""
    systems: list[str] = []
    for name, marker in CI_MARKERS.items():
        path = repo_root / marker
        if path.exists():
            systems.append(name)
    return systems


def detect_sub_projects(repo_root: Path) -> list[dict[str, str]]:
    """Detect sub-projects and workspaces.

    Checks for:
    - npm/yarn/pnpm workspaces (``package.json`` ``workspaces`` field)
    - Cargo workspaces (``Cargo.toml`` ``[workspace]`` section)
    - Python namespace packages (directories with their own ``pyproject.toml``)

    Returns a list of dicts with ``name`` and ``path`` keys.
    """
    sub_projects: list[dict[str, str]] = []

    # --- npm workspaces ---
    pkg_json = repo_root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text())
            workspaces = pkg.get("workspaces", [])
            # workspaces can be a list or a dict with "packages" key
            if isinstance(workspaces, dict):
                workspaces = workspaces.get("packages", [])
            if isinstance(workspaces, list):
                for ws in workspaces:
                    if isinstance(ws, str):
                        sub_projects.append({"name": ws, "path": ws})
        except (json.JSONDecodeError, OSError):
            pass

    # --- Cargo workspaces ---
    cargo_toml = repo_root / "Cargo.toml"
    if cargo_toml.exists():
        try:
            content = cargo_toml.read_text()
            if "[workspace]" in content:
                # Simple line-by-line parse for members
                in_members = False
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("members"):
                        in_members = True
                        continue
                    if in_members:
                        if stripped == "]":
                            break
                        # Extract quoted paths
                        member = stripped.strip('",').strip("',").strip()
                        if member and not member.startswith("["):
                            sub_projects.append({"name": member, "path": member})
        except OSError:
            pass

    # --- Python namespace packages ---
    # Look for directories containing their own pyproject.toml (one level deep)
    try:
        for child in sorted(repo_root.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in (
                "node_modules",
                "venv",
                ".venv",
                "__pycache__",
                ".git",
            ):
                continue
            if (child / "pyproject.toml").exists():
                sub_projects.append({"name": child.name, "path": child.name})
    except OSError:
        pass

    return sub_projects


def detect_key_docs(repo_root: Path) -> list[str]:
    """Detect key documentation files present in the repository."""
    candidates = [
        "README.md",
        "README.rst",
        "CONTRIBUTING.md",
        "CLAUDE.md",
        "CHANGELOG.md",
        "LICENSE",
        "LICENSE.md",
    ]
    return [name for name in candidates if (repo_root / name).exists()]


# ---------------------------------------------------------------------------
# Manifest formatting
# ---------------------------------------------------------------------------


def build_manifest_markdown(repo_root: Path) -> str:
    """Scan *repo_root* and return a markdown-formatted project manifest."""
    languages = detect_languages(repo_root)
    build_systems = detect_build_systems(repo_root)
    test_frameworks = detect_test_frameworks(repo_root)
    ci_systems = detect_ci_systems(repo_root)
    sub_projects = detect_sub_projects(repo_root)
    key_docs = detect_key_docs(repo_root)

    now = datetime.now(UTC).isoformat()
    lines: list[str] = [
        "## Project Manifest",
        f"*Auto-detected -- last scanned {now}*",
        "",
    ]

    if languages:
        lines.append(f"**Languages:** {', '.join(languages)}")
    else:
        lines.append("**Languages:** unknown")

    if build_systems:
        lines.append(f"**Build systems:** {', '.join(build_systems)}")

    if test_frameworks:
        lines.append(f"**Test frameworks:** {', '.join(test_frameworks)}")

    if ci_systems:
        lines.append(f"**CI/CD:** {', '.join(ci_systems)}")

    if key_docs:
        lines.append(f"**Key docs:** {', '.join(key_docs)}")

    if sub_projects:
        lines.append("")
        lines.append("### Sub-projects")
        for sp in sub_projects:
            lines.append(f"- `{sp['path']}` ({sp['name']})")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ProjectManifestManager
# ---------------------------------------------------------------------------


class ProjectManifestManager:
    """Detects and persists project-level metadata alongside the memory digest.

    Follows the same pattern as ``MemorySyncWorker`` for state tracking
    and file persistence.
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config

    @property
    def manifest_path(self) -> Path:
        """Return the path to the persisted manifest file."""
        return self._config.repo_root / ".hydraflow" / "memory" / "manifest.md"

    def scan(self) -> str:
        """Scan the repo and return the manifest markdown content."""
        return build_manifest_markdown(self._config.repo_root)

    def write(self, content: str) -> str:
        """Write *content* to the manifest file atomically. Returns the content hash."""
        atomic_write(self.manifest_path, content)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def needs_refresh(self, current_hash: str) -> bool:
        """Return True if the on-disk manifest differs from *current_hash*.

        Also returns True if the manifest file does not exist.
        """
        if not self.manifest_path.is_file():
            return True
        try:
            content = self.manifest_path.read_text()
        except OSError:
            return True
        on_disk_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return on_disk_hash != current_hash

    def refresh(self) -> ManifestRefreshResult:
        """Scan, write, and return the content and hash."""
        content = self.scan()
        digest_hash = self.write(content)
        return ManifestRefreshResult(content=content, digest_hash=digest_hash)


# ---------------------------------------------------------------------------
# Prompt injection helper
# ---------------------------------------------------------------------------


def load_project_manifest(config: HydraFlowConfig) -> str:
    """Read the project manifest from disk if it exists.

    Returns an empty string if the file is missing or empty.
    Content is capped at ``config.max_manifest_prompt_chars``.
    """
    manifest_path = config.repo_root / ".hydraflow" / "memory" / "manifest.md"
    if not manifest_path.is_file():
        return ""
    try:
        content = manifest_path.read_text()
    except OSError:
        return ""
    if not content.strip():
        return ""
    max_chars = config.max_manifest_prompt_chars
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n...(truncated)"
    return content
