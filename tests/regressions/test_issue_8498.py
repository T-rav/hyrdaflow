"""Regression test for issue #8498.

Gap: ``FakeGit.worktree_add`` was listed as adapter-surface by
``catalog_fake_methods`` but had no cassette under
``tests/trust/contracts/cassettes/git/``, so the fake-coverage auditor
would file a gap issue every cycle.

Fix: record ``worktree_add.yaml`` so the cassette set covers the method.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_cassette_methods, catalog_fake_methods

_REPO_ROOT = Path(__file__).parent.parent.parent
_FAKE_DIR = _REPO_ROOT / "src" / "mockworld" / "fakes"
_CASSETTE_DIR = _REPO_ROOT / "tests" / "trust" / "contracts" / "cassettes" / "git"

_METHOD = "worktree_add"
_RETIRE_MSG = (
    f"FakeGit no longer has {_METHOD!r} — retire this test when the method is removed."
)


class TestWorktreeAddCassetteCoverage:
    """Issue #8498: worktree_add must appear in both fake surface and cassette set."""

    def test_worktree_add_is_in_fake_git_adapter_surface(self) -> None:
        """catalog_fake_methods must list worktree_add as an adapter-surface method."""
        catalog = catalog_fake_methods(_FAKE_DIR)
        assert "FakeGit" in catalog, _RETIRE_MSG
        surface = catalog["FakeGit"]["adapter-surface"]
        assert _METHOD in surface, _RETIRE_MSG

    def test_worktree_add_has_cassette(self) -> None:
        """catalog_cassette_methods must include worktree_add once the cassette exists.

        If this fails, record tests/trust/contracts/cassettes/git/worktree_add.yaml.
        Currently cassetted commands: {catalog_cassette_methods(_CASSETTE_DIR)!r}.
        """
        methods = catalog_cassette_methods(_CASSETTE_DIR)
        assert _METHOD in methods, (
            f"{_METHOD!r} has no cassette in {_CASSETTE_DIR}. "
            f"Currently cassetted: {sorted(methods)}"
        )
