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

# --- Factory Tests ---


class TestCIScaffoldResultFactory:
    def test_creates_default_instance(self) -> None:
        result = CIScaffoldResultFactory.create()
        assert isinstance(result, CIScaffoldResult)
        assert result.created is True
        assert result.skipped is False
        assert result.language == "python"
        assert result.workflow_path == ".github/workflows/quality.yml"

    def test_creates_skipped_instance(self) -> None:
        result = CIScaffoldResultFactory.create(
            created=False, skipped=True, skip_reason="already exists"
        )
        assert result.created is False
        assert result.skipped is True
        assert result.skip_reason == "already exists"


# --- Existing Workflow Detection ---


class TestHasQualityWorkflow:
    def test_finds_existing_quality_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: make quality\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is True
        assert name == "ci.yml"

    def test_no_workflows_dir(self, tmp_path: Path) -> None:
        found, name = has_quality_workflow(tmp_path)
        assert found is False
        assert name == ""

    def test_workflows_dir_empty(self, tmp_path: Path) -> None:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        found, name = has_quality_workflow(tmp_path)
        assert found is False
        assert name == ""

    def test_workflow_without_quality(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: npm test\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is False
        assert name == ""

    def test_finds_yaml_extension(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yaml").write_text("steps:\n  - run: make quality\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is True
        assert name == "ci.yaml"

    def test_quality_yml_already_exists(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "quality.yml").write_text("run: make quality\n")

        found, name = has_quality_workflow(tmp_path)
        assert found is True
        assert name == "quality.yml"

    def test_skips_unreadable_workflow_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("steps:\n  - run: make quality\n")

        def raise_oserror(*_args: object, **_kwargs: object) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", raise_oserror)

        found, name = has_quality_workflow(tmp_path)

        assert found is False
        assert name == ""


# --- Workflow Generation ---


class TestGenerateWorkflow:
    def test_python_workflow_has_setup_python(self) -> None:
        wf = generate_workflow("python")
        assert "actions/setup-python@v5" in wf
        assert "python-version" in wf

    def test_python_workflow_has_make_quality(self) -> None:
        wf = generate_workflow("python")
        assert "make quality" in wf

    def test_python_workflow_has_correct_triggers(self) -> None:
        wf = generate_workflow("python")
        assert "pull_request:" in wf
        assert "push:" in wf
        assert "branches: [main]" in wf

    def test_javascript_workflow_has_setup_node(self) -> None:
        wf = generate_workflow("javascript")
        assert "actions/setup-node@v4" in wf
        assert "node-version" in wf

    def test_javascript_workflow_has_npm_ci(self) -> None:
        wf = generate_workflow("javascript")
        assert "npm ci" in wf

    def test_mixed_workflow_has_both_setups(self) -> None:
        wf = generate_workflow("mixed")
        assert "actions/setup-python@v5" in wf
        assert "actions/setup-node@v4" in wf

    def test_mixed_workflow_has_both_install_steps(self) -> None:
        wf = generate_workflow("mixed")
        assert "npm ci" in wf
        assert "pip install" in wf

    def test_unknown_language_returns_minimal_workflow(self) -> None:
        wf = generate_workflow("unknown")
        assert "make quality" in wf
        assert "setup-python" not in wf
        assert "setup-node" not in wf

    def test_unrecognized_language_falls_back_to_unknown_workflow(self) -> None:
        wf = generate_workflow("ruby")
        assert "make quality" in wf
        assert "setup-python" not in wf
        assert "setup-node" not in wf

    @pytest.mark.parametrize("lang", ["python", "javascript", "mixed", "unknown"])
    def test_workflow_has_valid_structure(self, lang: str) -> None:
        wf = generate_workflow(lang)
        assert wf.startswith("name: Quality")
        assert "jobs:" in wf
        assert "quality:" in wf
        assert "runs-on: ubuntu-latest" in wf

    @pytest.mark.parametrize("lang", ["python", "javascript", "mixed", "unknown"])
    def test_all_workflows_have_checkout(self, lang: str) -> None:
        wf = generate_workflow(lang)
        assert "actions/checkout@v4" in wf


# --- Full Scaffolding ---


class TestScaffoldCI:
    def test_creates_workflow_for_python_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.skipped is False
        assert result.language == "python"
        assert result.workflow_path == ".github/workflows/quality.yml"
        assert (tmp_path / ".github" / "workflows" / "quality.yml").exists()

    def test_creates_workflow_for_js_repo(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.language == "javascript"
        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert "setup-node" in content

    def test_creates_workflow_for_mixed_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()
        (tmp_path / "package.json").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.language == "mixed"
        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert "setup-python" in content
        assert "setup-node" in content

    def test_creates_workflows_directory(self, tmp_path: Path) -> None:
        assert not (tmp_path / ".github").exists()

        scaffold_ci(tmp_path)

        assert (tmp_path / ".github" / "workflows").is_dir()

    def test_skips_when_quality_workflow_exists(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("run: make quality\n")

        result = scaffold_ci(tmp_path)

        assert result.created is False
        assert result.skipped is True
        assert "ci.yml" in result.skip_reason
        assert not (wf_dir / "quality.yml").exists()

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()

        result = scaffold_ci(tmp_path, dry_run=True)

        assert result.created is False
        assert result.skipped is False
        assert result.language == "python"
        assert result.workflow_path == ".github/workflows/quality.yml"
        assert not (tmp_path / ".github" / "workflows" / "quality.yml").exists()

    def test_scaffold_ci_is_idempotent_when_run_twice(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()

        first = scaffold_ci(tmp_path)
        second = scaffold_ci(tmp_path)

        assert first.created is True
        assert second.created is False
        assert second.skipped is True

    def test_does_not_skip_for_unrelated_workflow(self, tmp_path: Path) -> None:
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "deploy.yml").write_text("run: kubectl apply\n")
        (tmp_path / "pyproject.toml").touch()

        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.skipped is False
        assert (wf_dir / "quality.yml").exists()

    def test_creates_workflow_for_unknown_repo(self, tmp_path: Path) -> None:
        result = scaffold_ci(tmp_path)

        assert result.created is True
        assert result.language == "unknown"
        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert "make quality" in content
        assert "setup-python" not in content
        assert "setup-node" not in content

    def test_generated_file_has_valid_structure(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").touch()

        scaffold_ci(tmp_path)

        content = (tmp_path / ".github" / "workflows" / "quality.yml").read_text()
        assert content.startswith("name: Quality")
        assert "make quality" in content
        assert "jobs:" in content

    def test_raises_on_write_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "pyproject.toml").touch()

        def raise_oserror(*_args: object, **_kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "write_text", raise_oserror)

        with pytest.raises(OSError, match="permission denied"):
            scaffold_ci(tmp_path)
