"""Regression test for issue #8493.

Invariant: every public port method on FakeGit must be covered by at least one
cassette under tests/trust/contracts/cassettes/git/. Before this fix, FakeGit.push
had no matching cassette, meaning the fake/real adapter contract was unverifiable
for the push operation.

This test pins the specific invariant: a cassette with input.command == "push"
must exist in the git cassette directory.
"""

from __future__ import annotations

from pathlib import Path

from tests.trust.contracts._replay import list_cassettes
from tests.trust.contracts._schema import load_cassette

_GIT_CASSETTE_DIR = (
    Path(__file__).parent.parent / "trust" / "contracts" / "cassettes" / "git"
)


def _cassette_commands() -> set[str]:
    """Return the set of input.command values across all git cassettes."""
    return {load_cassette(p).input.command for p in list_cassettes(_GIT_CASSETTE_DIR)}


def test_push_cassette_exists() -> None:
    """FakeGit.push must be covered by at least one git cassette."""
    commands = _cassette_commands()
    assert "push" in commands, (
        "No git cassette found with input.command == 'push'. "
        "FakeGit.push is a public port method and must have a matching cassette "
        "under tests/trust/contracts/cassettes/git/ per the fake-coverage contract "
        "(ADR-0047, spec §4.7)."
    )
