"""Regression test for issue #8492.

``FakeGit.config_unset`` is a public adapter-surface method with no cassette
under ``tests/trust/contracts/cassettes/git/``.  The fake-coverage auditor
(``FakeCoverageAuditorLoop``, spec §4.7) compares the set of public methods on
every ``Fake*`` class against the ``input.command`` values recorded in
``*.yaml`` cassettes under the matching adapter directory.  With no cassette,
the auditor continuously files a ``fake-coverage-gap`` issue — this regression
test guards that the cassette lands and stays landed.

Strategy
--------
Call ``catalog_cassette_methods`` against the real cassette directory and
assert ``"config_unset"`` is present.  The test is RED until
``tests/trust/contracts/cassettes/git/config_unset.yaml`` exists with
``input.command: config_unset``.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_cassette_methods

_CASSETTE_DIR = (
    Path(__file__).resolve().parent.parent / "trust" / "contracts" / "cassettes" / "git"
)


class TestFakeGitConfigUnsetHasCassette:
    """config_unset must have a recorded cassette in the git adapter directory."""

    def test_fake_git_config_unset_has_cassette(self) -> None:
        """Given the git cassette directory, config_unset must appear in the
        catalog so the fake-coverage auditor does not refile the gap issue.

        RED until ``cassettes/git/config_unset.yaml`` is committed.
        """
        methods = catalog_cassette_methods(_CASSETTE_DIR)
        assert "config_unset" in methods, (
            f"No cassette for FakeGit.config_unset found in {_CASSETTE_DIR}. "
            "Add tests/trust/contracts/cassettes/git/config_unset.yaml."
        )
