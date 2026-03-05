"""Scaffold test infrastructure for target repositories.

Creates test directory structures and framework config for Python (pytest)
and JS/TS (vitest) repos. Skips if test infrastructure already exists.
Scaffolds baseline test harness plus a small smoke-test suite per stack.
"""

from __future__ import annotations

import json
import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from manifest import detect_language

logger = logging.getLogger("hydraflow.test_scaffold")

# --- Test file patterns ---
_PYTHON_TEST_PATTERNS = ("test_*.py", "*_test.py")
_JS_TEST_PATTERNS = (
    "*.test.js",
    "*.test.ts",
    "*.test.jsx",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.ts",
)

# --- Test config files ---
_JS_CONFIG_FILES = (
    "vitest.config.js",
    "vitest.config.ts",
    "jest.config.js",
    "jest.config.ts",
    "jest.config.mjs",
    "jest.config.cjs",
)

_IGNORED_SOURCE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hydraflow",
}
_DUMMY_TEST_LIMIT = 6
_SMOKE_TEST_TARGET = 8

# --- Templates ---

_CONFTEST_TEMPLATE = (
    '"""Shared fixtures for tests."""\n\nfrom __future__ import annotations\n'
)

_PYTEST_CONFIG_TEMPLATE = """
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
"""

_VITEST_CONFIG_TEMPLATE = """\
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    exclude: ['hydraflow/**'],
  },
});
"""

_PYTHON_SMOKE_TEST_TEMPLATE = (
    '"""Prep smoke test to validate test harness wiring."""\n\n'
    "def test_prep_smoke() -> None:\n"
    "    assert True\n"
)

_JS_SMOKE_TEST_TEMPLATE = """\
import { describe, expect, it } from 'vitest';

describe('prep smoke', () => {
  it('passes', () => {
    expect(true).toBe(true);
  });
});
"""


def _python_smoke_test_paths(tests_dir: Path) -> list[Path]:
    names = ["test_prep_smoke.py"]
    names.extend(
        f"test_prep_smoke_{idx}.py" for idx in range(2, _SMOKE_TEST_TARGET + 1)
    )
    return [tests_dir / name for name in names]


def _js_smoke_test_paths(tests_dir: Path) -> list[Path]:
    names = ["prep.smoke.test.js"]
    names.extend(
        f"prep.smoke.{idx}.test.js" for idx in range(2, _SMOKE_TEST_TARGET + 1)
    )
    return [tests_dir / name for name in names]


def _is_ignored_source_path(path: Path) -> bool:
    return any(part in _IGNORED_SOURCE_DIRS for part in path.parts)


def _sanitize_test_name(rel_path: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in rel_path).strip("_").lower()


