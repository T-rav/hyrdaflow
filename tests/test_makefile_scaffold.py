"""Tests for makefile_scaffold module."""

from __future__ import annotations

from pathlib import Path

from makefile_scaffold import (
    ScaffoldResult,
    discover_project_paths,
    generate_makefile,
    merge_makefile,
    parse_makefile,
    scaffold_makefile,
    scaffold_makefiles,
)


class TestParseMakefile:
    """Tests for parse_makefile()."""

    def test_parses_simple_targets(self) -> None:
        content = "lint:\n\truff check .\n\ntest:\n\tpytest\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert "ruff check ." in result["lint"]
        assert "test" in result
        assert "pytest" in result["test"]

    def test_handles_targets_with_dependencies(self) -> None:
        content = "quality: quality-lite test\n\ntest:\n\tpytest\n"
        result = parse_makefile(content)
        assert "quality" in result
        assert "test" in result

    def test_ignores_comments_and_variables(self) -> None:
        content = "# A comment\nVAR = value\n\nlint:\n\truff check .\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert len(result) == 1

    def test_ignores_immediate_assignment_variables(self) -> None:
        # CC := gcc uses := which should not be treated as a target
        content = "CC := gcc\n\nlint:\n\truff check .\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert "CC" not in result
        assert len(result) == 1

    def test_ignores_posix_immediate_assignment_variables(self) -> None:
        # CC ::= gcc uses ::= which should not be treated as a target
        content = "CC ::= gcc\n\nlint:\n\truff check .\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert "CC" not in result
        assert len(result) == 1

    def test_handles_empty_makefile(self) -> None:
        result = parse_makefile("")
        assert result == {}

    def test_handles_multiline_recipes(self) -> None:
        content = "lint:\n\truff check . --fix\n\truff format .\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert "ruff check . --fix" in result["lint"]
        assert "ruff format ." in result["lint"]

    def test_handles_phony_declaration(self) -> None:
        content = ".PHONY: lint test\n\nlint:\n\truff check .\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert ".PHONY" not in result

    def test_handles_whitespace_only(self) -> None:
        result = parse_makefile("   \n\n  \t  \n")
        assert result == {}


class TestGenerateMakefile:
    """Tests for generate_makefile()."""

    def test_generates_python_makefile(self) -> None:
        content = generate_makefile("python")
        assert "ruff check" in content
        assert "ruff format" in content
        assert "pyright" in content
        assert "pytest" in content

    def test_generates_javascript_makefile(self) -> None:
        content = generate_makefile("javascript")
        assert "npx eslint" in content
        assert "npx tsc --noEmit" in content
        assert "npx vitest run --exclude='hydraflow/**'" in content

    def test_quality_target_chains_dependencies(self) -> None:
        content = generate_makefile("python")
        assert "quality-lite: lint-check typecheck security" in content
        assert "quality: quality-lite test coverage-check" in content

    def test_includes_phony_declaration(self) -> None:
        content = generate_makefile("python")
        assert ".PHONY:" in content
        assert "help" in content
        assert "lint" in content
        assert "lint-check" in content
        assert "lint-fix" in content
        assert "typecheck" in content
        assert "security" in content
        assert "test" in content
        assert "quality-lite" in content
        assert "quality" in content

    def test_sets_help_as_default_goal(self) -> None:
        content = generate_makefile("python")
        assert ".DEFAULT_GOAL := help" in content
        assert "COVERAGE_MIN ?= 70" in content
        assert "COVERAGE_TARGET ?= 70" in content
        assert "help:" in content
        assert "Available targets:" in content
        assert "coverage vars COVERAGE_MIN=70 COVERAGE_TARGET=70" in content

    def test_unknown_language_returns_empty(self) -> None:
        content = generate_makefile("unknown")
        assert content == ""

    def test_recipes_use_tabs_not_spaces(self) -> None:
        content = generate_makefile("python")
        recipe_lines = [
            line
            for line in content.split("\n")
            if line
            and not line.startswith((".", "#"))
            and ":" not in line
            and "=" not in line
        ]
        for line in recipe_lines:
            assert line.startswith("\t"), f"Recipe line should start with tab: {line!r}"

    def test_mixed_no_longer_defaults_to_python(self) -> None:
        content = generate_makefile("mixed")
        assert content == ""


