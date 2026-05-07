"""Regression test for #8494 — FakeGit script-API helpers misclassified as adapter-surface.

`reject_next_push`, `set_corrupted_config`, and `active_worktrees` are test
helpers (script API), not real-adapter methods.  They must appear in the
``test-helper`` bucket, never in ``adapter-surface``.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_fake_methods

_FAKE_DIR = Path(__file__).parents[2] / "src" / "mockworld" / "fakes"

_SCRIPT_API_HELPERS = {"reject_next_push", "set_corrupted_config", "active_worktrees"}


def test_fake_git_script_api_helpers_are_not_adapter_surface() -> None:
    cat = catalog_fake_methods(_FAKE_DIR)
    assert "FakeGit" in cat, "FakeGit not found — check fake_dir path"
    surface = set(cat["FakeGit"]["adapter-surface"])
    helpers = set(cat["FakeGit"]["test-helper"])
    for method in _SCRIPT_API_HELPERS:
        assert method not in surface, (
            f"FakeGit.{method} was classified as adapter-surface; "
            "it is a script-API test helper and must be in test-helper"
        )
        assert method in helpers, (
            f"FakeGit.{method} was not classified as test-helper; "
            "it is a script-API test helper"
        )
