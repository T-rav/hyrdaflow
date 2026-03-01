"""Tests for polyglot prep detection and test scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polyglot_prep import detect_prep_stack, scaffold_tests_polyglot


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (["App.sln"], "csharp"),
        (["go.mod"], "go"),
        (["Cargo.toml"], "rust"),
        (["CMakeLists.txt"], "cpp"),
        (["pom.xml"], "java"),
        (["Gemfile", "config/application.rb"], "rails"),
        (["Gemfile"], "ruby"),
        (["pyproject.toml"], "python"),
    ],
)
def test_detect_prep_stack(files: list[str], expected: str, tmp_path: Path) -> None:
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    if "Gemfile" in files:
        (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
    assert detect_prep_stack(tmp_path) == expected


@pytest.mark.parametrize(
    ("stack_file", "smoke_glob"),
    [
        ("App.sln", "tests/PrepSmokeTests*.cs"),
        ("go.mod", "prep_smoke*_test.go"),
        ("Cargo.toml", "tests/prep_smoke*.rs"),
        ("CMakeLists.txt", "tests/prep_smoke*.cpp"),
        ("Gemfile", "test/prep_smoke_test*.rb"),
    ],
)
def test_scaffold_tests_polyglot_for_extra_stacks(
    stack_file: str, smoke_glob: str, tmp_path: Path
) -> None:
    p = tmp_path / stack_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")

    result = scaffold_tests_polyglot(tmp_path)

    assert result.skipped is False
    smoke_files = sorted(tmp_path.glob(smoke_glob))
    assert len(smoke_files) == 8


def test_scaffold_tests_polyglot_for_rails_smoke_suite(tmp_path: Path) -> None:
    (tmp_path / "Gemfile").write_text("source 'https://rubygems.org'\n")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "application.rb").write_text(
        "module App; class Application; end; end\n"
    )

    result = scaffold_tests_polyglot(tmp_path)

    assert result.skipped is False
    smoke_files = sorted((tmp_path / "test").glob("prep_smoke_test*.rb"))
    assert len(smoke_files) == 8


def test_scaffold_go_creates_placeholder_tests_per_source_file(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/app\n")
    pkg_dir = tmp_path / "internal" / "calc"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "add.go").write_text(
        "package calc\n\nfunc Add(a, b int) int { return a + b }\n"
    )
    (pkg_dir / "sub.go").write_text(
        "package calc\n\nfunc Sub(a, b int) int { return a - b }\n"
    )

    result = scaffold_tests_polyglot(tmp_path)

    assert result.skipped is False
    assert (pkg_dir / "add_test.go").is_file()
    assert (pkg_dir / "sub_test.go").is_file()
    assert len(list(pkg_dir.glob("prep_smoke*_test.go"))) == 8
    assert "internal/calc/add_test.go" in result.created_files
    assert "internal/calc/sub_test.go" in result.created_files
    assert "go placeholder batching" in result.progress


def test_scaffold_rust_creates_placeholder_tests_per_source_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'app'\nversion = '0.1.0'\n")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "lib.rs").write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
    (src_dir / "math.rs").write_text("pub fn sub(a: i32, b: i32) -> i32 { a - b }\n")

    result = scaffold_tests_polyglot(tmp_path)

    assert result.skipped is False
    assert (tmp_path / "tests" / "prep_src_lib_rs.rs").is_file()
    assert (tmp_path / "tests" / "prep_src_math_rs.rs").is_file()
    assert len(list((tmp_path / "tests").glob("prep_smoke*.rs"))) == 8
    assert "tests/prep_src_lib_rs.rs" in result.created_files
    assert "tests/prep_src_math_rs.rs" in result.created_files
    assert "rust placeholder batching" in result.progress


def test_scaffold_go_batches_across_runs(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/app\n")
    pkg_dir = tmp_path / "internal" / "calc"
    pkg_dir.mkdir(parents=True)
    for idx in range(13):
        (pkg_dir / f"f{idx}.go").write_text(
            f"package calc\n\nfunc F{idx}() int {{ return {idx} }}\n"
        )

    first = scaffold_tests_polyglot(tmp_path)
    second = scaffold_tests_polyglot(tmp_path)

    first_tests = [
        f
        for f in first.created_files
        if f.startswith("internal/calc/f") and f.endswith("_test.go")
    ]
    second_tests = [
        f
        for f in second.created_files
        if f.startswith("internal/calc/f") and f.endswith("_test.go")
    ]
    assert len(first_tests) == 12
    assert len(second_tests) == 1
    assert "pending before batch 13" in first.progress
    assert "pending before batch 1" in second.progress


def test_scaffold_rust_batches_across_runs(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname='app'\nversion='0.1.0'\n")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for idx in range(14):
        (src_dir / f"m{idx}.rs").write_text(f"pub fn m{idx}() -> i32 {{ {idx} }}\n")

    first = scaffold_tests_polyglot(tmp_path)
    second = scaffold_tests_polyglot(tmp_path)

    first_tests = [
        f
        for f in first.created_files
        if f.startswith("tests/prep_src_m") and f.endswith("_rs.rs")
    ]
    second_tests = [
        f
        for f in second.created_files
        if f.startswith("tests/prep_src_m") and f.endswith("_rs.rs")
    ]
    assert len(first_tests) == 12
    assert len(second_tests) == 2
    assert "pending before batch 14" in first.progress
    assert "pending before batch 2" in second.progress


def test_node_ui_framework_repo_is_handled_generically(tmp_path: Path) -> None:
    pkg = {
        "name": "ui-app",
        "private": True,
        "scripts": {
            "lint": "echo lint",
            "test": "echo test",
            "build": "echo build",
        },
        # top frameworks sample (React/Next/Vue/Svelte)
        "dependencies": {
            "react": "^19.0.0",
            "next": "^15.0.0",
            "vue": "^3.0.0",
            "svelte": "^5.0.0",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    stack = detect_prep_stack(tmp_path)

    assert stack == "node"
