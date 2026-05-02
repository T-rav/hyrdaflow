"""Tests for prep_hooks.py — language detection."""

from __future__ import annotations

import json
from pathlib import Path

from prep_hooks import (
    detect_language,
)

# ---------------------------------------------------------------------------
# TestDetectLanguage
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_detects_python_from_pyproject_toml(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'foo'\n")
        assert detect_language(tmp_path) == "python"

    def test_detects_python_from_setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup\n")
        assert detect_language(tmp_path) == "python"

    def test_detects_python_from_requirements_txt(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("requests\n")
        assert detect_language(tmp_path) == "python"

    def test_detects_python_from_setup_cfg(self, tmp_path: Path) -> None:
        (tmp_path / "setup.cfg").write_text("[metadata]\nname = foo\n")
        assert detect_language(tmp_path) == "python"

    def test_detects_javascript_from_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"name": "my-app"}))
        assert detect_language(tmp_path) == "javascript"

    def test_detects_typescript_from_tsconfig(self, tmp_path: Path) -> None:
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_language(tmp_path) == "typescript"

    def test_detects_typescript_from_package_json_with_ts_dep(
        self, tmp_path: Path
    ) -> None:
        pkg = {"name": "my-app", "devDependencies": {"typescript": "^5.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_language(tmp_path) == "typescript"

    def test_detects_typescript_from_package_json_with_ts_main(
        self, tmp_path: Path
    ) -> None:
        pkg = {"name": "my-app", "main": "dist/index.ts"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_language(tmp_path) == "typescript"

    def test_detects_typescript_from_package_json_with_types_field(
        self, tmp_path: Path
    ) -> None:
        pkg = {"name": "my-app", "types": "dist/index.d.ts"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert detect_language(tmp_path) == "typescript"

    def test_returns_unknown_for_empty_dir(self, tmp_path: Path) -> None:
        assert detect_language(tmp_path) == "unknown"

    def test_python_takes_precedence_over_js(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "package.json").write_text(json.dumps({"name": "app"}))
        assert detect_language(tmp_path) == "python"
