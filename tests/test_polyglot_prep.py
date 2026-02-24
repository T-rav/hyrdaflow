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
    ("stack_file", "expected_file"),
    [
        ("App.sln", "tests/PrepSmokeTests.cs"),
        ("go.mod", "prep_smoke_test.go"),
        ("Cargo.toml", "tests/prep_smoke.rs"),
        ("CMakeLists.txt", "tests/prep_smoke.cpp"),
    ],
)
def test_scaffold_tests_polyglot_for_extra_stacks(
    stack_file: str, expected_file: str, tmp_path: Path
) -> None:
    p = tmp_path / stack_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")

    result = scaffold_tests_polyglot(tmp_path)

    assert result.skipped is False
    assert (tmp_path / expected_file).exists()


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
