"""Tests for prep_hooks.py — pre-commit hook scaffolding."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from prep_hooks import (
    configure_hooks_path,
    detect_language,
    scaffold_pre_commit_hook,
    setup_hooks,
)

# ---------------------------------------------------------------------------
# TestDetectLanguage
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """Tests for detect_language()."""

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


# ---------------------------------------------------------------------------
# TestScaffoldPreCommitHook
# ---------------------------------------------------------------------------


class TestScaffoldPreCommitHook:
    """Tests for scaffold_pre_commit_hook()."""

    def test_creates_python_hook(self, tmp_path: Path) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        hook = tmp_path / ".githooks" / "pre-commit"
        assert result.created is True
        content = hook.read_text()
        assert "ruff check ." in content
        assert "ruff format . --check" in content

    def test_creates_javascript_hook(self, tmp_path: Path) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="javascript")
        hook = tmp_path / ".githooks" / "pre-commit"
        assert result.created is True
        content = hook.read_text()
        assert "npx eslint ." in content

    def test_creates_typescript_hook(self, tmp_path: Path) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="typescript")
        hook = tmp_path / ".githooks" / "pre-commit"
        assert result.created is True
        content = hook.read_text()
        assert "npx eslint ." in content

    def test_creates_unknown_hook_with_placeholder(self, tmp_path: Path) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="unknown")
        hook = tmp_path / ".githooks" / "pre-commit"
        assert result.created is True
        content = hook.read_text()
        assert "Add your lint command here" in content
        assert "exit 0" in content

    def test_hook_is_executable(self, tmp_path: Path) -> None:
        scaffold_pre_commit_hook(tmp_path, language="python")
        hook = tmp_path / ".githooks" / "pre-commit"
        assert os.access(hook, os.X_OK)

    def test_hook_starts_with_shebang(self, tmp_path: Path) -> None:
        scaffold_pre_commit_hook(tmp_path, language="python")
        hook = tmp_path / ".githooks" / "pre-commit"
        assert hook.read_text().startswith("#!/bin/sh\n")

    def test_creates_githooks_directory(self, tmp_path: Path) -> None:
        assert not (tmp_path / ".githooks").exists()
        scaffold_pre_commit_hook(tmp_path, language="python")
        assert (tmp_path / ".githooks").is_dir()

    def test_skips_when_hook_exists(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / ".githooks"
        hooks_dir.mkdir()
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\necho existing\n")
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        assert result.skipped is True
        assert result.created is False
        # Original content preserved
        assert "existing" in (hooks_dir / "pre-commit").read_text()

    def test_warns_when_husky_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".husky").mkdir()
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        assert result.warned is True
        assert result.created is True
        assert ".husky" in result.message

    def test_auto_detects_language(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        result = scaffold_pre_commit_hook(tmp_path)
        assert result.language == "python"
        hook = tmp_path / ".githooks" / "pre-commit"
        assert "ruff check ." in hook.read_text()

    def test_explicit_language_overrides_detection(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        result = scaffold_pre_commit_hook(tmp_path, language="javascript")
        assert result.language == "javascript"
        hook = tmp_path / ".githooks" / "pre-commit"
        assert "npx eslint ." in hook.read_text()

    def test_result_contains_hook_path(self, tmp_path: Path) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        assert result.hook_path == tmp_path / ".githooks" / "pre-commit"

    def test_skipped_result_contains_hook_path(self, tmp_path: Path) -> None:
        hooks_dir = tmp_path / ".githooks"
        hooks_dir.mkdir()
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\n")
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        assert result.hook_path == tmp_path / ".githooks" / "pre-commit"

    def test_message_on_successful_creation_includes_path(self, tmp_path: Path) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        assert "python" in result.message
        assert str(tmp_path / ".githooks" / "pre-commit") in result.message

    def test_warned_message_includes_hook_path(self, tmp_path: Path) -> None:
        (tmp_path / ".husky").mkdir()
        result = scaffold_pre_commit_hook(tmp_path, language="python")
        assert ".husky" in result.message
        assert str(tmp_path / ".githooks" / "pre-commit") in result.message

    def test_empty_string_language_falls_back_to_unknown_hook(
        self, tmp_path: Path
    ) -> None:
        result = scaffold_pre_commit_hook(tmp_path, language="")
        assert result.created is True
        assert result.language == ""
        hook = tmp_path / ".githooks" / "pre-commit"
        assert "Add your lint command here" in hook.read_text()


# ---------------------------------------------------------------------------
# TestConfigureHooksPath
# ---------------------------------------------------------------------------


class TestConfigureHooksPath:
    """Tests for configure_hooks_path()."""

    @pytest.mark.asyncio
    async def test_runs_git_config(self) -> None:
        with patch("prep_hooks.run_subprocess", new_callable=AsyncMock) as mock_sub:
            await configure_hooks_path(Path("/fake/repo"))
            mock_sub.assert_called_once_with(
                "git", "config", "core.hooksPath", ".githooks", cwd=Path("/fake/repo")
            )

    @pytest.mark.asyncio
    async def test_handles_failure_gracefully(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(
                "prep_hooks.run_subprocess",
                new_callable=AsyncMock,
                side_effect=RuntimeError("git not found"),
            ),
            caplog.at_level(logging.WARNING, logger="hydraflow.prep_hooks"),
        ):
            await configure_hooks_path(Path("/fake/repo"))
        assert "Failed to configure git hooks path" in caplog.text


# ---------------------------------------------------------------------------
# TestSetupHooks
# ---------------------------------------------------------------------------


class TestSetupHooks:
    """Tests for setup_hooks() combined entry point."""

    @pytest.mark.asyncio
    async def test_creates_hook_and_configures_path(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        with patch("prep_hooks.run_subprocess", new_callable=AsyncMock) as mock_sub:
            result = await setup_hooks(tmp_path)
            assert result.created is True
            assert result.language == "python"
            mock_sub.assert_called_once_with(
                "git", "config", "core.hooksPath", ".githooks", cwd=tmp_path
            )

    @pytest.mark.asyncio
    async def test_skips_creation_but_still_configures_path(
        self, tmp_path: Path
    ) -> None:
        hooks_dir = tmp_path / ".githooks"
        hooks_dir.mkdir()
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\necho existing\n")
        with patch("prep_hooks.run_subprocess", new_callable=AsyncMock) as mock_sub:
            result = await setup_hooks(tmp_path)
            assert result.skipped is True
            # git config should still be called even when hook already exists
            mock_sub.assert_called_once_with(
                "git", "config", "core.hooksPath", ".githooks", cwd=tmp_path
            )

    @pytest.mark.asyncio
    async def test_explicit_language_passed_through_to_scaffold(
        self, tmp_path: Path
    ) -> None:
        with patch("prep_hooks.run_subprocess", new_callable=AsyncMock):
            result = await setup_hooks(tmp_path, language="javascript")
            assert result.language == "javascript"
            hook = tmp_path / ".githooks" / "pre-commit"
            assert "npx eslint ." in hook.read_text()