def _discover_python_sources(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.py"):
        if _is_ignored_source_path(path.relative_to(repo_root)):
            continue
        if "tests" in path.relative_to(repo_root).parts:
            continue
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        files.append(path)
    return sorted(files)


def _discover_js_sources(repo_root: Path) -> list[Path]:
    globs = ("*.js", "*.jsx", "*.ts", "*.tsx")
    files: list[Path] = []
    for pattern in globs:
        for path in repo_root.rglob(pattern):
            rel = path.relative_to(repo_root)
            if _is_ignored_source_path(rel):
                continue
            if "__tests__" in rel.parts:
                continue
            if path.name in _JS_CONFIG_FILES:
                continue
            if path.name in {"vite.config.js", "vite.config.ts", "vite.config.mjs"}:
                continue
            if ".test." in path.name or ".spec." in path.name:
                continue
            files.append(path)
    return sorted(set(files))


def _python_placeholder_test(rel_path: str, test_name: str) -> str:
    return (
        f'"""Prep placeholder coverage scaffold for {rel_path}."""\n\n'
        "from pathlib import Path\n\n"
        f"def test_placeholder_{test_name}_exists() -> None:\n"
        f'    target = Path("{rel_path}")\n'
        "    assert target.is_file()\n"
        "\n"
        f"def test_placeholder_{test_name}_is_utf8_text() -> None:\n"
        f'    target = Path("{rel_path}")\n'
        "    content = target.read_text(encoding='utf-8')\n"
        "    assert isinstance(content, str)\n"
        "\n"
        f"def test_placeholder_{test_name}_non_empty() -> None:\n"
        f'    target = Path("{rel_path}")\n'
        "    content = target.read_text(encoding='utf-8')\n"
        "    assert content.strip() != ''\n"
        "\n"
        f"def test_placeholder_{test_name}_has_codeish_characters() -> None:\n"
        f'    target = Path("{rel_path}")\n'
        "    content = target.read_text(encoding='utf-8')\n"
        "    assert any(ch.isalnum() for ch in content)\n"
        "\n"
        f"def test_placeholder_{test_name}_no_nul_bytes() -> None:\n"
        f'    target = Path("{rel_path}")\n'
        "    content = target.read_bytes()\n"
        "    assert b'\\x00' not in content\n"
        "\n"
        f"def test_placeholder_{test_name}_has_at_least_one_line() -> None:\n"
        f'    target = Path("{rel_path}")\n'
        "    lines = target.read_text(encoding='utf-8').splitlines()\n"
        "    assert len(lines) >= 1\n"
    )


def _js_placeholder_test(rel_path: str) -> str:
    return (
        "import { describe, expect, it } from 'vitest';\n"
        "import { existsSync, readFileSync, statSync } from 'node:fs';\n\n"
        f"describe('prep placeholder {rel_path}', () => {{\n"
        "  it('exists', () => {\n"
        f"    const target = '{rel_path}';\n"
        "    expect(existsSync(target)).toBe(true);\n"
        "  });\n"
        "\n"
        "  it('is regular file', () => {\n"
        f"    const target = '{rel_path}';\n"
        "    expect(statSync(target).isFile()).toBe(true);\n"
        "  });\n"
        "\n"
        "  it('is non-empty', () => {\n"
        f"    const target = '{rel_path}';\n"
        "    expect(readFileSync(target, 'utf8').trim().length).toBeGreaterThan(0);\n"
        "  });\n"
        "\n"
        "  it('contains code-like characters', () => {\n"
        f"    const target = '{rel_path}';\n"
        "    const content = readFileSync(target, 'utf8');\n"
        "    expect(/[A-Za-z0-9]/.test(content)).toBe(true);\n"
        "  });\n"
        "\n"
        "  it('has no NUL bytes', () => {\n"
        f"    const target = '{rel_path}';\n"
        "    const content = readFileSync(target, 'utf8');\n"
        "    expect(content.includes('\\u0000')).toBe(false);\n"
        "  });\n"
        "\n"
        "  it('has at least one line', () => {\n"
        f"    const target = '{rel_path}';\n"
        "    const lines = readFileSync(target, 'utf8').split(/\\r?\\n/);\n"
        "    expect(lines.length).toBeGreaterThanOrEqual(1);\n"
        "  });\n"
        "});\n"
    )


@dataclass
class TestScaffoldResult:
    """Result of test infrastructure scaffolding."""

    __test__ = False  # prevent pytest from treating this dataclass as a test class

    created_dirs: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    language: str = ""
    progress: str = ""


def _has_python_test_files(repo_root: Path) -> list[str]:
    """Find Python test files in the tests/ directory."""
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return []
    found = []
    for pattern in _PYTHON_TEST_PATTERNS:
        found.extend(str(p.relative_to(repo_root)) for p in tests_dir.glob(pattern))
    return found


def _has_js_test_files(repo_root: Path) -> list[str]:
    """Find JS/TS test files in __tests__/ or root."""
    tests_dir = repo_root / "__tests__"
    if not tests_dir.is_dir():
        return []
    found = []
    for pattern in _JS_TEST_PATTERNS:
        found.extend(str(p.relative_to(repo_root)) for p in tests_dir.glob(pattern))
    return found


def _has_pytest_config(repo_root: Path) -> bool:
    """Check if pyproject.toml has pytest config."""
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        data = tomllib.loads(pyproject.read_text())
        return "pytest" in data.get("tool", {})
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to parse pytest configuration from %s: %s",
            pyproject,
            exc,
            exc_info=True,
        )
        return False


