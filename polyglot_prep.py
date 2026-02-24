"""Polyglot detection/scaffolding helpers for prep workflows."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from manifest import detect_language, detect_languages
from test_scaffold import TestScaffoldResult, scaffold_tests

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
    return sorted(files)[:_PLACEHOLDER_LIMIT]


def _go_package_name(source_file: Path) -> str:
    try:
        for line in source_file.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", line)
            if match:
                return match.group(1)
    except OSError:
        pass
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
    return sorted(files)[:_PLACEHOLDER_LIMIT]


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
    result = TestScaffoldResult(language="java")
    test_dir = repo_root / "src" / "test" / "java"
    smoke = test_dir / "PrepSmokeTest.java"
    smoke_content = (
        "class PrepSmokeTest {\n"
        "    public static void main(String[] args) {\n"
        '        System.out.println("prep smoke");\n'
        "    }\n"
        "}\n"
    )
    if not test_dir.is_dir():
        result.created_dirs.append("src/test/java")
        if not dry_run:
            test_dir.mkdir(parents=True, exist_ok=True)
    if not smoke.is_file():
        result.created_files.append("src/test/java/PrepSmokeTest.java")
        if not dry_run:
            smoke.write_text(smoke_content, encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "Java test infrastructure already exists"
    return result


def _scaffold_ruby_tests(
    repo_root: Path, dry_run: bool, *, rails: bool
) -> TestScaffoldResult:
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
    result = TestScaffoldResult(language="csharp")
    test_dir = repo_root / "tests"
    smoke = test_dir / "PrepSmokeTests.cs"
    content = (
        "using Xunit;\n\n"
        "public class PrepSmokeTests {\n"
        "    [Fact]\n"
        "    public void Smoke() {\n"
        "        Assert.True(true);\n"
        "    }\n"
        "}\n"
    )
    if not test_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            test_dir.mkdir(parents=True, exist_ok=True)
    if not smoke.is_file():
        result.created_files.append("tests/PrepSmokeTests.cs")
        if not dry_run:
            smoke.write_text(content, encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "C# test infrastructure already exists"
    return result


def _scaffold_go_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    result = TestScaffoldResult(language="go")
    sources = _discover_go_sources(repo_root)
    for source in sources:
        test_path = source.with_name(f"{source.stem}_test.go")
        if test_path.is_file():
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
            "}\n"
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

    if not sources:
        smoke = repo_root / "prep_smoke_test.go"
        content = (
            'package main\n\nimport "testing"\n\nfunc TestPrepSmoke(t *testing.T) {}\n'
        )
        if not smoke.is_file():
            result.created_files.append("prep_smoke_test.go")
            if not dry_run:
                smoke.write_text(content, encoding="utf-8")
    if not result.created_files:
        result.skipped = True
        result.skip_reason = "Go test infrastructure already exists"
    return result


def _scaffold_rust_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    result = TestScaffoldResult(language="rust")
    tests_dir = repo_root / "tests"
    sources = _discover_rust_sources(repo_root)
    if not tests_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            tests_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        rel = source.relative_to(repo_root).as_posix()
        test_name = _sanitize_ident(rel)
        test_file = tests_dir / f"prep_{test_name}.rs"
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

    if not sources:
        smoke = tests_dir / "prep_smoke.rs"
        content = "#[test]\nfn prep_smoke() { assert!(true); }\n"
        if not smoke.is_file():
            result.created_files.append("tests/prep_smoke.rs")
            if not dry_run:
                smoke.write_text(content, encoding="utf-8")
    if not result.created_dirs and not result.created_files:
        result.skipped = True
        result.skip_reason = "Rust test infrastructure already exists"
    return result


def _scaffold_cpp_tests(repo_root: Path, dry_run: bool) -> TestScaffoldResult:
    result = TestScaffoldResult(language="cpp")
    tests_dir = repo_root / "tests"
    smoke = tests_dir / "prep_smoke.cpp"
    content = "#include <cassert>\n\nint main() {\n  assert(true);\n  return 0;\n}\n"
    if not tests_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            tests_dir.mkdir(parents=True, exist_ok=True)
    if not smoke.is_file():
        result.created_files.append("tests/prep_smoke.cpp")
        if not dry_run:
            smoke.write_text(content, encoding="utf-8")
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
    stack = detect_prep_stack(repo_root)
    handlers: dict[str, Callable[[], TestScaffoldResult]] = {
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
    return TestScaffoldResult(
        skipped=True, skip_reason="No recognized language detected", language="unknown"
    )
