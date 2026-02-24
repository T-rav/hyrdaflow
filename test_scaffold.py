"""Scaffold test infrastructure for target repositories.

Creates test directory structures and framework config for Python (pytest)
and JS/TS (vitest) repos. Skips if test infrastructure already exists.
Scaffolds baseline test harness plus one smoke test per supported stack.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from manifest import detect_language

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
    except Exception:  # noqa: BLE001
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


def _scaffold_python_tests(repo_root: Path) -> TestScaffoldResult:
    """Create Python test baseline: tests/, conftest, pytest config, smoke test."""
    result = TestScaffoldResult(language="python")
    tests_dir = repo_root / "tests"

    # Create tests/ directory
    if not tests_dir.is_dir():
        tests_dir.mkdir(parents=True)
        result.created_dirs.append("tests")

    # Create tests/__init__.py
    init_file = tests_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")
        result.created_files.append("tests/__init__.py")

    # Create tests/conftest.py
    conftest = tests_dir / "conftest.py"
    if not conftest.exists():
        conftest.write_text(_CONFTEST_TEMPLATE)
        result.created_files.append("tests/conftest.py")

    smoke_test = tests_dir / "test_prep_smoke.py"
    if not smoke_test.exists():
        smoke_test.write_text(_PYTHON_SMOKE_TEST_TEMPLATE)
        result.created_files.append("tests/test_prep_smoke.py")

    # Handle pyproject.toml
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        # Create minimal pyproject.toml with pytest config
        pyproject.write_text(_PYTEST_CONFIG_TEMPLATE.lstrip())
        result.created_files.append("pyproject.toml")
    elif not _has_pytest_config(repo_root):
        # Append pytest config to existing pyproject.toml
        existing = pyproject.read_text()
        separator = "" if existing.endswith("\n") else "\n"
        pyproject.write_text(existing + separator + _PYTEST_CONFIG_TEMPLATE)
        result.modified_files.append("pyproject.toml")

    return result


def _scaffold_js_tests(repo_root: Path) -> TestScaffoldResult:
    """Create JS/TS baseline: __tests__/, vitest config, deps, smoke test."""
    result = TestScaffoldResult(language="javascript")
    tests_dir = repo_root / "__tests__"

    # Create __tests__/ directory
    if not tests_dir.is_dir():
        tests_dir.mkdir(parents=True)
        result.created_dirs.append("__tests__")

    # Create vitest.config.js (only if no test config exists)
    existing_configs = _has_js_test_config(repo_root)
    if not existing_configs:
        vitest_config = repo_root / "vitest.config.js"
        vitest_config.write_text(_VITEST_CONFIG_TEMPLATE)
        result.created_files.append("vitest.config.js")

    smoke_test = tests_dir / "prep.smoke.test.js"
    if not smoke_test.exists():
        smoke_test.write_text(_JS_SMOKE_TEST_TEMPLATE)
        result.created_files.append("__tests__/prep.smoke.test.js")

    # Modify package.json if it exists
    pkg_path = repo_root / "package.json"
    if pkg_path.is_file():
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
    if has_infra:
        return TestScaffoldResult(
            skipped=True,
            skip_reason=f"Test infrastructure already exists: {'; '.join(details)}",
            language=language,
        )

    if dry_run:
        return _dry_run_scaffold(repo_root, language)

    if language == "python":
        result = _scaffold_python_tests(repo_root)
    elif language == "javascript":
        result = _scaffold_js_tests(repo_root)
    else:
        # mixed
        py_result = _scaffold_python_tests(repo_root)
        js_result = _scaffold_js_tests(repo_root)
        result = _merge_results(py_result, js_result)

    # If nothing was created or modified, scaffold already ran
    if (
        not result.created_dirs
        and not result.created_files
        and not result.modified_files
    ):
        result.skipped = True
        result.skip_reason = "Test infrastructure already exists"

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
        if not (tests_dir / "test_prep_smoke.py").exists():
            result.created_files.append("tests/test_prep_smoke.py")
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
        if not (repo_root / "__tests__" / "prep.smoke.test.js").exists():
            result.created_files.append("__tests__/prep.smoke.test.js")
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
