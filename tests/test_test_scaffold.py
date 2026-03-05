"""Tests for test_scaffold.py — test infrastructure scaffolding module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_scaffold import (
    TestScaffoldResult,
    _has_pytest_config,
    _scaffold_js_tests,
    _scaffold_python_tests,
    has_test_infrastructure,
    scaffold_tests,
)

# ---------------------------------------------------------------------------
# TestScaffoldResult
# ---------------------------------------------------------------------------


class TestTestScaffoldResult:
    """Tests for the TestScaffoldResult dataclass."""

    def test_scaffold_result_defaults_to_empty_fields(self) -> None:
        result = TestScaffoldResult()

        assert result.created_dirs == []
        assert result.created_files == []
        assert result.modified_files == []
        assert result.skipped is False
        assert result.skip_reason == ""
        assert result.language == ""
        assert result.progress == ""

    def test_scaffold_result_stores_explicit_field_values(self) -> None:
        result = TestScaffoldResult(
            created_dirs=["tests/"],
            created_files=["tests/__init__.py"],
            modified_files=["pyproject.toml"],
            skipped=False,
            skip_reason="",
            language="python",
        )

        assert result.created_dirs == ["tests/"]
        assert result.created_files == ["tests/__init__.py"]
        assert result.modified_files == ["pyproject.toml"]
        assert result.language == "python"
        assert result.progress == ""

    def test_mutable_default_independence(self) -> None:
        """Each instance should get its own list."""
        a = TestScaffoldResult()
        b = TestScaffoldResult()
        a.created_dirs.append("foo/")

        assert b.created_dirs == []


# ---------------------------------------------------------------------------
# _has_pytest_config
# ---------------------------------------------------------------------------


class TestHasPytestConfig:
    """Tests for the private _has_pytest_config helper."""

    def test_logs_warning_when_pyproject_unreadable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.pytest.ini_options]")
        original_read_text = Path.read_text

        def fake_read_text(self: Path, *args, **kwargs):
            if self == pyproject:
                raise OSError("boom")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        with caplog.at_level("WARNING"):
            result = _has_pytest_config(tmp_path)

        assert result is False
        assert str(pyproject) in caplog.text


# ---------------------------------------------------------------------------
# has_test_infrastructure
# ---------------------------------------------------------------------------


class TestHasTestInfrastructure:
    """Tests for has_test_infrastructure()."""

    # --- Python ---

    def test_python_has_tests_dir_and_pytest_config(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("def test_x(): pass\n")
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )

        has_infra, details = has_test_infrastructure(tmp_path, "python")

        assert has_infra is True
        assert len(details) > 0

    def test_python_empty_tests_dir(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        has_infra, _details = has_test_infrastructure(tmp_path, "python")

        assert has_infra is False

    def test_python_tests_dir_without_config(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("def test_x(): pass\n")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        has_infra, _details = has_test_infrastructure(tmp_path, "python")

        assert has_infra is False

    def test_python_no_tests_dir(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        has_infra, _details = has_test_infrastructure(tmp_path, "python")

        assert has_infra is False

    def test_python_tests_dir_with_only_init(self, tmp_path: Path) -> None:
        """tests/ with only __init__.py is not real test infrastructure."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("")
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )

        has_infra, _details = has_test_infrastructure(tmp_path, "python")

        assert has_infra is False

    # --- JavaScript ---

    def test_js_has_tests_dir_and_vitest_config(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        (tests_dir / "foo.test.js").write_text("test('x', () => {})\n")
        (tmp_path / "vitest.config.js").write_text("export default {}\n")

        has_infra, details = has_test_infrastructure(tmp_path, "javascript")

        assert has_infra is True
        assert len(details) > 0

    def test_js_has_jest_config(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        (tests_dir / "foo.test.js").write_text("test('x', () => {})\n")
        (tmp_path / "jest.config.js").write_text("module.exports = {}\n")

        has_infra, details = has_test_infrastructure(tmp_path, "javascript")

        assert has_infra is True
        assert len(details) > 0

    def test_js_no_test_infra(self, tmp_path: Path) -> None:
        has_infra, _details = has_test_infrastructure(tmp_path, "javascript")

        assert has_infra is False

    def test_js_config_without_test_dir(self, tmp_path: Path) -> None:
        (tmp_path / "vitest.config.js").write_text("export default {}\n")

        has_infra, _details = has_test_infrastructure(tmp_path, "javascript")

        assert has_infra is False

    # --- Mixed ---

    def test_mixed_returns_false_when_only_python_infra_present(
        self, tmp_path: Path
    ) -> None:
        """Mixed repo with only Python infra should NOT be considered complete."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("def test_x(): pass\n")
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )

        has_infra, _details = has_test_infrastructure(tmp_path, "mixed")

        assert has_infra is False

    def test_mixed_returns_false_when_only_js_infra_present(
        self, tmp_path: Path
    ) -> None:
        """Mixed repo with only JS infra should NOT be considered complete."""
        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        (tests_dir / "foo.test.js").write_text("test('x', () => {})\n")
        (tmp_path / "vitest.config.js").write_text("export default {}\n")

        has_infra, _details = has_test_infrastructure(tmp_path, "mixed")

        assert has_infra is False

    def test_mixed_returns_true_when_both_infra_present(self, tmp_path: Path) -> None:
        """Mixed repo requires both Python and JS infra to return True."""
        py_dir = tmp_path / "tests"
        py_dir.mkdir()
        (py_dir / "test_foo.py").write_text("def test_x(): pass\n")
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )
        js_dir = tmp_path / "__tests__"
        js_dir.mkdir()
        (js_dir / "foo.test.js").write_text("test('x', () => {})\n")
        (tmp_path / "vitest.config.js").write_text("export default {}\n")

        has_infra, details = has_test_infrastructure(tmp_path, "mixed")

        assert has_infra is True
        assert len(details) > 0


# ---------------------------------------------------------------------------
# _scaffold_python_tests
# ---------------------------------------------------------------------------


class TestScaffoldPythonTests:
    """Tests for _scaffold_python_tests()."""

    def test_creates_tests_directory(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = _scaffold_python_tests(tmp_path)

        assert (tmp_path / "tests").is_dir()
        assert "tests" in result.created_dirs

    def test_creates_init_py(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = _scaffold_python_tests(tmp_path)

        assert (tmp_path / "tests" / "__init__.py").is_file()
        assert "tests/__init__.py" in result.created_files

    def test_creates_conftest(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = _scaffold_python_tests(tmp_path)

        conftest = tmp_path / "tests" / "conftest.py"
        assert conftest.is_file()
        assert "tests/conftest.py" in result.created_files
        content = conftest.read_text()
        assert "fixtures" in content.lower() or "conftest" in content.lower()

    def test_creates_python_smoke_test_suite(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        result = _scaffold_python_tests(tmp_path)
        smoke_files = sorted((tmp_path / "tests").glob("test_prep_smoke*.py"))
        assert len(smoke_files) == 8
        assert "tests/test_prep_smoke.py" in result.created_files
        assert "tests/test_prep_smoke_8.py" in result.created_files

    def test_adds_pytest_config_to_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = _scaffold_python_tests(tmp_path)

        content = (tmp_path / "pyproject.toml").read_text()
        assert "[tool.pytest.ini_options]" in content
        assert "pyproject.toml" in result.modified_files

    def test_preserves_existing_pyproject_content(self, tmp_path: Path) -> None:
        original = '[project]\nname = "myapp"\nversion = "1.0.0"\n'
        (tmp_path / "pyproject.toml").write_text(original)

        _scaffold_python_tests(tmp_path)

        content = (tmp_path / "pyproject.toml").read_text()
        assert 'name = "myapp"' in content
        assert "[tool.pytest.ini_options]" in content

    def test_skips_pytest_config_if_present(self, tmp_path: Path) -> None:
        toml_content = (
            "[project]\nname = 'foo'\n\n"
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )
        (tmp_path / "pyproject.toml").write_text(toml_content)

        result = _scaffold_python_tests(tmp_path)

        assert "pyproject.toml" not in result.modified_files

    def test_creates_pyproject_if_missing(self, tmp_path: Path) -> None:
        # No pyproject.toml at all — scaffold should create one
        (tmp_path / "requirements.txt").write_text("flask\n")

        result = _scaffold_python_tests(tmp_path)

        pyproject = tmp_path / "pyproject.toml"
        assert pyproject.is_file()
        content = pyproject.read_text()
        assert "[tool.pytest.ini_options]" in content
        assert "pyproject.toml" in result.created_files

    def test_does_not_overwrite_existing_conftest(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text("# My custom conftest\n")

        _scaffold_python_tests(tmp_path)

        content = (tests_dir / "conftest.py").read_text()
        assert content == "# My custom conftest\n"

    def test_does_not_overwrite_existing_init_py(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "__init__.py").write_text("# Existing init\n")

        result = _scaffold_python_tests(tmp_path)

        content = (tests_dir / "__init__.py").read_text()
        assert content == "# Existing init\n"
        assert "tests/__init__.py" not in result.created_files

    def test_result_language_is_python(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = _scaffold_python_tests(tmp_path)

        assert result.language == "python"

    def test_creates_python_placeholder_tests_for_source_files(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "alpha.py").write_text("VALUE = 1\n")
        (src_dir / "beta.py").write_text("VALUE = 2\n")

        result = _scaffold_python_tests(tmp_path)

        assert (tmp_path / "tests" / "test_prep_src_alpha_py.py").is_file()
        assert (tmp_path / "tests" / "test_prep_src_beta_py.py").is_file()
        assert "tests/test_prep_src_alpha_py.py" in result.created_files
        assert "tests/test_prep_src_beta_py.py" in result.created_files

    def test_batches_python_placeholders_and_progresses_next_run(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for idx in range(8):
            (src_dir / f"file_{idx}.py").write_text(f"VALUE_{idx} = {idx}\n")

        first = _scaffold_python_tests(tmp_path)
        second = _scaffold_python_tests(tmp_path)

        first_placeholders = [
            f for f in first.created_files if f.startswith("tests/test_prep_src_file_")
        ]
        second_placeholders = [
            f for f in second.created_files if f.startswith("tests/test_prep_src_file_")
        ]
        assert len(first_placeholders) == 6
        assert len(second_placeholders) == 2
        assert "batch limit 6" in first.progress
        assert "pending before batch 8" in first.progress
        assert "pending before batch 2" in second.progress


# ---------------------------------------------------------------------------
# _scaffold_js_tests
# ---------------------------------------------------------------------------


class TestScaffoldJsTests:
    """Tests for _scaffold_js_tests()."""

    def test_creates_tests_directory(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = _scaffold_js_tests(tmp_path)

        assert (tmp_path / "__tests__").is_dir()
        assert "__tests__" in result.created_dirs

    def test_creates_vitest_config(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = _scaffold_js_tests(tmp_path)

        config_file = tmp_path / "vitest.config.js"
        assert config_file.is_file()
        assert "vitest.config.js" in result.created_files
        content = config_file.read_text()
        assert "defineConfig" in content
        assert "exclude" in content
        assert "hydraflow/**" in content

    def test_creates_js_smoke_test_suite(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        result = _scaffold_js_tests(tmp_path)
        smoke_files = sorted((tmp_path / "__tests__").glob("prep.smoke*.test.js"))
        assert len(smoke_files) == 8
        assert "__tests__/prep.smoke.test.js" in result.created_files
        assert "__tests__/prep.smoke.8.test.js" in result.created_files

    def test_adds_vitest_to_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = _scaffold_js_tests(tmp_path)

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "vitest" in pkg.get("devDependencies", {})
        assert "package.json" in result.modified_files

    def test_adds_test_script_to_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        _scaffold_js_tests(tmp_path)

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert pkg.get("scripts", {}).get("test") == "vitest run"

    def test_preserves_existing_package_json(self, tmp_path: Path) -> None:
        pkg_data = {
            "name": "foo",
            "version": "1.0.0",
            "dependencies": {"express": "^4.0.0"},
            "scripts": {"start": "node index.js"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg_data, indent=2) + "\n")

        _scaffold_js_tests(tmp_path)

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert pkg["dependencies"]["express"] == "^4.0.0"
        assert pkg["scripts"]["start"] == "node index.js"
        assert pkg["scripts"]["test"] == "vitest run"

    def test_does_not_overwrite_existing_test_script(self, tmp_path: Path) -> None:
        pkg_data = {"name": "foo", "scripts": {"test": "jest"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg_data, indent=2) + "\n")

        _scaffold_js_tests(tmp_path)

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert pkg["scripts"]["test"] == "jest"

    def test_skips_vitest_config_if_jest_exists(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        (tmp_path / "jest.config.js").write_text("module.exports = {}\n")

        result = _scaffold_js_tests(tmp_path)

        assert not (tmp_path / "vitest.config.js").exists()
        assert "vitest.config.js" not in result.created_files

    def test_skips_vitest_config_if_vitest_exists(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        (tmp_path / "vitest.config.js").write_text("export default {}\n")

        result = _scaffold_js_tests(tmp_path)

        content = (tmp_path / "vitest.config.js").read_text()
        assert content == "export default {}\n"
        assert "vitest.config.js" not in result.created_files

    def test_skips_vitest_config_if_vitest_ts_exists(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        (tmp_path / "vitest.config.ts").write_text("export default {}\n")

        result = _scaffold_js_tests(tmp_path)

        assert not (tmp_path / "vitest.config.js").exists()
        assert "vitest.config.js" not in result.created_files

    def test_skips_deps_if_no_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "tsconfig.json").write_text("{}\n")

        result = _scaffold_js_tests(tmp_path)

        assert (tmp_path / "__tests__").is_dir()
        assert "package.json" not in result.modified_files

    def test_adds_jest_dom_to_dev_dependencies(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = _scaffold_js_tests(tmp_path)

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "@testing-library/jest-dom" in pkg.get("devDependencies", {})
        assert "package.json" in result.modified_files

    def test_skips_package_json_modification_when_malformed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text("not valid json {{{")

        result = _scaffold_js_tests(tmp_path)

        assert "package.json" not in result.modified_files
        # __tests__/ and vitest.config.js should still be created
        assert (tmp_path / "__tests__").is_dir()

    def test_result_language_is_javascript(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = _scaffold_js_tests(tmp_path)

        assert result.language == "javascript"

    def test_creates_js_placeholder_tests_for_source_files(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "alpha.ts").write_text("export const alpha = 1;\n")
        (src_dir / "beta.js").write_text("export const beta = 2;\n")

        result = _scaffold_js_tests(tmp_path)

        assert (tmp_path / "__tests__" / "prep.src_alpha_ts.test.js").is_file()
        assert (tmp_path / "__tests__" / "prep.src_beta_js.test.js").is_file()
        assert "__tests__/prep.src_alpha_ts.test.js" in result.created_files
        assert "__tests__/prep.src_beta_js.test.js" in result.created_files

    def test_batches_js_placeholders_and_progresses_next_run(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for idx in range(9):
            (src_dir / f"part_{idx}.js").write_text(f"export const n{idx} = {idx};\n")

        first = _scaffold_js_tests(tmp_path)
        second = _scaffold_js_tests(tmp_path)

        first_placeholders = [
            f for f in first.created_files if f.startswith("__tests__/prep.src_part_")
        ]
        second_placeholders = [
            f for f in second.created_files if f.startswith("__tests__/prep.src_part_")
        ]
        assert len(first_placeholders) == 6
        assert len(second_placeholders) == 3
        assert "batch limit 6" in first.progress
        assert "pending before batch 9" in first.progress
        assert "pending before batch 3" in second.progress


# ---------------------------------------------------------------------------
# scaffold_tests (top-level orchestrator)
# ---------------------------------------------------------------------------


class TestScaffoldTests:
    """Tests for scaffold_tests() orchestrator."""

    def test_scaffolds_python_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = scaffold_tests(tmp_path)

        assert result.skipped is False
        assert result.language == "python"
        assert (tmp_path / "tests").is_dir()
        assert (tmp_path / "tests" / "__init__.py").is_file()

    def test_scaffolds_js_repo(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = scaffold_tests(tmp_path)

        assert result.skipped is False
        assert result.language == "javascript"
        assert (tmp_path / "__tests__").is_dir()

    def test_scaffolds_mixed_repo(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = scaffold_tests(tmp_path)

        assert result.skipped is False
        assert result.language == "mixed"
        assert (tmp_path / "tests").is_dir()
        assert (tmp_path / "__tests__").is_dir()

    def test_skips_unknown_language(self, tmp_path: Path) -> None:
        result = scaffold_tests(tmp_path)

        assert result.skipped is True
        assert (
            "unknown" in result.skip_reason.lower()
            or "language" in result.skip_reason.lower()
        )

    def test_backfills_smoke_suite_for_existing_python_infrastructure(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'foo'\n\n"
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("def test_x(): pass\n")

        result = scaffold_tests(tmp_path)

        assert result.skipped is False
        smoke_files = sorted((tmp_path / "tests").glob("test_prep_smoke*.py"))
        assert len(smoke_files) == 8

    def test_backfills_smoke_suite_for_existing_js_infrastructure(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')
        (tmp_path / "vitest.config.js").write_text("export default {}\n")
        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        (tests_dir / "foo.test.js").write_text("test('x', () => {})\n")

        result = scaffold_tests(tmp_path)

        assert result.skipped is False
        smoke_files = sorted((tmp_path / "__tests__").glob("prep.smoke*.test.js"))
        assert len(smoke_files) == 8

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        result = scaffold_tests(tmp_path, dry_run=True)

        assert result.skipped is False
        assert len(result.created_dirs) > 0 or len(result.created_files) > 0
        assert not (tmp_path / "tests").exists()

    def test_scaffold_tests_is_idempotent_when_run_twice(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")

        first = scaffold_tests(tmp_path)
        second = scaffold_tests(tmp_path)

        assert first.skipped is False
        assert second.skipped is True

    def test_scaffold_tests_batches_existing_infra_placeholders(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'foo'\n\n"
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_existing.py").write_text("def test_existing(): pass\n")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        for idx in range(7):
            (src_dir / f"module_{idx}.py").write_text(f"VAL_{idx} = {idx}\n")

        first = scaffold_tests(tmp_path)
        second = scaffold_tests(tmp_path)

        first_placeholders = [
            f
            for f in first.created_files
            if f.startswith("tests/test_prep_src_module_")
        ]
        second_placeholders = [
            f
            for f in second.created_files
            if f.startswith("tests/test_prep_src_module_")
        ]
        assert len(first_placeholders) == 6
        assert len(second_placeholders) == 1
        assert first.skipped is False
        assert second.skipped is False

    def test_generates_smoke_test_files(self, tmp_path: Path) -> None:
        """Scaffold should create baseline smoke-test suites for both stacks."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        scaffold_tests(tmp_path)

        py_smoke_files = sorted((tmp_path / "tests").glob("test_prep_smoke*.py"))
        js_smoke_files = sorted((tmp_path / "__tests__").glob("prep.smoke*.test.js"))
        assert len(py_smoke_files) == 8
        assert len(js_smoke_files) == 8

    def test_dry_run_js_repo_does_not_write(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = scaffold_tests(tmp_path, dry_run=True)

        assert result.skipped is False
        assert result.language == "javascript"
        assert not (tmp_path / "__tests__").exists()
        assert not (tmp_path / "vitest.config.js").exists()
        assert "__tests__" in result.created_dirs
        assert "vitest.config.js" in result.created_files

    def test_dry_run_mixed_repo_does_not_write(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        (tmp_path / "package.json").write_text('{"name": "foo"}\n')

        result = scaffold_tests(tmp_path, dry_run=True)

        assert result.skipped is False
        assert result.language == "mixed"
        assert not (tmp_path / "tests").exists()
        assert not (tmp_path / "__tests__").exists()
        assert "tests" in result.created_dirs
        assert "__tests__" in result.created_dirs

    def test_dry_run_does_not_report_package_json_when_already_complete(
        self, tmp_path: Path
    ) -> None:
        """Dry-run should not report package.json as modified when it already has all deps."""
        pkg_data = {
            "name": "foo",
            "devDependencies": {
                "vitest": "^4.0.0",
                "@testing-library/jest-dom": "^6.0.0",
            },
            "scripts": {"test": "vitest run"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg_data, indent=2) + "\n")

        result = scaffold_tests(tmp_path, dry_run=True)

        assert "package.json" not in result.modified_files
