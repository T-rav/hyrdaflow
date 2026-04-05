"""Tests for makefile_contract module."""

from __future__ import annotations

from pathlib import Path

import pytest

from makefile_contract import (
    OPTIONAL_TARGETS,
    REQUIRED_TARGETS,
    ContractResult,
    validate,
    validate_and_repair,
)


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo directory."""
    return tmp_path


class TestContractConstants:
    """Verify the contract definition is coherent."""

    def test_required_targets_are_nonempty(self) -> None:
        assert len(REQUIRED_TARGETS) > 0

    def test_quality_in_required(self) -> None:
        assert "quality" in REQUIRED_TARGETS

    def test_quality_lite_in_required(self) -> None:
        assert "quality-lite" in REQUIRED_TARGETS

    def test_no_overlap_between_required_and_optional(self) -> None:
        overlap = set(REQUIRED_TARGETS) & set(OPTIONAL_TARGETS)
        assert overlap == set()


class TestValidate:
    """Test read-only validation."""

    def test_missing_makefile_fails(self, tmp_repo: Path) -> None:
        result = validate(tmp_repo)

        assert result.valid is False
        assert set(result.missing) == set(REQUIRED_TARGETS)

    def test_empty_makefile_fails(self, tmp_repo: Path) -> None:
        (tmp_repo / "Makefile").write_text("", encoding="utf-8")

        result = validate(tmp_repo)

        assert result.valid is False
        assert set(result.missing) == set(REQUIRED_TARGETS)

    def test_complete_makefile_passes(self, tmp_repo: Path) -> None:
        lines = [f"{t}:\n\techo {t}\n" for t in REQUIRED_TARGETS]
        (tmp_repo / "Makefile").write_text("\n".join(lines), encoding="utf-8")

        result = validate(tmp_repo)

        assert result.valid is True
        assert result.missing == []
        assert set(result.present) == set(REQUIRED_TARGETS)

    def test_partial_makefile_reports_missing(self, tmp_repo: Path) -> None:
        content = "lint:\n\techo lint\n\ntest:\n\techo test\n"
        (tmp_repo / "Makefile").write_text(content, encoding="utf-8")

        result = validate(tmp_repo)

        assert result.valid is False
        assert "lint" not in result.missing
        assert "test" not in result.missing
        assert "quality" in result.missing

    def test_optional_targets_tracked(self, tmp_repo: Path) -> None:
        lines = [f"{t}:\n\techo {t}\n" for t in REQUIRED_TARGETS]
        (tmp_repo / "Makefile").write_text("\n".join(lines), encoding="utf-8")

        result = validate(tmp_repo)

        assert result.valid is True
        for opt in OPTIONAL_TARGETS:
            assert opt in result.optional_missing

    def test_prerequisite_only_targets_detected(self, tmp_repo: Path) -> None:
        content = (
            "lint:\n\techo lint\n\n"
            "lint-check:\n\techo lint-check\n\n"
            "test:\n\techo test\n\n"
            "typecheck:\n\techo typecheck\n\n"
            "security:\n\techo security\n\n"
            "quality-lite: lint-check typecheck security\n\n"
            "quality: quality-lite test\n"
        )
        (tmp_repo / "Makefile").write_text(content, encoding="utf-8")

        result = validate(tmp_repo)

        assert result.valid is True

    def test_variable_assignments_not_confused_with_targets(
        self, tmp_repo: Path
    ) -> None:
        content = (
            "CC := gcc\n"
            "CFLAGS ::= -Wall\n"
            "lint:\n\techo lint\n\n"
            "lint-check:\n\techo lint-check\n\n"
            "test:\n\techo test\n\n"
            "typecheck:\n\techo typecheck\n\n"
            "security:\n\techo security\n\n"
            "quality-lite: lint-check typecheck security\n\n"
            "quality: quality-lite test\n"
        )
        (tmp_repo / "Makefile").write_text(content, encoding="utf-8")

        result = validate(tmp_repo)

        assert result.valid is True
        assert "CC" not in result.present


class TestValidateAndRepair:
    """Test validation with auto-repair."""

    def test_repair_generates_makefile_for_python(self, tmp_repo: Path) -> None:
        (tmp_repo / "pyproject.toml").write_text("[project]\nname='x'\n")

        result = validate_and_repair(tmp_repo)

        assert result.repaired is True
        assert (tmp_repo / "Makefile").is_file()

        post = validate(tmp_repo)
        assert post.valid is True

    def test_repair_merges_missing_targets(self, tmp_repo: Path) -> None:
        (tmp_repo / "Makefile").write_text(
            "lint:\n\truff check . --fix\n", encoding="utf-8"
        )
        (tmp_repo / "pyproject.toml").write_text("[project]\nname='x'\n")

        result = validate_and_repair(tmp_repo, language="python")

        assert result.repaired is True
        content = (tmp_repo / "Makefile").read_text()
        assert "quality:" in content
        assert "typecheck:" in content

    def test_repair_preserves_existing_targets(self, tmp_repo: Path) -> None:
        original = "lint:\n\tmy-custom-linter .\n"
        (tmp_repo / "Makefile").write_text(original, encoding="utf-8")
        (tmp_repo / "pyproject.toml").write_text("[project]\nname='x'\n")

        validate_and_repair(tmp_repo, language="python")

        content = (tmp_repo / "Makefile").read_text()
        assert "my-custom-linter" in content

    def test_already_valid_returns_not_repaired(self, tmp_repo: Path) -> None:
        lines = [f"{t}:\n\techo {t}\n" for t in REQUIRED_TARGETS]
        (tmp_repo / "Makefile").write_text("\n".join(lines), encoding="utf-8")

        result = validate_and_repair(tmp_repo, language="python")

        assert result.valid is True
        assert result.repaired is False

    def test_unsupported_language_no_makefile(self, tmp_repo: Path) -> None:
        result = validate_and_repair(tmp_repo, language="brainfuck")

        assert result.valid is False
        assert result.repaired is False

    def test_explicit_language_skips_detection(self, tmp_repo: Path) -> None:
        (tmp_repo / "package.json").write_text('{"name":"x"}')

        result = validate_and_repair(tmp_repo, language="node")

        assert result.repaired is True
        content = (tmp_repo / "Makefile").read_text()
        assert "eslint" in content


class TestContractResult:
    """Test ContractResult dataclass."""

    def test_default_values(self) -> None:
        result = ContractResult(valid=True)

        assert result.missing == []
        assert result.present == []
        assert result.optional_missing == []
        assert result.warnings == []
        assert result.repaired is False
