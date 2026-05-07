"""Regression test for issue #8496.

Bug: FakeGit.set_corrupted_config is classified as `adapter-surface` by
fake_coverage_auditor because it lacks the `script_` prefix that marks
test-helper methods.  The auditor then files a spurious cassette-gap issue.

Fix: rename to script_set_corrupted_config so catalog_fake_methods
classifies it as `test-helper`, and update the two scenario callers.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_fake_methods
from mockworld.fakes.fake_git import FakeGit


class TestFakeGitHelperClassification:
    """FakeGit.script_set_corrupted_config must be a test-helper, not adapter-surface."""

    def test_script_set_corrupted_config_classified_as_helper(
        self, tmp_path: Path
    ) -> None:
        fake_dir = Path(__file__).parent.parent.parent / "src" / "mockworld" / "fakes"
        catalog = catalog_fake_methods(fake_dir)
        helpers = catalog.get("FakeGit", {}).get("test-helper", [])
        assert "script_set_corrupted_config" in helpers, (
            "script_set_corrupted_config must be in test-helper list so "
            "the auditor does not file a cassette-gap issue"
        )

    def test_set_corrupted_config_not_on_adapter_surface(self, tmp_path: Path) -> None:
        fake_dir = Path(__file__).parent.parent.parent / "src" / "mockworld" / "fakes"
        catalog = catalog_fake_methods(fake_dir)
        surface = catalog.get("FakeGit", {}).get("adapter-surface", [])
        assert "set_corrupted_config" not in surface, (
            "set_corrupted_config must not appear on adapter-surface after rename"
        )

    def test_script_set_corrupted_config_seeds_state(self, tmp_path: Path) -> None:
        fake = FakeGit()
        fake.script_set_corrupted_config(
            tmp_path, key="core.worktree", value="/workspace"
        )
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            fake.config_get(tmp_path, "core.worktree")
        )
        assert result == "/workspace"