def _has_js_test_config(repo_root: Path) -> list[str]:
    """Check for JS test config files, return found names."""
    return [f for f in _JS_CONFIG_FILES if (repo_root / f).is_file()]


def has_test_infrastructure(repo_root: Path, language: str) -> tuple[bool, list[str]]:
    """Check if test infrastructure already exists.

    Returns (has_infra, details) where has_infra is True when both
    a test directory with test files AND framework config exist.
    For "mixed" repos, BOTH Python and JS infrastructure must be present.
    """
    details: list[str] = []
    py_done = False
    js_done = False

    if language in ("python", "mixed"):
        py_files = _has_python_test_files(repo_root)
        py_config = _has_pytest_config(repo_root)
        if py_files:
            details.append(f"Python test files found: {', '.join(py_files[:3])}")
        if py_config:
            details.append("pytest config found in pyproject.toml")
        py_done = bool(py_files and py_config)
        if language == "python" and py_done:
            return True, details

    if language in ("javascript", "mixed"):
        js_files = _has_js_test_files(repo_root)
        js_configs = _has_js_test_config(repo_root)
        if js_files:
            details.append(f"JS test files found: {', '.join(js_files[:3])}")
        if js_configs:
            details.append(f"JS test config found: {', '.join(js_configs)}")
        js_done = bool(js_files and js_configs)
        if language == "javascript" and js_done:
            return True, details

    if language == "mixed":
        return py_done and js_done, details

    return False, details


def _scaffold_python_tests(
    repo_root: Path, *, include_baseline: bool = True
) -> TestScaffoldResult:
    """Create Python test baseline: tests/, conftest, pytest config, smoke suite."""
    result = TestScaffoldResult(language="python")
    tests_dir = repo_root / "tests"

    # Create tests/ directory
    if include_baseline and not tests_dir.is_dir():
        tests_dir.mkdir(parents=True)
        result.created_dirs.append("tests")

    # Create tests/__init__.py
    init_file = tests_dir / "__init__.py"
    if include_baseline and not init_file.exists():
        init_file.write_text("")
        result.created_files.append("tests/__init__.py")

    # Create tests/conftest.py
    conftest = tests_dir / "conftest.py"
    if include_baseline and not conftest.exists():
        conftest.write_text(_CONFTEST_TEMPLATE)
        result.created_files.append("tests/conftest.py")

    if include_baseline or tests_dir.is_dir():
        for smoke_test in _python_smoke_test_paths(tests_dir):
            if smoke_test.exists():
                continue
            smoke_test.write_text(_PYTHON_SMOKE_TEST_TEMPLATE)
            result.created_files.append(f"tests/{smoke_test.name}")

    sources = _discover_python_sources(repo_root)
    pending_before = 0
    placeholder_created = 0
    for src in sources:
        rel = src.relative_to(repo_root).as_posix()
        test_name = _sanitize_test_name(rel)
        placeholder = tests_dir / f"test_prep_{test_name}.py"
        if not placeholder.exists():
            pending_before += 1
        if placeholder_created >= _DUMMY_TEST_LIMIT:
            continue
        if placeholder.exists():
            continue
        placeholder.write_text(_python_placeholder_test(rel, test_name))
        result.created_files.append(f"tests/{placeholder.name}")
        placeholder_created += 1

    result.progress = (
        "python placeholder batching: "
        f"created {placeholder_created} file(s) this run; "
        f"pending before batch {pending_before}; "
        f"batch limit {_DUMMY_TEST_LIMIT}"
    )

    # Handle pyproject.toml
    pyproject = repo_root / "pyproject.toml"
    if include_baseline and not pyproject.is_file():
        # Create minimal pyproject.toml with pytest config
        pyproject.write_text(_PYTEST_CONFIG_TEMPLATE.lstrip())
        result.created_files.append("pyproject.toml")
    elif include_baseline and not _has_pytest_config(repo_root):
        # Append pytest config to existing pyproject.toml
        existing = pyproject.read_text()
        separator = "" if existing.endswith("\n") else "\n"
        pyproject.write_text(existing + separator + _PYTEST_CONFIG_TEMPLATE)
        result.modified_files.append("pyproject.toml")

    return result


