"""Tests for CI workflow scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci_scaffold import (
    CIScaffoldResult,
    generate_workflow,
    has_quality_workflow,
    scaffold_ci,
)
from tests.conftest import CIScaffoldResultFactory


class TestCIScaffoldResultFactory:
    def test_creates_default_instance(self) -> None:
        result = CIScaffoldResultFactory.create()
        assert isinstance(result, CIScaffoldResult)
        assert result.created is True
        assert result.skipped is False
        assert result.workflow_path == ".github/workflows/quality.yml"


class TestHasQualityWorkflow:
    def test_finds_managed_marker(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("# prep-managed: quality-workflow\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is True
        assert name == "ci.yml"

    def test_finds_legacy_make_quality(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: make quality\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is True
        assert name == "ci.yml"

    def test_returns_false_when_no_quality_marker(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: npm test\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is False
        assert name == ""


class TestGenerateWorkflow:
    @pytest.mark.parametrize(
        ("lang", "expected"),
        [
            ("python", "setup-python"),
            ("node", "setup-node"),
            ("javascript", "setup-node"),
            ("java", "setup-java"),
            ("ruby", "setup-ruby"),
            ("rails", "setup-ruby"),
            ("csharp", "setup-dotnet"),
            ("go", "setup-go"),
            ("rust", "discover-projects"),
            ("cpp", "discover-projects"),
        ],
    )
    def test_language_specific_templates(self, lang: str, expected: str) -> None:
        wf = generate_workflow(lang)
        assert expected in wf
        assert "prep-managed: quality-workflow" in wf
        assert "make quality-lite" in wf
        assert "make quality" in wf
        assert "|| true" not in wf

    def test_unknown_workflow_fallback(self) -> None:
        wf = generate_workflow("some-new-lang")
        assert "make quality-lite" in wf
        assert "make quality" in wf

    def test_workflow_discovery_ignores_hydra_folders(self) -> None:
        wf = generate_workflow("python")
        assert '"hydra", "hydraflow"' in wf


class TestScaffoldCI:
    def test_creates_workflow_for_python_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.skipped is False
        assert result.language == "python"
        assert (tmp_path / ".github" / "workflows" / "quality.yml").exists()

    def test_creates_workflow_for_csharp_repo(self, tmp_path: Path) -> None:
        (tmp_path / "App.sln").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.language == "csharp"
        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert "make quality-lite" in content
        assert "make quality" in content

    def test_creates_workflow_for_go_repo(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.language == "go"
        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert "make quality-lite" in content
        assert "make quality" in content

    def test_creates_workflow_for_rust_repo(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.language == "rust"
        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert "make quality-lite" in content
        assert "make quality" in content

    def test_skips_when_quality_workflow_exists(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("# prep-managed: quality-workflow\n")

        result = scaffold_ci(tmp_path)

        assert result.created is False
        assert result.skipped is True

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").touch()

        result = scaffold_ci(tmp_path, dry_run=True)

        assert result.created is False
        assert result.skipped is False
        assert result.language == "node"
        assert not (tmp_path / ".github" / "workflows" / "quality.yml").exists()

    def test_scaffold_ci_is_idempotent_when_run_twice(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()

        first = scaffold_ci(tmp_path)
        second = scaffold_ci(tmp_path)

        assert first.created is True
        assert second.created is False
        assert second.skipped is True
