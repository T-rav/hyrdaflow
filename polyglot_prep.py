"""Polyglot detection/scaffolding helpers for prep workflows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from manifest import detect_language, detect_languages
from test_scaffold import TestScaffoldResult, scaffold_tests


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
    smoke = tests_dir / "prep_smoke.rs"
    content = "#[test]\nfn prep_smoke() { assert!(true); }\n"
    if not tests_dir.is_dir():
        result.created_dirs.append("tests")
        if not dry_run:
            tests_dir.mkdir(parents=True, exist_ok=True)
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