class TestMergeMakefile:
    """Tests for merge_makefile()."""

    def test_adds_missing_targets_to_existing(self) -> None:
        existing = "lint:\n\truff check . --fix\n"
        new_content, _ = merge_makefile(existing, "python")
        assert "quality:" in new_content
        assert "test:" in new_content
        assert "typecheck:" in new_content
        # Original lint should be preserved
        assert "lint:\n\truff check . --fix" in new_content

    def test_skips_existing_targets_with_same_recipe(self) -> None:
        existing = "lint:\n\truff check . --fix && ruff format .\n"
        new_content, _ = merge_makefile(existing, "python")
        # Original lint should appear exactly once (not duplicated)
        assert new_content.count("\nlint:\n") + new_content.startswith("lint:\n") == 1

    def test_warns_on_different_recipe(self) -> None:
        existing = "test:\n\tnpm test\n"
        _, warnings = merge_makefile(existing, "python")
        assert any("test" in w for w in warnings)

    def test_preserves_existing_content_order(self) -> None:
        existing = "clean:\n\trm -rf dist\n\nbuild:\n\tpython -m build\n"
        new_content, _ = merge_makefile(existing, "python")
        # Original targets should appear before new ones
        clean_pos = new_content.index("clean:")
        lint_pos = new_content.index("lint:")
        assert clean_pos < lint_pos

    def test_updates_phony_line(self) -> None:
        existing = ".PHONY: clean build\n\nclean:\n\trm -rf dist\n"
        new_content, _ = merge_makefile(existing, "python")
        # .PHONY should include new targets and preserve original entries
        assert "help" in new_content
        assert "lint" in new_content
        assert "test" in new_content
        # build is in .PHONY but has no target definition — must be preserved
        phony_line = next(
            ln for ln in new_content.split("\n") if ln.startswith(".PHONY")
        )
        assert "build" in phony_line
        assert "clean" in phony_line

    def test_preserves_phony_entries_without_target_definitions(self) -> None:
        # Targets listed in .PHONY but without recipes (e.g. defined in included files)
        # must not be dropped when the .PHONY line is rewritten.
        existing = ".PHONY: deploy release\n\nclean:\n\trm -rf dist\n"
        new_content, _ = merge_makefile(existing, "python")
        phony_line = next(
            ln for ln in new_content.split("\n") if ln.startswith(".PHONY")
        )
        assert "deploy" in phony_line
        assert "release" in phony_line

    def test_warns_on_different_quality_prerequisites(self) -> None:
        # quality: exists but chains different targets — should warn
        existing = "quality: build deploy\n"
        _, warnings = merge_makefile(existing, "python")
        assert any("quality" in w for w in warnings)

    def test_warns_on_different_quality_lite_prerequisites(self) -> None:
        # quality-lite: exists but chains different targets — should warn
        existing = "quality-lite: lint-check typecheck\n"
        _, warnings = merge_makefile(existing, "python")
        assert any("quality-lite" in w for w in warnings)

    def test_no_warning_when_quality_deps_match(self) -> None:
        # quality: exists with correct chain — no warning
        existing = (
            "quality-lite: lint-check typecheck security\n"
            "quality: quality-lite test coverage-check\n"
        )
        _, warnings = merge_makefile(existing, "python")
        assert not any("quality" in w for w in warnings)
        assert not any("quality-lite" in w for w in warnings)

    def test_handles_makefile_without_phony(self) -> None:
        existing = "clean:\n\trm -rf dist\n"
        new_content, _ = merge_makefile(existing, "python")
        assert ".PHONY:" in new_content

    def test_merge_adds_default_goal_when_missing(self) -> None:
        existing = "clean:\n\trm -rf dist\n"
        new_content, _ = merge_makefile(existing, "python")
        assert ".DEFAULT_GOAL := help" in new_content

    def test_merge_preserves_existing_default_goal(self) -> None:
        existing = ".DEFAULT_GOAL := quality\n\nclean:\n\trm -rf dist\n"
        new_content, _ = merge_makefile(existing, "python")
        assert ".DEFAULT_GOAL := quality" in new_content
        assert new_content.count(".DEFAULT_GOAL") == 1


