"""Tests for lint_scaffold.py — linting and type-checking config scaffolding."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lint_scaffold import (
    _ensure_js_dev_deps,
    _ensure_python_dev_deps,
    _has_eslint_config,
    _has_pyright_config,
    _has_ruff_config,
    _has_tsconfig,
    _scaffold_eslint,
    _scaffold_pyright,
    _scaffold_ruff,
    _scaffold_tsconfig,
    has_typescript_files,
    scaffold_lint_config,
)
from tests.conftest import LintScaffoldResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pyproject(repo: Path, content: str = "") -> Path:
    """Create a pyproject.toml with given content."""
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(content)
    return pyproject


def _make_package_json(repo: Path, content: dict | None = None) -> Path:
    """Create a package.json with given content."""
    pkg = repo / "package.json"
    pkg.write_text(json.dumps(content or {"name": "test"}, indent=2) + "\n")
    return pkg


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestLintScaffoldResultFactory:
    """Tests for the LintScaffoldResultFactory."""

    def test_creates_default_result(self) -> None:
        result = LintScaffoldResultFactory.create()
        assert result.scaffolded == []
        assert result.skipped == []
        assert result.modified_files == []
        assert result.created_files == []
        assert result.language == "python"

    def test_creates_custom_result(self) -> None:
        result = LintScaffoldResultFactory.create(
            scaffolded=["ruff"],
            skipped=["pyright"],
            language="mixed",
        )
        assert result.scaffolded == ["ruff"]
        assert result.skipped == ["pyright"]
        assert result.language == "mixed"


# ---------------------------------------------------------------------------
# has_typescript_files tests
# ---------------------------------------------------------------------------


class TestHasTypescriptFiles:
    """Tests for has_typescript_files."""

    def test_finds_ts_files_in_src(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.ts").write_text("const x = 1;")
        assert has_typescript_files(tmp_path) is True

    def test_finds_tsx_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("export default () => <div/>;")
        assert has_typescript_files(tmp_path) is True

    def test_ignores_declaration_files(self, tmp_path: Path) -> None:
        (tmp_path / "types.d.ts").write_text("declare module 'foo';")
        assert has_typescript_files(tmp_path) is False

    def test_ignores_node_modules(self, tmp_path: Path) -> None:
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.ts").write_text("export {};")
        assert has_typescript_files(tmp_path) is False

    def test_ignores_hydra_folder(self, tmp_path: Path) -> None:
        hydra = tmp_path / "hydra" / "src"
        hydra.mkdir(parents=True)
        (hydra / "index.ts").write_text("export {};")
        assert has_typescript_files(tmp_path) is False

    def test_ignores_hydraflow_folder(self, tmp_path: Path) -> None:
        hydraflow = tmp_path / "hydraflow" / "src"
        hydraflow.mkdir(parents=True)
        (hydraflow / "index.ts").write_text("export {};")
        assert has_typescript_files(tmp_path) is False

    def test_has_typescript_files_returns_false_without_ts_files(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.js").write_text("const x = 1;")
        assert has_typescript_files(tmp_path) is False


# ---------------------------------------------------------------------------
# _has_ruff_config tests
# ---------------------------------------------------------------------------


class TestHasRuffConfig:
    """Tests for _has_ruff_config."""

    def test_detects_ruff_toml(self, tmp_path: Path) -> None:
        (tmp_path / "ruff.toml").write_text("line-length = 80\n")
        assert _has_ruff_config(tmp_path) is True

    def test_detects_dot_ruff_toml(self, tmp_path: Path) -> None:
        (tmp_path / ".ruff.toml").write_text("line-length = 80\n")
        assert _has_ruff_config(tmp_path) is True

    def test_detects_tool_ruff_in_pyproject(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[tool.ruff]\nline-length = 80\n")
        assert _has_ruff_config(tmp_path) is True

    def test_has_ruff_config_returns_false_when_absent(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        assert _has_ruff_config(tmp_path) is False

    def test_has_ruff_config_returns_false_without_pyproject(
        self, tmp_path: Path
    ) -> None:
        assert _has_ruff_config(tmp_path) is False

    def test_malformed_pyproject_with_ruff_string(self, tmp_path: Path) -> None:
        """Falls back to string matching for malformed TOML."""
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nbad = [\n")
        assert _has_ruff_config(tmp_path) is True


# ---------------------------------------------------------------------------
# _has_pyright_config tests
# ---------------------------------------------------------------------------


class TestHasPyrightConfig:
    """Tests for _has_pyright_config."""

    def test_detects_pyrightconfig_json(self, tmp_path: Path) -> None:
        (tmp_path / "pyrightconfig.json").write_text("{}")
        assert _has_pyright_config(tmp_path) is True

    def test_detects_tool_pyright_in_pyproject(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, '[tool.pyright]\npythonVersion = "3.11"\n')
        assert _has_pyright_config(tmp_path) is True

    def test_has_pyright_config_returns_false_when_missing(
        self, tmp_path: Path
    ) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        assert _has_pyright_config(tmp_path) is False

    def test_has_pyright_config_returns_false_without_pyproject(
        self, tmp_path: Path
    ) -> None:
        assert _has_pyright_config(tmp_path) is False


# ---------------------------------------------------------------------------
# _has_eslint_config tests
# ---------------------------------------------------------------------------


class TestHasEslintConfig:
    """Tests for _has_eslint_config."""

    def test_detects_eslintrc_json(self, tmp_path: Path) -> None:
        (tmp_path / ".eslintrc.json").write_text("{}")
        assert _has_eslint_config(tmp_path) is True

    def test_detects_eslint_config_js(self, tmp_path: Path) -> None:
        (tmp_path / "eslint.config.js").write_text("export default [];")
        assert _has_eslint_config(tmp_path) is True

    def test_detects_biome_json(self, tmp_path: Path) -> None:
        (tmp_path / "biome.json").write_text("{}")
        assert _has_eslint_config(tmp_path) is True

    def test_detects_eslintrc_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".eslintrc.yaml").write_text("rules: {}")
        assert _has_eslint_config(tmp_path) is True

    def test_has_eslint_config_returns_false_when_absent(self, tmp_path: Path) -> None:
        assert _has_eslint_config(tmp_path) is False


# ---------------------------------------------------------------------------
# _has_tsconfig tests
# ---------------------------------------------------------------------------


class TestHasTsconfig:
    """Tests for _has_tsconfig."""

    def test_detects_tsconfig(self, tmp_path: Path) -> None:
        (tmp_path / "tsconfig.json").write_text("{}")
        assert _has_tsconfig(tmp_path) is True

    def test_has_tsconfig_returns_false_when_absent(self, tmp_path: Path) -> None:
        assert _has_tsconfig(tmp_path) is False


# ---------------------------------------------------------------------------
# _scaffold_ruff tests
# ---------------------------------------------------------------------------


class TestScaffoldRuff:
    """Tests for _scaffold_ruff."""

    def test_appends_ruff_to_existing_pyproject(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        modified, created = _scaffold_ruff(tmp_path)
        assert modified == ["pyproject.toml"]
        assert created == []
        content = (tmp_path / "pyproject.toml").read_text()
        assert "[tool.ruff]" in content
        assert "[project]" in content  # original content preserved

    def test_creates_pyproject_with_ruff(self, tmp_path: Path) -> None:
        modified, created = _scaffold_ruff(tmp_path)
        assert modified == []
        assert created == ["pyproject.toml"]
        assert (tmp_path / "pyproject.toml").exists()

    def test_ruff_config_has_correct_defaults(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        _scaffold_ruff(tmp_path)
        data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
        ruff = data["tool"]["ruff"]
        assert ruff["line-length"] == 120
        assert ruff["target-version"] == "py311"
        lint = ruff["lint"]
        assert "E" in lint["select"]
        assert "F" in lint["select"]
        assert "W" in lint["select"]
        assert "I" in lint["select"]
        assert "UP" in lint["select"]

    def test_preserves_existing_pyproject_content(self, tmp_path: Path) -> None:
        original = "[project]\nname = 'my-project'\nversion = '1.0.0'\n"
        _make_pyproject(tmp_path, original)
        _scaffold_ruff(tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        assert "name = 'my-project'" in content
        assert "version = '1.0.0'" in content

    def test_result_is_valid_toml(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        _scaffold_ruff(tmp_path)
        # Should not raise
        tomllib.loads((tmp_path / "pyproject.toml").read_text())


# ---------------------------------------------------------------------------
# _scaffold_pyright tests
# ---------------------------------------------------------------------------


class TestScaffoldPyright:
    """Tests for _scaffold_pyright."""

    def test_appends_pyright_to_existing_pyproject(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        modified, created = _scaffold_pyright(tmp_path)
        assert modified == ["pyproject.toml"]
        assert created == []
        content = (tmp_path / "pyproject.toml").read_text()
        assert "[tool.pyright]" in content

    def test_creates_pyproject_with_pyright(self, tmp_path: Path) -> None:
        modified, created = _scaffold_pyright(tmp_path)
        assert modified == []
        assert created == ["pyproject.toml"]

    def test_pyright_config_has_correct_defaults(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        _scaffold_pyright(tmp_path)
        data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
        pyright = data["tool"]["pyright"]
        assert pyright["pythonVersion"] == "3.11"

    def test_result_is_valid_toml(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        _scaffold_pyright(tmp_path)
        tomllib.loads((tmp_path / "pyproject.toml").read_text())


# ---------------------------------------------------------------------------
# _ensure_python_dev_deps tests
# ---------------------------------------------------------------------------


class TestEnsurePythonDevDeps:
    """Tests for _ensure_python_dev_deps."""

    def test_adds_ruff_and_pyright_to_dev_deps(self, tmp_path: Path) -> None:
        _make_pyproject(
            tmp_path,
            "[project]\nname = 'test'\n\n[project.optional-dependencies]\ndev = [\n]\n",
        )
        result = _ensure_python_dev_deps(tmp_path)
        assert result == ["pyproject.toml"]
        content = (tmp_path / "pyproject.toml").read_text()
        assert "ruff" in content
        assert "pyright" in content

    def test_skips_if_already_present(self, tmp_path: Path) -> None:
        _make_pyproject(
            tmp_path,
            '[project]\nname = "test"\n\n[project.optional-dependencies]\n'
            'dev = [\n    "ruff>=0.4.0",\n    "pyright>=1.1.0",\n]\n',
        )
        result = _ensure_python_dev_deps(tmp_path)
        assert result == []

    def test_skips_if_no_pyproject(self, tmp_path: Path) -> None:
        result = _ensure_python_dev_deps(tmp_path)
        assert result == []

    def test_adds_only_missing_dep(self, tmp_path: Path) -> None:
        _make_pyproject(
            tmp_path,
            '[project]\nname = "test"\n\n[project.optional-dependencies]\n'
            'dev = [\n    "ruff>=0.4.0",\n]\n',
        )
        result = _ensure_python_dev_deps(tmp_path)
        assert result == ["pyproject.toml"]
        content = (tmp_path / "pyproject.toml").read_text()
        assert "pyright" in content

    def test_creates_dev_section_if_missing(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        result = _ensure_python_dev_deps(tmp_path)
        assert result == ["pyproject.toml"]
        content = (tmp_path / "pyproject.toml").read_text()
        assert "ruff" in content
        assert "pyright" in content

    def test_skips_when_optional_deps_exists_but_no_dev_key(
        self, tmp_path: Path
    ) -> None:
        """Should not create duplicate [project.optional-dependencies] when section exists without dev."""
        _make_pyproject(
            tmp_path,
            '[project]\nname = "test"\n\n[project.optional-dependencies]\ntest = [\n    "pytest",\n]\n',
        )
        result = _ensure_python_dev_deps(tmp_path)
        # Should skip rather than create a duplicate section (which would be invalid TOML)
        assert result == []
        content = (tmp_path / "pyproject.toml").read_text()
        # File should remain valid TOML
        data = tomllib.loads(content)
        # Only one optional-dependencies section — no duplicate header corruption
        assert list(data["project"]["optional-dependencies"].keys()) == ["test"]

    def test_result_is_valid_toml_after_dep_insertion(self, tmp_path: Path) -> None:
        """File must be valid TOML after inserting deps into an existing dev section."""
        _make_pyproject(
            tmp_path,
            '[project]\nname = "test"\n\n[project.optional-dependencies]\ndev = [\n]\n',
        )
        _ensure_python_dev_deps(tmp_path)
        # Should not raise
        tomllib.loads((tmp_path / "pyproject.toml").read_text())


# ---------------------------------------------------------------------------
# _scaffold_eslint tests
# ---------------------------------------------------------------------------


class TestScaffoldEslint:
    """Tests for _scaffold_eslint."""

    def test_creates_eslint_config_js(self, tmp_path: Path) -> None:
        created = _scaffold_eslint(tmp_path)
        assert created == ["eslint.config.js"]
        assert (tmp_path / "eslint.config.js").exists()

    def test_config_contains_rules(self, tmp_path: Path) -> None:
        _scaffold_eslint(tmp_path)
        content = (tmp_path / "eslint.config.js").read_text()
        assert "no-unused-vars" in content
        assert "no-undef" in content
        assert "warn" in content
        assert "error" in content

    def test_config_uses_flat_format(self, tmp_path: Path) -> None:
        _scaffold_eslint(tmp_path)
        content = (tmp_path / "eslint.config.js").read_text()
        assert "export default" in content


# ---------------------------------------------------------------------------
# _scaffold_tsconfig tests
# ---------------------------------------------------------------------------


class TestScaffoldTsconfig:
    """Tests for _scaffold_tsconfig."""

    def test_creates_tsconfig_json(self, tmp_path: Path) -> None:
        created = _scaffold_tsconfig(tmp_path)
        assert created == ["tsconfig.json"]
        assert (tmp_path / "tsconfig.json").exists()

    def test_scaffold_tsconfig_sets_strict_to_false(self, tmp_path: Path) -> None:
        _scaffold_tsconfig(tmp_path)
        data = json.loads((tmp_path / "tsconfig.json").read_text())
        assert data["compilerOptions"]["strict"] is False

    def test_tsconfig_is_valid_json(self, tmp_path: Path) -> None:
        _scaffold_tsconfig(tmp_path)
        # Should not raise
        json.loads((tmp_path / "tsconfig.json").read_text())

    def test_tsconfig_has_expected_defaults(self, tmp_path: Path) -> None:
        _scaffold_tsconfig(tmp_path)
        data = json.loads((tmp_path / "tsconfig.json").read_text())
        opts = data["compilerOptions"]
        assert opts["target"] == "ES2020"
        assert opts["module"] == "ESNext"
        assert opts["noEmit"] is True
        assert opts["esModuleInterop"] is True


# ---------------------------------------------------------------------------
# _ensure_js_dev_deps tests
# ---------------------------------------------------------------------------


class TestEnsureJsDevDeps:
    """Tests for _ensure_js_dev_deps."""

    def test_adds_eslint_to_devdeps(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path, {"name": "test"})
        result = _ensure_js_dev_deps(tmp_path)
        assert result == ["package.json"]
        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "eslint" in pkg["devDependencies"]

    def test_preserves_existing_devdeps(self, tmp_path: Path) -> None:
        _make_package_json(
            tmp_path,
            {"name": "test", "devDependencies": {"prettier": "^3.0.0"}},
        )
        _ensure_js_dev_deps(tmp_path)
        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "prettier" in pkg["devDependencies"]
        assert "eslint" in pkg["devDependencies"]

    def test_skips_if_eslint_present(self, tmp_path: Path) -> None:
        _make_package_json(
            tmp_path,
            {"name": "test", "devDependencies": {"eslint": "^8.0.0"}},
        )
        result = _ensure_js_dev_deps(tmp_path)
        assert result == []

    def test_skips_if_no_package_json(self, tmp_path: Path) -> None:
        result = _ensure_js_dev_deps(tmp_path)
        assert result == []

    def test_adds_typescript_when_ts_files_present(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path, {"name": "test"})
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.ts").write_text("const x = 1;")
        _ensure_js_dev_deps(tmp_path)
        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "typescript" in pkg["devDependencies"]


# ---------------------------------------------------------------------------
# scaffold_lint_config (top-level orchestrator) tests
# ---------------------------------------------------------------------------


class TestScaffoldLintConfig:
    """Tests for the top-level scaffold_lint_config orchestrator."""

    def test_scaffolds_python_repo(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        result = scaffold_lint_config(tmp_path)
        assert "ruff" in result.scaffolded
        assert "pyright" in result.scaffolded
        assert result.language == "python"
        assert len(result.modified_files) > 0 or len(result.created_files) > 0

    def test_scaffolds_js_repo(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path)
        result = scaffold_lint_config(tmp_path)
        assert "eslint" in result.scaffolded
        assert result.language == "javascript"
        assert "eslint.config.js" in result.created_files

    def test_scaffolds_ts_repo_with_tsconfig(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.ts").write_text("const x = 1;")
        result = scaffold_lint_config(tmp_path)
        assert "eslint" in result.scaffolded
        assert "tsconfig" in result.scaffolded
        assert "tsconfig.json" in result.created_files

    def test_scaffolds_mixed_repo(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        _make_package_json(tmp_path)
        result = scaffold_lint_config(tmp_path)
        assert "ruff" in result.scaffolded
        assert "pyright" in result.scaffolded
        assert "eslint" in result.scaffolded
        assert result.language == "mixed"

    def test_skips_existing_ruff_config(self, tmp_path: Path) -> None:
        _make_pyproject(
            tmp_path, "[project]\nname = 'test'\n\n[tool.ruff]\nline-length = 80\n"
        )
        result = scaffold_lint_config(tmp_path)
        assert "ruff" in result.skipped
        assert "ruff" not in result.scaffolded

    def test_skips_existing_eslint_config(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path)
        (tmp_path / ".eslintrc.json").write_text("{}")
        result = scaffold_lint_config(tmp_path)
        assert "eslint" in result.skipped
        assert "eslint" not in result.scaffolded

    def test_skips_tsconfig_when_no_ts_files(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path)
        result = scaffold_lint_config(tmp_path)
        assert "tsconfig" not in result.scaffolded
        assert "tsconfig" not in result.skipped

    def test_skips_unknown_language(self, tmp_path: Path) -> None:
        result = scaffold_lint_config(tmp_path)
        assert result.scaffolded == []
        assert result.skipped == []
        assert result.language == "unknown"

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        original_content = (tmp_path / "pyproject.toml").read_text()
        result = scaffold_lint_config(tmp_path, dry_run=True)
        assert "ruff" in result.scaffolded
        assert "pyright" in result.scaffolded
        # File unchanged
        assert (tmp_path / "pyproject.toml").read_text() == original_content
        assert result.modified_files == []
        assert result.created_files == []

    def test_scaffold_lint_is_idempotent_when_run_twice(self, tmp_path: Path) -> None:
        _make_pyproject(tmp_path, "[project]\nname = 'test'\n")
        first = scaffold_lint_config(tmp_path)
        assert len(first.scaffolded) > 0

        second = scaffold_lint_config(tmp_path)
        assert second.scaffolded == []
        assert "ruff" in second.skipped
        assert "pyright" in second.skipped

    def test_never_overwrites_existing_config(self, tmp_path: Path) -> None:
        original_ruff = "[project]\nname = 'test'\n\n[tool.ruff]\nline-length = 80\n"
        _make_pyproject(tmp_path, original_ruff)
        scaffold_lint_config(tmp_path)
        content = (tmp_path / "pyproject.toml").read_text()
        # Original ruff config preserved (line-length = 80, not 120)
        assert "line-length = 80" in content

    def test_skips_existing_pyright_config(self, tmp_path: Path) -> None:
        _make_pyproject(
            tmp_path,
            '[project]\nname = "test"\n\n[tool.pyright]\npythonVersion = "3.10"\n',
        )
        result = scaffold_lint_config(tmp_path)
        assert "pyright" in result.skipped

    def test_skips_existing_tsconfig(self, tmp_path: Path) -> None:
        _make_package_json(tmp_path)
        (tmp_path / "tsconfig.json").write_text("{}")
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.ts").write_text("const x = 1;")
        result = scaffold_lint_config(tmp_path)
        assert "tsconfig" in result.skipped
        assert "tsconfig" not in result.scaffolded

    def test_created_file_not_duplicated_in_modified(self, tmp_path: Path) -> None:
        """pyproject.toml created by ruff scaffold must not also appear in modified_files."""
        # No pyproject.toml exists; both ruff and pyright will scaffold it
        (tmp_path / "requirements.txt").touch()
        result = scaffold_lint_config(tmp_path)
        assert "ruff" in result.scaffolded
        assert "pyright" in result.scaffolded
        # File should appear in exactly one list
        overlap = set(result.created_files) & set(result.modified_files)
        assert overlap == set(), f"Files in both lists: {overlap}"
