"""Regression test for issue #8510.

FakeCoverageAuditorLoop filed a gap: ``FakeGitHub.close_issue`` is on the
adapter surface but had no corresponding cassette under
``tests/trust/contracts/cassettes/github/``.  Without a cassette the contract
suite cannot detect fake/real drift on ``close_issue``.

Two assertions:
  1. ``close_issue`` appears in ``catalog_fake_methods`` for ``FakeGitHub``
     (ensures the auditor would see it as an adapter-surface method).
  2. A cassette for ``close_issue`` exists under the github cassette directory
     (ensures the gap reported by the auditor is now closed).
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_cassette_methods, catalog_fake_methods

_FAKE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "mockworld" / "fakes"
)
_CASSETTE_DIR = (
    Path(__file__).resolve().parent.parent
    / "trust"
    / "contracts"
    / "cassettes"
    / "github"
)


class TestIssue8510CloseIssueCassetteCoverage:
    """close_issue must be cataloged as adapter surface and have a cassette."""

    def test_close_issue_is_in_fake_github_adapter_surface(self) -> None:
        """catalog_fake_methods must list close_issue as an adapter-surface method."""
        catalog = catalog_fake_methods(_FAKE_DIR)
        assert "FakeGitHub" in catalog, "FakeGitHub not found in fake catalog"
        surface = catalog["FakeGitHub"]["adapter-surface"]
        assert "close_issue" in surface, (
            f"close_issue not found in FakeGitHub adapter surface; got: {surface}"
        )

    def test_close_issue_cassette_exists(self) -> None:
        """A cassette with input.command == 'close_issue' must exist."""
        cassetted = catalog_cassette_methods(_CASSETTE_DIR)
        assert "close_issue" in cassetted, (
            f"No cassette records close_issue under {_CASSETTE_DIR}; "
            f"cassetted methods: {sorted(cassetted)}"
        )