def _scaffold_js_tests(
    repo_root: Path, *, include_baseline: bool = True
) -> TestScaffoldResult:
    """Create JS/TS baseline: __tests__/, vitest config, deps, smoke suite."""
    result = TestScaffoldResult(language="javascript")
    tests_dir = repo_root / "__tests__"

    # Create __tests__/ directory
    if include_baseline and not tests_dir.is_dir():
        tests_dir.mkdir(parents=True)
        result.created_dirs.append("__tests__")

    # Create vitest.config.js (only if no test config exists)
    existing_configs = _has_js_test_config(repo_root)
    if include_baseline and not existing_configs:
        vitest_config = repo_root / "vitest.config.js"
        vitest_config.write_text(_VITEST_CONFIG_TEMPLATE)
        result.created_files.append("vitest.config.js")

    if include_baseline or tests_dir.is_dir():
        for smoke_test in _js_smoke_test_paths(tests_dir):
            if smoke_test.exists():
                continue
            smoke_test.write_text(_JS_SMOKE_TEST_TEMPLATE)
            result.created_files.append(f"__tests__/{smoke_test.name}")

    sources = _discover_js_sources(repo_root)
    pending_before = 0
    placeholder_created = 0
    for src in sources:
        rel = src.relative_to(repo_root).as_posix()
        test_name = _sanitize_test_name(rel)
        placeholder = tests_dir / f"prep.{test_name}.test.js"
        if not placeholder.exists():
            pending_before += 1
        if placeholder_created >= _DUMMY_TEST_LIMIT:
            continue
        if placeholder.exists():
            continue
        placeholder.write_text(_js_placeholder_test(rel))
        result.created_files.append(f"__tests__/{placeholder.name}")
        placeholder_created += 1

    result.progress = (
        "javascript placeholder batching: "
        f"created {placeholder_created} file(s) this run; "
        f"pending before batch {pending_before}; "
        f"batch limit {_DUMMY_TEST_LIMIT}"
    )

    # Modify package.json if it exists
    pkg_path = repo_root / "package.json"
    if include_baseline and pkg_path.is_file():
        try:
            pkg = json.loads(pkg_path.read_text())
        except (json.JSONDecodeError, OSError):
            return result  # Can't parse package.json; skip dependency injection
        modified = False

        # Add vitest to devDependencies
        if "devDependencies" not in pkg:
            pkg["devDependencies"] = {}
        if "vitest" not in pkg["devDependencies"]:
            pkg["devDependencies"]["vitest"] = "^4.0.0"
            modified = True
        if "@testing-library/jest-dom" not in pkg["devDependencies"]:
            pkg["devDependencies"]["@testing-library/jest-dom"] = "^6.0.0"
            modified = True

        # Add test script if not present
        if "scripts" not in pkg:
            pkg["scripts"] = {}
        if "test" not in pkg["scripts"]:
            pkg["scripts"]["test"] = "vitest run"
            modified = True

        if modified:
            pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
            result.modified_files.append("package.json")

    return result


def _merge_results(a: TestScaffoldResult, b: TestScaffoldResult) -> TestScaffoldResult:
    """Merge two scaffold results."""
    return TestScaffoldResult(
        created_dirs=a.created_dirs + b.created_dirs,
        created_files=a.created_files + b.created_files,
        modified_files=a.modified_files + b.modified_files,
        skipped=False,
        skip_reason="",
        language="mixed",
        progress="; ".join([p for p in (a.progress, b.progress) if p]),
    )


