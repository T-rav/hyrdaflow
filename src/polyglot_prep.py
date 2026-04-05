"""Polyglot detection/scaffolding helpers for prep workflows."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from test_scaffold import TestScaffoldResult

logger = logging.getLogger("hydraflow.polyglot_prep")


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
        except OSError as exc:
            logger.warning(
                "Failed to read %s while checking pytest config; assuming pytest is absent (%s).",
                repo_root / "pyproject.toml",
                exc,
                exc_info=True,
            )
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
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "Failed to parse %s while detecting jest config: %s",
                        pkg_json,
                        exc,
                        exc_info=True,
                    )

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
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to parse %s while detecting npm workspaces: %s",
                pkg_json,
                exc,
                exc_info=True,
            )

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
        except OSError as exc:
            logger.warning(
                "Failed to read %s while detecting Cargo workspaces: %s",
                cargo_toml,
                exc,
                exc_info=True,
            )

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
    except OSError as exc:
        logger.warning(
            "Failed to list directories in %s while detecting namespace packages: %s",
            repo_root,
            exc,
            exc_info=True,
        )

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


_IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".hydraflow",
}
_PLACEHOLDER_LIMIT = 12
_SMOKE_TEST_TARGET = 8


def _smoke_file_names(base_name: str, suffix: str, target: int) -> list[str]:
    names = [f"{base_name}{suffix}"]
    names.extend(f"{base_name}_{idx}{suffix}" for idx in range(2, target + 1))
    return names


def _java_smoke_content(class_name: str) -> str:
    return (
        f"class {class_name} {{\n"
        "    public static void main(String[] args) {\n"
        '        System.out.println("prep smoke");\n'
        "    }\n"
        "}\n"
    )


def _csharp_smoke_content(class_name: str) -> str:
    return (
        "using Xunit;\n\n"
        f"public class {class_name} {{\n"
        "    [Fact]\n"
        "    public void Smoke() {\n"
        "        Assert.True(true);\n"
        "    }\n"
        "}\n"
    )


def _go_smoke_content(package_name: str, func_name: str) -> str:
    return (
        f"package {package_name}\n\n"
        'import "testing"\n\n'
        f"func {func_name}(t *testing.T) {{\n"
        "}\n"
    )


def _rust_smoke_content(func_name: str) -> str:
    return f"#[test]\nfn {func_name}() {{ assert!(true); }}\n"


def _cpp_smoke_content(func_name: str) -> str:
    return f"#include <cassert>\n\nvoid {func_name}() {{\n  assert(true);\n}}\n"


def _ruby_smoke_content(class_name: str, *, rails: bool) -> str:
    require_line = 'require "test_helper"' if rails else 'require "minitest/autorun"'
    return (
        f"{require_line}\n\n"
        f"class {class_name} < Minitest::Test\n"
        "  def test_smoke\n"
        "    assert true\n"
        "  end\n"
        "end\n"
    )


def _is_ignored_rel_path(path: Path) -> bool:
    return any(part in _IGNORED_DIR_NAMES for part in path.parts)


def _sanitize_ident(text: str) -> str:
    token = re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_")
    if not token:
        return "file"
    if token[0].isdigit():
        return f"f_{token}"
    return token


def _discover_go_sources(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*.go"):
        rel = path.relative_to(repo_root)
        if _is_ignored_rel_path(rel):
            continue
        if path.name.endswith("_test.go"):
            continue
        files.append(path)
    return sorted(files)


def _go_package_name(source_file: Path) -> str:
    try:
        for line in source_file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
            if match:
                return match.group(1)
    except OSError:
        logger.debug("Could not read Go file for package detection", exc_info=True)
    return "main"


def _discover_rust_sources(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    src_dir = repo_root / "src"
    if not src_dir.is_dir():
        return files
    for path in src_dir.rglob("*.rs"):
        rel = path.relative_to(repo_root)
        if _is_ignored_rel_path(rel):
            continue
        files.append(path)
    return sorted(files)


def detect_prep_stack(repo_root: Path) -> str:
    """Detect primary stack for prep CI/test scaffolding."""
    stack = "unknown"
    has_gemfile = (repo_root / "Gemfile").is_file()
    is_rails = has_gemfile and (
        (repo_root / "config" / "application.rb").is_file()
        or (repo_root / "bin" / "rails").is_file()
    )
    langs = set(detect_languages(repo_root))
    primary = detect_language(repo_root)

    if any(repo_root.glob("*.sln")) or any(repo_root.glob("*.csproj")):
        stack = "csharp"
    elif is_rails:
        stack = "rails"
    elif has_gemfile:
        stack = "ruby"
    elif "rust" in langs:
        stack = "rust"
    elif "go" in langs:
        stack = "go"
    elif "java" in langs:
        stack = "java"
    elif (repo_root / "CMakeLists.txt").is_file() or any(repo_root.glob("*.cpp")):
        stack = "cpp"
    elif (repo_root / "package.json").is_file() or primary == "javascript":
        stack = "node"
    elif primary == "mixed":
        stack = "mixed"
    elif primary == "python":
        stack = "python"

    return stack


def _scaffold_java_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    from test_scaffold import TestScaffoldResult  # noqa: PLC0415

    result = TestScaffoldResult(language="java")
    test_dir = repo_root / "src" / "test" / "java"
    if not test_dir.is_dir():
        result.created_dirs.append("src/test/java")
        if not dry_run:
            test_dir.mkdir(parents=True, exist_ok=True)
    for idx, file_name in enumerate(
        _smoke_file_names("PrepSmokeTest", ".java", _SMOKE_TEST_TARGET),
        start=1,
    ):
        smoke = test_dir / file_name
        class_name = "PrepSmokeTest" if idx == 1 else f"PrepSmokeTest{idx}"
        if smoke.is_file():
            continue
        result.created_files.append(f"src/test/java/{file_name}")
        if not dry_run:
            smoke.write_text(_java_smoke_content(class_name), encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "Java test infrastructure already exists"
    return result


def _scaffold_ruby_tests(
    repo_root: Path, dry_run: bool, *, rails: bool
) -> TestScaffoldResult:
    from test_scaffold import TestScaffoldResult  # noqa: PLC0415

    lang = "rails" if rails else "ruby"
    result = TestScaffoldResult(language=lang)
    test_dir = repo_root / "test"
    helper = test_dir / "test_helper.rb"
    helper_content = (
        "# frozen_string_literal: true\n\nENV['RAILS_ENV'] ||= 'test'\n"
        if rails
        else "# frozen_string_literal: true\n"
    )
    if not test_dir.is_dir():
        result.created_dirs.append("test")
        if not dry_run:
            test_dir.mkdir(parents=True, exist_ok=True)
    if not helper.is_file():
        result.created_files.append("test/test_helper.rb")
        if not dry_run:
            helper.write_text(helper_content, encoding="utf-8")
    for idx, file_name in enumerate(
        _smoke_file_names("prep_smoke_test", ".rb", _SMOKE_TEST_TARGET), start=1
    ):
        smoke = test_dir / file_name
        class_name = "PrepSmokeTest" if idx == 1 else f"PrepSmokeTest{idx}"
        if smoke.is_file():
            continue
        result.created_files.append(f"test/{file_name}")
        if not dry_run:
            smoke.write_text(
                _ruby_smoke_content(class_name, rails=rails), encoding="utf-8"
            )
    if rails:
        model_dir = test_dir / "models"
        keep_file = model_dir / ".keep"
        if not model_dir.is_dir():
            result.created_dirs.append("test/models")
            if not dry_run:
                model_dir.mkdir(parents=True, exist_ok=True)
        if not keep_file.is_file():
            result.created_files.append("test/models/.keep")
            if not dry_run:
                keep_file.write_text("", encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = f"{lang.capitalize()} test infrastructure already exists"
    return result


def _scaffold_csharp_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    from test_scaffold import TestScaffoldResult  # noqa: PLC0415

    result = TestScaffoldResult(language="csharp")
    test_dir = repo_root / "tests"
    if not test_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            test_dir.mkdir(parents=True, exist_ok=True)
    for idx, file_name in enumerate(
        _smoke_file_names("PrepSmokeTests", ".cs", _SMOKE_TEST_TARGET),
        start=1,
    ):
        smoke = test_dir / file_name
        class_name = "PrepSmokeTests" if idx == 1 else f"PrepSmokeTests{idx}"
        if smoke.is_file():
            continue
        result.created_files.append(f"tests/{file_name}")
        if not dry_run:
            smoke.write_text(_csharp_smoke_content(class_name), encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "C# test infrastructure already exists"
    return result


def _scaffold_go_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    from test_scaffold import TestScaffoldResult  # noqa: PLC0415

    result = TestScaffoldResult(language="go")
    sources = _discover_go_sources(repo_root)
    pending_before = 0
    created_batch = 0
    for source in sources:
        test_path = source.with_name(f"{source.stem}_test.go")
        if not test_path.is_file():
            pending_before += 1
        if created_batch >= _PLACEHOLDER_LIMIT or test_path.is_file():
            continue

        package_name = _go_package_name(source)
        fn_name = _sanitize_ident(source.stem)
        rel = source.relative_to(repo_root).as_posix()
        content = (
            f"package {package_name}\n\n"
            "import (\n"
            '\t"bytes"\n'
            '\t"os"\n'
            '\t"testing"\n'
            ")\n\n"
            f"func prepRead_{fn_name}(t *testing.T) []byte {{\n"
            "\tt.Helper()\n"
            f'\tdata, err := os.ReadFile("{source.name}")\n'
            "\tif err != nil {\n"
            f'\t\tt.Fatalf("expected source file {rel} to exist: %v", err)\n'
            "\t}\n"
            "\treturn data\n"
            "}\n\n"
            f"func TestPrepPlaceholder_{fn_name}_Exists(t *testing.T) {{\n"
            f'\tif _, err := os.Stat("{source.name}"); err != nil {{\n'
            f'\t\tt.Fatalf("expected source file {rel} to exist: %v", err)\n'
            "\t}\n"
            "}\n"
            f"\nfunc TestPrepPlaceholder_{fn_name}_NonEmpty(t *testing.T) {{\n"
            f"\tdata := prepRead_{fn_name}(t)\n"
            "\tif len(bytes.TrimSpace(data)) == 0 {\n"
            f'\t\tt.Fatalf("expected source file {rel} to be non-empty")\n'
            "\t}\n"
            "}\n"
            f"\nfunc TestPrepPlaceholder_{fn_name}_HasCodeLikeCharacters(t *testing.T) {{\n"
            f"\tdata := prepRead_{fn_name}(t)\n"
            "\tfound := false\n"
            "\tfor _, b := range data {\n"
            "\t\tif (b >= 'a' && b <= 'z') || (b >= 'A' && b <= 'Z') || (b >= '0' && b <= '9') {\n"
            "\t\t\tfound = true\n"
            "\t\t\tbreak\n"
            "\t\t}\n"
            "\t}\n"
            "\tif !found {\n"
            f'\t\tt.Fatalf("expected source file {rel} to contain code-like characters")\n'
            "\t}\n"
            "}\n"
            f"\nfunc TestPrepPlaceholder_{fn_name}_NoNulBytes(t *testing.T) {{\n"
            f"\tdata := prepRead_{fn_name}(t)\n"
            "\tif bytes.Contains(data, []byte{0}) {\n"
            f'\t\tt.Fatalf("expected source file {rel} to have no NUL bytes")\n'
            "\t}\n"
            f"\nfunc TestPrepPlaceholder_{fn_name}_HasAtLeastOneLine(t *testing.T) {{\n"
            f"\tdata := prepRead_{fn_name}(t)\n"
            "\tif len(bytes.Split(data, []byte{'\\n'})) < 1 {\n"
            f'\t\tt.Fatalf("expected source file {rel} to have at least one line")\n'
            "\t}\n"
            "}\n"
            f"\nfunc TestPrepPlaceholder_{fn_name}_IsRegularFile(t *testing.T) {{\n"
            f'\tinfo, err := os.Stat("{source.name}")\n'
            "\tif err != nil {\n"
            f'\t\tt.Fatalf("expected source file {rel} to exist: %v", err)\n'
            "\t}\n"
            "\tif !info.Mode().IsRegular() {\n"
            f'\t\tt.Fatalf("expected source file {rel} to be regular file")\n'
            "\t}\n"
            "}\n"
        )
        result.created_files.append(str(test_path.relative_to(repo_root)))
        if not dry_run:
            test_path.write_text(content, encoding="utf-8")
        created_batch += 1

    smoke_dir = sources[0].parent if sources else repo_root
    smoke_package = _go_package_name(sources[0]) if sources else "main"
    smoke_names = _smoke_file_names("prep_smoke", "_test.go", _SMOKE_TEST_TARGET)
    for idx, file_name in enumerate(smoke_names, start=1):
        smoke = smoke_dir / file_name
        func_name = "TestPrepSmoke" if idx == 1 else f"TestPrepSmoke{idx}"
        if smoke.is_file():
            continue
        rel_smoke = smoke.relative_to(repo_root).as_posix()
        result.created_files.append(rel_smoke)
        if not dry_run:
            smoke.write_text(
                _go_smoke_content(smoke_package, func_name), encoding="utf-8"
            )

    result.progress = (
        "go placeholder batching: "
        f"created {created_batch} file(s) this run; "
        f"pending before batch {pending_before}; "
        f"batch limit {_PLACEHOLDER_LIMIT}"
    )
    if not result.created_files:
        result.skipped = True
        result.skip_reason = "Go test infrastructure already exists"
    return result


def _scaffold_rust_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    from test_scaffold import TestScaffoldResult  # noqa: PLC0415

    result = TestScaffoldResult(language="rust")
    tests_dir = repo_root / "tests"
    sources = _discover_rust_sources(repo_root)
    pending_before = 0
    created_batch = 0
    if not tests_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            tests_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        rel = source.relative_to(repo_root).as_posix()
        test_name = _sanitize_ident(rel)
        test_file = tests_dir / f"prep_{test_name}.rs"
        if not test_file.is_file():
            pending_before += 1
        if created_batch >= _PLACEHOLDER_LIMIT:
            continue
        if test_file.is_file():
            continue
        content = (
            "use std::path::Path;\n\n"
            f"fn prep_read_{test_name}() -> String {{\n"
            f'    std::fs::read_to_string("{rel}").expect("source file should be readable as UTF-8")\n'
            "}\n\n"
            "#[test]\n"
            f"fn prep_placeholder_{test_name}_exists() {{\n"
            f'    assert!(Path::new("{rel}").exists());\n'
            "}\n"
            "\n#[test]\n"
            f"fn prep_placeholder_{test_name}_non_empty() {{\n"
            f"    let content = prep_read_{test_name}();\n"
            "    assert!(!content.trim().is_empty());\n"
            "}\n"
            "\n#[test]\n"
            f"fn prep_placeholder_{test_name}_has_codeish_characters() {{\n"
            f"    let content = prep_read_{test_name}();\n"
            "    assert!(content.chars().any(|c| c.is_alphanumeric()));\n"
            "}\n"
            "\n#[test]\n"
            f"fn prep_placeholder_{test_name}_no_nul_bytes() {{\n"
            f"    let content = prep_read_{test_name}();\n"
            "    assert!(!content.contains('\\0'));\n"
            "}\n"
            "\n#[test]\n"
            f"fn prep_placeholder_{test_name}_has_at_least_one_line() {{\n"
            f"    let content = prep_read_{test_name}();\n"
            "    assert!(content.lines().count() >= 1);\n"
            "}\n"
            "\n#[test]\n"
            f"fn prep_placeholder_{test_name}_is_regular_file() {{\n"
            f'    let meta = std::fs::metadata("{rel}").expect("source metadata should exist");\n'
            "    assert!(meta.is_file());\n"
            "}\n"
        )
        result.created_files.append(str(test_file.relative_to(repo_root)))
        if not dry_run:
            test_file.write_text(content, encoding="utf-8")
        created_batch += 1

    for idx, file_name in enumerate(
        _smoke_file_names("prep_smoke", ".rs", _SMOKE_TEST_TARGET), start=1
    ):
        smoke = tests_dir / file_name
        func_name = "prep_smoke" if idx == 1 else f"prep_smoke_{idx}"
        if smoke.is_file():
            continue
        result.created_files.append(f"tests/{file_name}")
        if not dry_run:
            smoke.write_text(_rust_smoke_content(func_name), encoding="utf-8")
    result.progress = (
        "rust placeholder batching: "
        f"created {created_batch} file(s) this run; "
        f"pending before batch {pending_before}; "
        f"batch limit {_PLACEHOLDER_LIMIT}"
    )
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "Rust test infrastructure already exists"
    return result


def _scaffold_cpp_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    from test_scaffold import TestScaffoldResult  # noqa: PLC0415

    result = TestScaffoldResult(language="cpp")
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            tests_dir.mkdir(parents=True, exist_ok=True)
    for idx, file_name in enumerate(
        _smoke_file_names("prep_smoke", ".cpp", _SMOKE_TEST_TARGET), start=1
    ):
        smoke = tests_dir / file_name
        func_name = "prep_smoke" if idx == 1 else f"prep_smoke_{idx}"
        if smoke.is_file():
            continue
        result.created_files.append(f"tests/{file_name}")
        if not dry_run:
            smoke.write_text(_cpp_smoke_content(func_name), encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "C++ test infrastructure already exists"
    return result


def scaffold_tests_polyglot(
    repo_root: Path, *, dry_run: bool = False
) -> TestScaffoldResult:
    """Scaffold tests for common stacks.

    Delegates to existing ``test_scaffold`` for Python/Node/mixed.
    """
    from test_scaffold import TestScaffoldResult as TSR  # noqa: PLC0415
    from test_scaffold import scaffold_tests  # noqa: PLC0415

    stack = detect_prep_stack(repo_root)
    handlers: dict[str, Callable[[], TSR]] = {
        "python": lambda: scaffold_tests(repo_root, dry_run=dry_run),
        "node": lambda: scaffold_tests(repo_root, dry_run=dry_run),
        "mixed": lambda: scaffold_tests(repo_root, dry_run=dry_run),
        "java": lambda: _scaffold_java_tests(repo_root, dry_run),
        "ruby": lambda: _scaffold_ruby_tests(repo_root, dry_run, rails=False),
        "rails": lambda: _scaffold_ruby_tests(repo_root, dry_run, rails=True),
        "csharp": lambda: _scaffold_csharp_tests(repo_root, dry_run),
        "go": lambda: _scaffold_go_tests(repo_root, dry_run),
        "rust": lambda: _scaffold_rust_tests(repo_root, dry_run),
        "cpp": lambda: _scaffold_cpp_tests(repo_root, dry_run),
    }
    if stack in handlers:
        return handlers[stack]()
    return TSR(
        skipped=True, skip_reason="No recognized language detected", language="unknown"
    )
