"""Scaffold linting and type-checking config for target repositories.

Scaffolds ruff/pyright config for Python repos and eslint/tsconfig for JS/TS repos.
Never overwrites existing config. Uses permissive defaults to avoid blocking existing code.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import tomllib
from pathlib import Path

from manifest import detect_language
from prep_ignore import PREP_IGNORED_DIRS

logger = logging.getLogger("hydraflow.lint_scaffold")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ESLINT_CONFIG_FILES = frozenset(
    {
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        ".eslintrc.yaml",
        ".eslintrc.yml",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "biome.json",
    }
)

_RUFF_SECTION = """
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP"]
"""

_PYRIGHT_SECTION = """
[tool.pyright]
pythonVersion = "3.11"
"""

_ESLINT_CONFIG = """\
// ESLint flat config (v9+)
export default [
  {
    rules: {
      "no-unused-vars": "warn",
      "no-undef": "error",
    },
  },
];
"""

_TSCONFIG = {
    "compilerOptions": {
        "target": "ES2020",
        "module": "ESNext",
        "moduleResolution": "bundler",
        "strict": False,
        "esModuleInterop": True,
        "skipLibCheck": True,
        "noEmit": True,
    },
    "include": ["src/**/*"],
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LintScaffoldResult:
    """Result of lint/type-check config scaffolding."""

    scaffolded: list[str] = dataclasses.field(default_factory=list)
    skipped: list[str] = dataclasses.field(default_factory=list)
    modified_files: list[str] = dataclasses.field(default_factory=list)
    created_files: list[str] = dataclasses.field(default_factory=list)
    language: str = ""


# ---------------------------------------------------------------------------
# TypeScript file detection
# ---------------------------------------------------------------------------


def has_typescript_files(repo_root: Path) -> bool:
    """Check if the repo contains TypeScript source files (excluding node_modules and .d.ts)."""
    for ext in ("*.ts", "*.tsx"):
        for p in repo_root.rglob(ext):
            if any(part in PREP_IGNORED_DIRS for part in p.parts):
                continue
            if p.name.endswith(".d.ts"):
                continue
            return True
    return False


# ---------------------------------------------------------------------------
# Config detection functions
# ---------------------------------------------------------------------------


def _has_ruff_config(repo_root: Path) -> bool:
    """Check if ruff config already exists."""
    if (repo_root / "ruff.toml").exists() or (repo_root / ".ruff.toml").exists():
        return True

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            if "ruff" in data.get("tool", {}):
                return True
        except tomllib.TOMLDecodeError:
            # Fall back to string matching
            if "[tool.ruff]" in pyproject.read_text():
                return True
    return False


def _has_pyright_config(repo_root: Path) -> bool:
    """Check if pyright config already exists."""
    if (repo_root / "pyrightconfig.json").exists():
        return True

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            if "pyright" in data.get("tool", {}):
                return True
        except tomllib.TOMLDecodeError:
            if "[tool.pyright]" in pyproject.read_text():
                return True
    return False


def _has_eslint_config(repo_root: Path) -> bool:
    """Check if ESLint (or Biome) config already exists."""
    return any((repo_root / f).exists() for f in _ESLINT_CONFIG_FILES)


def _has_tsconfig(repo_root: Path) -> bool:
    """Check if tsconfig.json already exists."""
    return (repo_root / "tsconfig.json").exists()


# ---------------------------------------------------------------------------
# Scaffold functions
# ---------------------------------------------------------------------------


def _scaffold_ruff(repo_root: Path) -> tuple[list[str], list[str]]:
    """Append [tool.ruff] section to pyproject.toml. Returns (modified, created) file lists."""
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        # Ensure trailing newline before appending
        if content and not content.endswith("\n"):
            content += "\n"
        content += _RUFF_SECTION
        pyproject.write_text(content)
        return (["pyproject.toml"], [])
    else:
        pyproject.write_text(_RUFF_SECTION.lstrip("\n"))
        return ([], ["pyproject.toml"])


def _scaffold_pyright(repo_root: Path) -> tuple[list[str], list[str]]:
    """Append [tool.pyright] section to pyproject.toml. Returns (modified, created) file lists."""
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        if content and not content.endswith("\n"):
            content += "\n"
        content += _PYRIGHT_SECTION
        pyproject.write_text(content)
        return (["pyproject.toml"], [])
    else:
        pyproject.write_text(_PYRIGHT_SECTION.lstrip("\n"))
        return ([], ["pyproject.toml"])


def _ensure_python_dev_deps(repo_root: Path) -> list[str]:
    """Add ruff and pyright to [project.optional-dependencies] dev if not present."""
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return []

    content = pyproject.read_text()

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    opt_deps = data.get("project", {}).get("optional-dependencies", {})
    dev_deps = opt_deps.get("dev", [])

    # Check which tools are missing
    has_ruff = any("ruff" in dep for dep in dev_deps)
    has_pyright = any("pyright" in dep for dep in dev_deps)

    additions = []
    if not has_ruff:
        additions.append('"ruff>=0.4.0"')
    if not has_pyright:
        additions.append('"pyright>=1.1.0"')

    if not additions:
        return []

    # If dev section exists, insert before its closing bracket
    if "dev" in opt_deps:
        lines = content.split("\n")
        in_dev = False
        insert_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("dev") and "=" in stripped and "[" in stripped:
                in_dev = True
            # Use exact match to avoid matching "]" inside dependency strings like "pkg[extra]"
            if in_dev and stripped == "]":
                insert_idx = i
                break

        if insert_idx >= 0:
            indent = "    "
            new_lines = [f"{indent}{a}," for a in additions]
            for j, new_line in enumerate(new_lines):
                lines.insert(insert_idx + j, new_line)
            pyproject.write_text("\n".join(lines))
        # Combine both outcomes into one return (avoids PLR0911 too-many-returns)
        return ["pyproject.toml"] if insert_idx >= 0 else []
    elif "optional-dependencies" in data.get("project", {}):
        # [project.optional-dependencies] exists but lacks 'dev' key; cannot safely
        # inject a new key without a proper TOML writer — skip rather than creating
        # a duplicate section header which would produce invalid TOML.
        logger.warning(
            "[project.optional-dependencies] exists but lacks 'dev' key in %s. "
            "Add ruff and pyright to dev dependencies manually.",
            pyproject,
        )
        return []
    else:
        # Append full [project.optional-dependencies] section
        section = "\n[project.optional-dependencies]\ndev = [\n"
        for a in additions:
            section += f"    {a},\n"
        section += "]\n"
        if content and not content.endswith("\n"):
            content += "\n"
        content += section
        pyproject.write_text(content)
        return ["pyproject.toml"]


def _scaffold_eslint(repo_root: Path) -> list[str]:
    """Create eslint.config.js with permissive flat config. Returns created file list."""
    config_path = repo_root / "eslint.config.js"
    config_path.write_text(_ESLINT_CONFIG)
    return ["eslint.config.js"]


def _scaffold_tsconfig(repo_root: Path) -> list[str]:
    """Create tsconfig.json with permissive defaults. Returns created file list."""
    tsconfig_path = repo_root / "tsconfig.json"
    tsconfig_path.write_text(json.dumps(_TSCONFIG, indent=2) + "\n")
    return ["tsconfig.json"]


def _ensure_js_dev_deps(repo_root: Path) -> list[str]:
    """Add eslint (and typescript if TS detected) to devDependencies in package.json."""
    pkg_path = repo_root / "package.json"
    if not pkg_path.exists():
        return []

    try:
        pkg = json.loads(pkg_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    dev_deps = pkg.get("devDependencies", {})
    changed = False

    if "eslint" not in dev_deps:
        dev_deps["eslint"] = "^9.0.0"
        changed = True

    if has_typescript_files(repo_root) and "typescript" not in dev_deps:
        dev_deps["typescript"] = "^5.0.0"
        changed = True

    if not changed:
        return []

    pkg["devDependencies"] = dev_deps
    pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    return ["package.json"]


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def scaffold_lint_config(
    repo_root: Path, *, dry_run: bool = False
) -> LintScaffoldResult:
    """Scaffold linting and type-checking config for a repository.

    Detects language, scaffolds appropriate configs with permissive defaults,
    and ensures relevant tools are in dependencies. Never overwrites existing config.
    """
    language = detect_language(repo_root)
    result = LintScaffoldResult(language=language)

    if language == "unknown":
        logger.info("No recognized language markers found in %s", repo_root)
        return result

    # --- Python scaffolding ---
    if language in ("python", "mixed"):
        if _has_ruff_config(repo_root):
            result.skipped.append("ruff")
        else:
            result.scaffolded.append("ruff")
            if not dry_run:
                modified, created = _scaffold_ruff(repo_root)
                result.modified_files.extend(modified)
                result.created_files.extend(created)

        if _has_pyright_config(repo_root):
            result.skipped.append("pyright")
        else:
            result.scaffolded.append("pyright")
            if not dry_run:
                modified, created = _scaffold_pyright(repo_root)
                result.modified_files.extend(modified)
                result.created_files.extend(created)

        if not dry_run:
            dep_files = _ensure_python_dev_deps(repo_root)
            result.modified_files.extend(dep_files)

    # --- JS/TS scaffolding ---
    if language in ("javascript", "mixed"):
        if _has_eslint_config(repo_root):
            result.skipped.append("eslint")
        else:
            result.scaffolded.append("eslint")
            if not dry_run:
                created = _scaffold_eslint(repo_root)
                result.created_files.extend(created)

        if _has_tsconfig(repo_root):
            result.skipped.append("tsconfig")
        elif has_typescript_files(repo_root):
            result.scaffolded.append("tsconfig")
            if not dry_run:
                created = _scaffold_tsconfig(repo_root)
                result.created_files.extend(created)

        if not dry_run:
            dep_files = _ensure_js_dev_deps(repo_root)
            result.modified_files.extend(dep_files)

    # Deduplicate file lists; a file can only be in one category
    result.created_files = list(dict.fromkeys(result.created_files))
    created_set = set(result.created_files)
    result.modified_files = list(
        dict.fromkeys(f for f in result.modified_files if f not in created_set)
    )

    logger.info(
        "Lint scaffold complete: scaffolded=%s, skipped=%s",
        result.scaffolded,
        result.skipped,
    )
    return result
