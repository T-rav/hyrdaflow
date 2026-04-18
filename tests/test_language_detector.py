"""Tests for target-repo language detection via marker files."""

from __future__ import annotations

from pathlib import Path

import pytest

from language_detector import detect_languages


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


class TestDetectLanguages:
    """Tests for detect_languages() — marker-based language detection."""

    def test_python_from_pyproject_toml(self, repo: Path) -> None:
        """pyproject.toml presence should detect python."""
        (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        assert detect_languages(repo) == {"python"}

    def test_python_from_setup_py(self, repo: Path) -> None:
        """setup.py presence should detect python."""
        (repo / "setup.py").write_text("from setuptools import setup\n")
        assert detect_languages(repo) == {"python"}

    def test_python_from_requirements_txt(self, repo: Path) -> None:
        """requirements.txt presence should detect python."""
        (repo / "requirements.txt").write_text("requests==2.0\n")
        assert detect_languages(repo) == {"python"}

    def test_typescript_from_tsconfig(self, repo: Path) -> None:
        """tsconfig.json presence should detect typescript."""
        (repo / "tsconfig.json").write_text("{}\n")
        assert detect_languages(repo) == {"typescript"}

    def test_typescript_from_package_json_with_ts_dep(self, repo: Path) -> None:
        """package.json with typescript in devDependencies should detect typescript."""
        (repo / "package.json").write_text(
            '{"devDependencies": {"typescript": "^5.0.0"}}\n'
        )
        assert detect_languages(repo) == {"typescript"}

    def test_typescript_from_package_json_dependencies(self, repo: Path) -> None:
        """Return typescript when package.json declares typescript under dependencies."""
        (repo / "package.json").write_text(
            '{"dependencies": {"typescript": "^5.0.0"}}\n'
        )
        assert detect_languages(repo) == {"typescript"}

    def test_package_json_without_typescript_dep_is_not_typescript(
        self, repo: Path
    ) -> None:
        """package.json without typescript dependency should not detect typescript."""
        (repo / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}\n')
        assert detect_languages(repo) == set()

    def test_csharp_from_csproj(self, repo: Path) -> None:
        """A .csproj file should detect csharp."""
        (repo / "MyApp.csproj").write_text("<Project></Project>\n")
        assert detect_languages(repo) == {"csharp"}

    def test_csharp_from_sln(self, repo: Path) -> None:
        """A .sln file should detect csharp."""
        (repo / "MyApp.sln").write_text("Microsoft Visual Studio Solution\n")
        assert detect_languages(repo) == {"csharp"}

    def test_go_from_go_mod(self, repo: Path) -> None:
        """go.mod presence should detect go."""
        (repo / "go.mod").write_text("module example.com/foo\n")
        assert detect_languages(repo) == {"go"}

    def test_rust_from_cargo_toml(self, repo: Path) -> None:
        """Cargo.toml presence should detect rust."""
        (repo / "Cargo.toml").write_text("[package]\nname = 'x'\n")
        assert detect_languages(repo) == {"rust"}

    def test_multi_language_returns_all(self, repo: Path) -> None:
        """Multiple marker files should return all detected languages."""
        (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        (repo / "tsconfig.json").write_text("{}\n")
        assert detect_languages(repo) == {"python", "typescript"}

    def test_empty_repo_returns_empty_set(self, repo: Path) -> None:
        """A directory with no marker files should return an empty set."""
        assert detect_languages(repo) == set()

    def test_nonexistent_path_returns_empty_set(self, repo: Path) -> None:
        """A nonexistent path should return an empty set, not raise."""
        assert detect_languages(repo / "does-not-exist") == set()

    def test_malformed_package_json_is_not_typescript(self, repo: Path) -> None:
        """Malformed package.json should be treated as no typescript dependency."""
        (repo / "package.json").write_text("{not valid json")
        assert detect_languages(repo) == set()
