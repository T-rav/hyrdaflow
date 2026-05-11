"""Regression test for issue #8490.

FakeGit.config_get had no matching cassette under
tests/trust/contracts/cassettes/git/, leaving the adapter-surface method
unverified by the contract replay harness.

Strategy
--------
catalog_fake_methods confirms config_get is on FakeGit's adapter surface.
catalog_cassette_methods confirms a cassette recording exists for it.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_cassette_methods, catalog_fake_methods

_FAKE_DIR = Path(__file__).parent.parent.parent / "src" / "mockworld" / "fakes"
_CASSETTE_DIR = (
    Path(__file__).parent.parent / "trust" / "contracts" / "cassettes" / "git"
)


def test_config_get_in_fake_git_surface() -> None:
    """config_get must appear on FakeGit's adapter surface."""
    catalog = catalog_fake_methods(_FAKE_DIR)
    assert "FakeGit" in catalog, "FakeGit class not found in fake_dir"
    surface = catalog["FakeGit"]["adapter-surface"]
    assert "config_get" in surface, (
        f"config_get missing from FakeGit adapter surface; got {surface}"
    )


def test_config_get_cassette_exists() -> None:
    """config_get must have a cassette recorded under cassettes/git/."""
    methods = catalog_cassette_methods(_CASSETTE_DIR)
    assert "config_get" in methods, (
        f"No cassette for config_get under {_CASSETTE_DIR}; found: {sorted(methods)}"
    )
