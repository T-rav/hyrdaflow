"""Tests for makefile_scaffold module."""

from __future__ import annotations

from makefile_scaffold import (
    _check_prereq_deps,
    _diff_targets,
    _normalize_recipe,
    generate_makefile,
    merge_makefile,
    parse_makefile,
)


class TestParseMakefile:
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

    def test_handles_heredoc_recipe_body(self) -> None:
        content = "coverage-check:\n\t@python - <<'PY'\nimport json\nprint('ok')\nPY\n"
        result = parse_makefile(content)
        assert "coverage-check" in result
        assert "@python - <<'PY'" in result["coverage-check"]
        assert "import json" in result["coverage-check"]
        assert "PY" in result["coverage-check"]

    def test_handles_phony_declaration(self) -> None:
        content = ".PHONY: lint test\n\nlint:\n\truff check .\n"
        result = parse_makefile(content)
        assert "lint" in result
        assert ".PHONY" not in result

    def test_handles_whitespace_only(self) -> None:
        result = parse_makefile("   \n\n  \t  \n")
        assert result == {}


class TestGenerateMakefile:
    def test_generates_python_makefile(self) -> None:
        content = generate_makefile("python")
        assert "ruff check" in content
        assert "ruff format" in content
        assert "pyright" in content
        assert "pytest" in content

    def test_generates_standard_python_test_target(self) -> None:
        content = generate_makefile("python")
        assert "test:" in content
        assert "\tpytest tests/ -x -q\n" in content

    def test_generates_javascript_makefile(self) -> None:
        content = generate_makefile("javascript")
        assert "npx eslint" in content
        assert "npx tsc --noEmit" in content
        assert "npx vitest run --exclude='hydraflow/**'" in content

    def test_quality_target_chains_dependencies(self) -> None:
        content = generate_makefile("python")
        assert "smoke: test" in content
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
        assert "smoke" in content
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
        assert "smoke        Run smoke tests" in content

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

    def test_no_warning_for_recipe_indent_only_differences(self) -> None:
        existing = (
            "help:\n"
            '\t@echo "Available targets:"   \n'
            '\t@echo "  help         Show this help"  \n'
            '\t@echo "  lint         Run lint auto-fixes" \n'
            '\t@echo "  lint-check   Run lint checks" \n'
            '\t@echo "  lint-fix     Alias for lint" \n'
            '\t@echo "  typecheck    Run type checks" \n'
            '\t@echo "  security     Run security checks" \n'
            '\t@echo "  test         Run tests" \n'
            '\t@echo "  coverage-check Enforce coverage floor from reports" \n'
            '\t@echo "  coverage vars COVERAGE_MIN=70 COVERAGE_TARGET=70" \n'
            '\t@echo "  smoke        Run smoke tests" \n'
            '\t@echo "  quality-lite Run lint/type/security" \n'
            '\t@echo "  quality      Run quality-lite + tests" \n'
        )
        _, warnings = merge_makefile(existing, "python")
        assert not any(
            "Target 'help' exists with different recipe" in w for w in warnings
        )

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

    def test_warns_on_different_smoke_prerequisites(self) -> None:
        existing = "smoke: test-fast\n"
        _, warnings = merge_makefile(existing, "python")
        assert any("smoke" in w for w in warnings)

    def test_no_warning_when_quality_deps_match(self) -> None:
        # quality: exists with correct chain — no warning
        existing = (
            "smoke: test\n"
            "quality-lite: lint-check typecheck security\n"
            "quality: quality-lite test coverage-check\n"
        )
        _, warnings = merge_makefile(existing, "python")
        assert not any("smoke" in w for w in warnings)
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

    def test_warns_on_coverage_check_recipe_mismatch(self) -> None:
        # Regression: coverage-check warning path was previously untested.
        existing = "coverage-check:\n\t@echo 'custom coverage'\n"
        _, warnings = merge_makefile(existing, "python")
        assert any("coverage-check" in w for w in warnings)


class TestNormalizeRecipe:
    def test_strips_leading_trailing_whitespace(self) -> None:
        assert _normalize_recipe("  ruff check .  \n") == "ruff check ."

    def test_normalizes_multiline_recipe(self) -> None:
        result = _normalize_recipe("  ruff check .\n  ruff format .\n")
        assert result == "ruff check .\nruff format ."

    def test_empty_string_returns_empty(self) -> None:
        assert _normalize_recipe("") == ""

    def test_preserves_internal_content(self) -> None:
        result = _normalize_recipe("\t@python - <<'PY'\nimport json\nPY\n")
        assert "import json" in result
        assert "@python" in result


class TestDiffTargets:
    def test_returns_missing_targets(self) -> None:
        existing: dict[str, str] = {"lint": "ruff check ."}
        template: dict[str, str | None] = {"lint": "ruff check .", "test": "pytest"}
        to_add, warnings = _diff_targets(existing, template)
        assert "test" in to_add
        assert "lint" not in to_add
        assert not warnings

    def test_warns_on_recipe_mismatch(self) -> None:
        existing: dict[str, str] = {"lint": "npm test"}
        template: dict[str, str | None] = {"lint": "ruff check ."}
        to_add, warnings = _diff_targets(existing, template)
        assert not to_add
        assert any("lint" in w for w in warnings)

    def test_skips_recipe_check_for_prereq_only_targets(self) -> None:
        existing: dict[str, str] = {"quality": ""}
        template: dict[str, str | None] = {"quality": None}
        to_add, warnings = _diff_targets(existing, template)
        assert not to_add
        assert not warnings

    def test_empty_existing_returns_all_template_targets(self) -> None:
        existing: dict[str, str] = {}
        template: dict[str, str | None] = {"lint": "ruff check .", "test": "pytest"}
        to_add, warnings = _diff_targets(existing, template)
        assert set(to_add) == {"lint", "test"}
        assert not warnings

    def test_empty_template_returns_nothing(self) -> None:
        existing: dict[str, str] = {"lint": "ruff check ."}
        template: dict[str, str | None] = {}
        to_add, warnings = _diff_targets(existing, template)
        assert not to_add
        assert not warnings


class TestCheckPrereqDeps:
    def test_warns_on_mismatched_quality_deps(self) -> None:
        content = "quality: build deploy\n"
        existing = parse_makefile(content)
        warnings = _check_prereq_deps(content, existing)
        assert any("quality" in w for w in warnings)

    def test_warns_on_mismatched_quality_lite_deps(self) -> None:
        content = "quality-lite: lint-check typecheck\n"
        existing = parse_makefile(content)
        warnings = _check_prereq_deps(content, existing)
        assert any("quality-lite" in w for w in warnings)

    def test_warns_on_mismatched_smoke_deps(self) -> None:
        content = "smoke: test-fast\n"
        existing = parse_makefile(content)
        warnings = _check_prereq_deps(content, existing)
        assert any("smoke" in w for w in warnings)

    def test_no_warning_when_all_deps_match(self) -> None:
        content = (
            "smoke: test\n"
            "quality-lite: lint-check typecheck security\n"
            "quality: quality-lite test coverage-check\n"
        )
        existing = parse_makefile(content)
        warnings = _check_prereq_deps(content, existing)
        assert not warnings

    def test_no_warning_when_targets_absent(self) -> None:
        content = "lint:\n\truff check .\n"
        existing = parse_makefile(content)
        warnings = _check_prereq_deps(content, existing)
        assert not warnings
