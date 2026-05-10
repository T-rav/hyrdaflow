"""Regression test for issue #8499.

Fake coverage gap: FakeGit exposes a public method ``worktree_prune`` but
no matching cassette existed under ``tests/trust/contracts/cassettes/git/``.
Without the cassette the trust-contract test suite silently skipped this
method, allowing the fake to drift from the real adapter undetected.

This test verifies the cassette is recorded and structurally valid.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))

from contracts._schema import load_cassette
from fake_coverage_auditor_loop import catalog_cassette_methods

_CASSETTE_DIR = (
    Path(__file__).resolve().parent.parent / "trust" / "contracts" / "cassettes" / "git"
)


def test_fake_git_worktree_prune_has_cassette() -> None:
    """worktree_prune must appear in the git cassette catalog."""
    methods = catalog_cassette_methods(_CASSETTE_DIR)
    assert "worktree_prune" in methods, (
        f"No cassette for FakeGit.worktree_prune found in {_CASSETTE_DIR}. "
        "Add tests/trust/contracts/cassettes/git/worktree_prune.yaml."
    )


def test_worktree_prune_cassette_parses_without_error() -> None:
    """The worktree_prune cassette must validate against the Cassette schema."""
    cassette_path = _CASSETTE_DIR / "worktree_prune.yaml"
    assert cassette_path.exists(), f"Cassette file missing: {cassette_path}"
    cassette = load_cassette(cassette_path)
    assert cassette.adapter == "git"
    assert cassette.interaction == "worktree_prune"
    assert cassette.input.command == "worktree_prune"
    assert cassette.output.exit_code == 0
