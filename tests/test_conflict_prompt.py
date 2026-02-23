"""Tests for the shared conflict prompt builder."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conflict_prompt import build_conflict_prompt
from tests.helpers import ConfigFactory

ISSUE_URL = "https://github.com/test-org/test-repo/issues/42"
PR_URL = "https://github.com/test-org/test-repo/pull/101"


class TestBuildConflictPrompt:
    def test_includes_issue_and_pr_urls(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert ISSUE_URL in prompt
        assert PR_URL in prompt

    def test_includes_merge_conflict_header(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "merge conflicts" in prompt.lower()

    def test_includes_make_quality_instruction(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "make quality" in prompt

    def test_includes_do_not_push(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "Do not push" in prompt

    def test_no_previous_error_on_first_attempt(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "Previous Attempt Failed" not in prompt

    def test_no_error_section_when_error_is_none(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 2)
        assert "Previous Attempt Failed" not in prompt

    def test_includes_previous_error_on_retry(self) -> None:
        prompt = build_conflict_prompt(
            ISSUE_URL, PR_URL, "make quality failed: ruff error", 2
        )
        assert "## Previous Attempt Failed" in prompt
        assert "ruff error" in prompt
        assert "Attempt 1" in prompt

    def test_truncates_long_error(self) -> None:
        long_error = "x" * 5000
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, long_error, 3)
        assert "## Previous Attempt Failed" in prompt
        error_section = prompt.split("## Previous Attempt Failed")[1].split("##")[0]
        # The x's in the error section should be <= 3000
        assert error_section.count("x") <= 3000

    def test_includes_memory_suggestion_instructions(self) -> None:
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "MEMORY_SUGGESTION_START" in prompt
        assert "MEMORY_SUGGESTION_END" in prompt
        assert "## Optional: Memory Suggestion" in prompt

    def test_includes_project_context_when_config_provided(
        self, tmp_path: Path
    ) -> None:
        """When config is provided and manifest exists, prompt includes project context."""
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        config.repo_root.mkdir(parents=True, exist_ok=True)
        manifest_path = config.repo_root / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("## Project Manifest\npython, make, pytest")

        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1, config=config)
        assert "## Project Context" in prompt
        assert "python, make, pytest" in prompt

    def test_includes_accumulated_learnings_when_config_provided(
        self, tmp_path: Path
    ) -> None:
        """When config is provided and digest exists, prompt includes learnings."""
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        config.repo_root.mkdir(parents=True, exist_ok=True)
        digest_path = config.repo_root / ".hydraflow" / "memory" / "digest.md"
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text("## Memory Digest\nAlways check edge cases")

        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1, config=config)
        assert "## Accumulated Learnings" in prompt
        assert "Always check edge cases" in prompt

    def test_omits_project_context_when_no_config(self) -> None:
        """Without config parameter, no project context section."""
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1)
        assert "## Project Context" not in prompt

    def test_omits_project_context_when_config_but_no_manifest(
        self, tmp_path: Path
    ) -> None:
        """With config but no manifest file, no project context section."""
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        config.repo_root.mkdir(parents=True, exist_ok=True)

        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, None, 1, config=config)
        assert "## Project Context" not in prompt

    def test_truncates_long_error_using_config_max_chars(self, tmp_path: Path) -> None:
        """When config is provided, config.error_output_max_chars is used for truncation."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo", error_output_max_chars=500
        )
        long_error = "Z" * 2000
        prompt = build_conflict_prompt(ISSUE_URL, PR_URL, long_error, 2, config=config)
        assert "## Previous Attempt Failed" in prompt
        error_section = prompt.split("## Previous Attempt Failed")[1].split("##")[0]
        assert error_section.count("Z") <= 500
