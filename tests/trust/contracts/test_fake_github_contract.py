"""Contract tests: FakeGitHub output must match recorded gh-CLI cassettes.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 "fake contract tests — replay side". Each cassette in
`tests/trust/contracts/cassettes/github/` was recorded against a live gh
CLI against the sandbox repo; this test replays the cassette input through
`FakeGitHub` and asserts the normalized stdout/stderr/exit_code matches.

The refresh side (re-recording the cassettes against the live CLI) lives in
`src/contract_refresh_loop.py` — tracked separately from this replay gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from tests.conftest import IssueFactory
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "github"


async def _invoke_fake_github(cassette: Cassette) -> FakeOutput:
    """Dispatch the cassette input through FakeGitHub's matching method."""
    fake = FakeGitHub()
    method = cassette.input.command
    args = cassette.input.args

    if method == "create_pr":
        issue = IssueFactory.create(number=int(args[0]))
        pr_info = await fake.create_pr(issue, branch=str(args[1]))
        stdout = f"{pr_info.url}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "merge_pr":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        merged = await fake.merge_pr(pr_number)
        assert merged, "FakeGitHub.merge_pr unexpectedly returned False"
        stdout = f"merged pull request https://github.com/_/_/pull/{pr_number}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "close_task":
        n = int(args[0])
        fake.add_issue(n, "Test issue", "")
        await fake.close_task(n)
        assert fake._issues[n].state == "closed"
        return FakeOutput(exit_code=0, stdout="", stderr=f"✓ Closed issue #{n}\n")

    msg = f"FakeGitHub has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_github_matches_cassette(cassette_path: Path) -> None:
    """Replay a GitHub cassette; assert FakeGitHub's output matches under normalizers."""
    await replay_cassette(cassette_path, _invoke_fake_github)


def test_cassette_directory_not_empty() -> None:
    """A trust gate with zero cassettes is a silent pass — guard against that."""
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