class TestScaffoldMakefile:
    """Tests for scaffold_makefile()."""

    def test_creates_new_makefile_for_python_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        result = scaffold_makefile(tmp_path)
        assert result.created is True
        assert result.language == "python"
        makefile = tmp_path / "Makefile"
        assert makefile.exists()
        content = makefile.read_text()
        assert "ruff" in content
        assert "pytest" in content

    def test_creates_new_makefile_for_js_repo(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").touch()
        result = scaffold_makefile(tmp_path)
        assert result.created is True
        assert result.language == "node"
        content = (tmp_path / "Makefile").read_text()
        assert "npx eslint" in content

    def test_creates_new_makefile_for_go_repo(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").touch()
        result = scaffold_makefile(tmp_path)
        assert result.created is True
        assert result.language == "go"
        content = (tmp_path / "Makefile").read_text()
        assert "go test ./..." in content

    def test_creates_new_makefile_for_rust_repo(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").touch()
        result = scaffold_makefile(tmp_path)
        assert result.created is True
        assert result.language == "rust"
        content = (tmp_path / "Makefile").read_text()
        assert "cargo test --all-targets" in content

    def test_merges_into_existing_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        makefile = tmp_path / "Makefile"
        makefile.write_text("clean:\n\trm -rf dist\n")
        result = scaffold_makefile(tmp_path)
        assert result.created is False
        assert len(result.targets_added) > 0
        content = makefile.read_text()
        assert "clean:" in content
        assert "lint:" in content

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        result = scaffold_makefile(tmp_path, dry_run=True)
        assert result.language == "python"
        assert not (tmp_path / "Makefile").exists()

    def test_dry_run_does_not_modify_existing_makefile(self, tmp_path: Path) -> None:
        # dry_run=True on the merge path must not write to the existing file
        (tmp_path / "pyproject.toml").touch()
        makefile = tmp_path / "Makefile"
        original = "clean:\n\trm -rf dist\n"
        makefile.write_text(original)
        result = scaffold_makefile(tmp_path, dry_run=True)
        # File must be unchanged
        assert makefile.read_text() == original
        # But the result should still report what would have been added
        assert len(result.targets_added) > 0
        assert result.language == "python"

    def test_returns_warnings_for_conflicts(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        makefile = tmp_path / "Makefile"
        makefile.write_text("test:\n\tnpm test\n")
        result = scaffold_makefile(tmp_path)
        assert len(result.warnings) > 0
        assert any("test" in w for w in result.warnings)

    def test_skips_unknown_language(self, tmp_path: Path) -> None:
        result = scaffold_makefile(tmp_path)
        assert result.language == "unknown"
        assert len(result.targets_added) == 0
        assert not (tmp_path / "Makefile").exists()

    def test_idempotent_on_complete_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        scaffold_makefile(tmp_path)
        content_first = (tmp_path / "Makefile").read_text()
        result = scaffold_makefile(tmp_path)
        content_second = (tmp_path / "Makefile").read_text()
        assert content_first == content_second
        assert len(result.targets_added) == 0

    def test_finds_lowercase_makefile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        makefile = tmp_path / "makefile"
        makefile.write_text("clean:\n\trm -rf dist\n")
        result = scaffold_makefile(tmp_path)
        assert result.created is False
        # Should have merged into the existing lowercase makefile
        content = makefile.read_text()
        assert "lint:" in content

    def test_finds_gnumakefile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        makefile = tmp_path / "GNUmakefile"
        makefile.write_text("clean:\n\trm -rf dist\n")
        result = scaffold_makefile(tmp_path)
        assert result.created is False
        content = makefile.read_text()
        assert "lint:" in content

    def test_empty_makefile_treated_as_new(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        makefile = tmp_path / "Makefile"
        makefile.write_text("   \n\n")
        result = scaffold_makefile(tmp_path)
        assert result.created is True
        content = makefile.read_text()
        assert "ruff" in content

    def test_scaffold_result_fields(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        result = scaffold_makefile(tmp_path)
        assert isinstance(result, ScaffoldResult)
        assert isinstance(result.created, bool)
        assert isinstance(result.targets_added, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.skipped, list)
        assert isinstance(result.language, str)


class TestScaffoldMakefiles:
    def test_discovers_multiple_project_paths(self, tmp_path: Path) -> None:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "pyproject.toml").touch()
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "package.json").write_text("{}\n")
        paths = discover_project_paths(tmp_path)
        rels = {str(p.relative_to(tmp_path)) for p in paths}
        assert "backend" in rels
        assert "frontend" in rels

    def test_ignores_git_submodule_paths(self, tmp_path: Path) -> None:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "pyproject.toml").touch()
        (tmp_path / "hydraflow").mkdir()
        (tmp_path / "hydraflow" / "package.json").write_text("{}\n")
        (tmp_path / ".gitmodules").write_text(
            '[submodule "hydraflow"]\n\tpath = hydraflow\n\turl = https://example.com/hydraflow.git\n'
        )

        paths = discover_project_paths(tmp_path)
        rels = {str(p.relative_to(tmp_path)) for p in paths}
        assert "backend" in rels
        assert "hydraflow" not in rels

    def test_ignores_hydra_named_folder_without_gitmodules(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "pyproject.toml").touch()
        (tmp_path / "hydra").mkdir()
        (tmp_path / "hydra" / "package.json").write_text("{}\n")

        paths = discover_project_paths(tmp_path)
        rels = {str(p.relative_to(tmp_path)) for p in paths}
        assert "backend" in rels
        assert "hydra" not in rels

    def test_scaffolds_makefiles_for_multiple_projects(self, tmp_path: Path) -> None:
        (tmp_path / "backend").mkdir()
        (tmp_path / "backend" / "pyproject.toml").touch()
        (tmp_path / "frontend").mkdir()
        (tmp_path / "frontend" / "package.json").write_text("{}\n")
        result = scaffold_makefiles(tmp_path)
        assert "backend" in result.results
        assert "frontend" in result.results
        assert (tmp_path / "backend" / "Makefile").exists()
        assert (tmp_path / "frontend" / "Makefile").exists()
