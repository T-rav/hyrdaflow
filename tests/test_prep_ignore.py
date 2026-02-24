"""Tests for prep_ignore.py — shared ignore policy and submodule discovery."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from prep_ignore import PREP_IGNORED_DIRS, load_git_submodule_roots


class TestPrepIgnoredDirs:
    """Tests for the PREP_IGNORED_DIRS constant."""

    def test_is_frozenset(self) -> None:
        """PREP_IGNORED_DIRS should be immutable (frozenset)."""
        assert isinstance(PREP_IGNORED_DIRS, frozenset)

    def test_contains_critical_entries(self) -> None:
        """PREP_IGNORED_DIRS should contain key directories that must always be ignored."""
        expected = {".git", "node_modules", "__pycache__", ".venv", ".hydraflow"}
        assert expected.issubset(PREP_IGNORED_DIRS)


class TestLoadGitSubmoduleRoots:
    """Tests for load_git_submodule_roots."""

    def test_returns_empty_when_gitmodules_absent(self, tmp_path: Path) -> None:
        """Should return empty tuple when .gitmodules does not exist."""
        result = load_git_submodule_roots(tmp_path)

        assert result == ()

    def test_returns_paths_for_valid_gitmodules(self, tmp_path: Path) -> None:
        """Should return resolved absolute paths for each submodule path entry."""
        gitmodules = tmp_path / ".gitmodules"
        gitmodules.write_text(
            '[submodule "vendor/lib"]\n'
            "\tpath = vendor/lib\n"
            "\turl = https://github.com/example/lib.git\n"
        )

        result = load_git_submodule_roots(tmp_path)

        assert len(result) == 1
        assert result[0] == (tmp_path / "vendor/lib").resolve()

    def test_returns_empty_for_no_path_lines(self, tmp_path: Path) -> None:
        """Should return empty tuple when .gitmodules has no path = lines."""
        gitmodules = tmp_path / ".gitmodules"
        gitmodules.write_text(
            '[submodule "vendor/lib"]\n\turl = https://github.com/example/lib.git\n'
        )

        result = load_git_submodule_roots(tmp_path)

        assert result == ()

    def test_returns_empty_on_oserror(self, tmp_path: Path) -> None:
        """Should return empty tuple when reading .gitmodules raises OSError."""
        gitmodules = tmp_path / ".gitmodules"
        gitmodules.write_text("path = vendor/lib\n")

        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = load_git_submodule_roots(tmp_path)

        assert result == ()

    def test_handles_multiple_submodules(self, tmp_path: Path) -> None:
        """Should return paths for all submodules in .gitmodules."""
        gitmodules = tmp_path / ".gitmodules"
        gitmodules.write_text(
            '[submodule "vendor/lib-a"]\n'
            "\tpath = vendor/lib-a\n"
            "\turl = https://github.com/example/lib-a.git\n"
            '[submodule "vendor/lib-b"]\n'
            "\tpath = vendor/lib-b\n"
            "\turl = https://github.com/example/lib-b.git\n"
        )

        result = load_git_submodule_roots(tmp_path)

        assert len(result) == 2
        resolved = set(result)
        assert (tmp_path / "vendor/lib-a").resolve() in resolved
        assert (tmp_path / "vendor/lib-b").resolve() in resolved

    def test_strips_whitespace_from_paths(self, tmp_path: Path) -> None:
        """Should strip leading/trailing whitespace from path values."""
        gitmodules = tmp_path / ".gitmodules"
        gitmodules.write_text('[submodule "lib"]\n\tpath =   lib/core  \n')

        result = load_git_submodule_roots(tmp_path)

        assert len(result) == 1
        assert result[0] == (tmp_path / "lib/core").resolve()