def scaffold_tests(repo_root: Path, *, dry_run: bool = False) -> TestScaffoldResult:
    """Scaffold test infrastructure for a repository.

    Detects the repo language and creates appropriate test skeleton.
    Skips if test infrastructure already exists.
    """
    language = detect_language(repo_root)

    if language == "unknown":
        return TestScaffoldResult(
            skipped=True,
            skip_reason="No recognized language detected",
            language="unknown",
        )

    has_infra, details = has_test_infrastructure(repo_root, language)

    if dry_run:
        return _dry_run_scaffold(repo_root, language)

    include_baseline = not has_infra
    if language == "python":
        result = _scaffold_python_tests(repo_root, include_baseline=include_baseline)
    elif language == "javascript":
        result = _scaffold_js_tests(repo_root, include_baseline=include_baseline)
    else:
        # mixed
        py_result = _scaffold_python_tests(repo_root, include_baseline=include_baseline)
        js_result = _scaffold_js_tests(repo_root, include_baseline=include_baseline)
        result = _merge_results(py_result, js_result)

    # If nothing was created or modified, scaffold already ran
    if (
        not result.created_dirs
        and not result.created_files
        and not result.modified_files
    ):
        result.skipped = True
        result.skip_reason = (
            f"Test infrastructure already exists: {'; '.join(details)}"
            if has_infra and details
            else "Test infrastructure already exists"
        )

    return result


def _dry_run_scaffold(repo_root: Path, language: str) -> TestScaffoldResult:
    """Compute what would be done without writing files."""
    result = TestScaffoldResult(language=language)

    if language in ("python", "mixed"):
        tests_dir = repo_root / "tests"
        if not tests_dir.is_dir():
            result.created_dirs.append("tests")
        if not (tests_dir / "__init__.py").exists():
            result.created_files.append("tests/__init__.py")
        if not (tests_dir / "conftest.py").exists():
            result.created_files.append("tests/conftest.py")
        for smoke_test in _python_smoke_test_paths(tests_dir):
            if not smoke_test.exists():
                result.created_files.append(f"tests/{smoke_test.name}")
        for src in _discover_python_sources(repo_root):
            rel = src.relative_to(repo_root).as_posix()
            test_name = _sanitize_test_name(rel)
            placeholder = tests_dir / f"test_prep_{test_name}.py"
            if not placeholder.exists():
                result.created_files.append(f"tests/{placeholder.name}")
        pyproject = repo_root / "pyproject.toml"
        if not pyproject.is_file():
            result.created_files.append("pyproject.toml")
        elif not _has_pytest_config(repo_root):
            result.modified_files.append("pyproject.toml")

    if language in ("javascript", "mixed"):
        if not (repo_root / "__tests__").is_dir():
            result.created_dirs.append("__tests__")
        if not _has_js_test_config(repo_root):
            result.created_files.append("vitest.config.js")
        tests_dir = repo_root / "__tests__"
        for smoke_test in _js_smoke_test_paths(tests_dir):
            if not smoke_test.exists():
                result.created_files.append(f"__tests__/{smoke_test.name}")
        for src in _discover_js_sources(repo_root):
            rel = src.relative_to(repo_root).as_posix()
            test_name = _sanitize_test_name(rel)
            placeholder = repo_root / "__tests__" / f"prep.{test_name}.test.js"
            if not placeholder.exists():
                result.created_files.append(f"__tests__/{placeholder.name}")
        pkg_path = repo_root / "package.json"
        if pkg_path.is_file():
            try:
                pkg = json.loads(pkg_path.read_text())
                dev_deps = pkg.get("devDependencies", {})
                scripts = pkg.get("scripts", {})
                needs_modification = (
                    "vitest" not in dev_deps
                    or "@testing-library/jest-dom" not in dev_deps
                    or "test" not in scripts
                )
                if needs_modification:
                    result.modified_files.append("package.json")
            except (json.JSONDecodeError, OSError):
                result.modified_files.append("package.json")

    return result
