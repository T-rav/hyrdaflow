"""Tests for per-issue reflections file."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from reflections import append_reflection, clear_reflections, read_reflections
from tests.helpers import ConfigFactory


class TestReflections:
    def test_read_empty(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        assert read_reflections(config, 42) == ""

    def test_append_and_read(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        append_reflection(config, 42, "implement", "Found that auth module uses JWT")
        content = read_reflections(config, 42)
        assert "implement" in content
        assert "Found that auth module uses JWT" in content

    def test_multiple_appends_accumulate(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        append_reflection(config, 42, "implement", "First attempt failed — wrong API")
        append_reflection(config, 42, "review", "Reviewer noted missing error handling")
        append_reflection(
            config, 42, "implement", "Fixed error handling, retry succeeded"
        )
        content = read_reflections(config, 42)
        # Each entry has "--- phase | timestamp ---" = 2 occurrences of "---" per entry
        assert content.count("--- implement") + content.count("--- review") == 3
        assert "First attempt" in content
        assert "Reviewer noted" in content
        assert "Fixed error" in content

    def test_entries_have_timestamps(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        append_reflection(config, 42, "plan", "Codebase uses factory pattern")
        content = read_reflections(config, 42)
        assert "UTC" in content

    def test_entries_have_phase(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        append_reflection(config, 42, "triage", "Low complexity, skip planning")
        content = read_reflections(config, 42)
        assert "triage" in content

    def test_separate_issues_separate_files(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        append_reflection(config, 42, "implement", "Issue 42 learning")
        append_reflection(config, 99, "implement", "Issue 99 learning")
        assert "Issue 42" in read_reflections(config, 42)
        assert "Issue 99" in read_reflections(config, 99)
        assert "Issue 99" not in read_reflections(config, 42)

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        append_reflection(config, 42, "implement", "Some learning")
        assert read_reflections(config, 42) != ""
        clear_reflections(config, 42)
        assert read_reflections(config, 42) == ""

    def test_clear_nonexistent_is_safe(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        clear_reflections(config, 999)  # Should not raise
