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


async def _invoke_fake_github(cassette: Cassette) -> FakeOutput:  # noqa: PLR0911
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

    if method == "close_issue":
        issue_number = int(args[0])
        fake.add_issue(issue_number, "Test Issue", "body")
        await fake.close_issue(issue_number)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "close_task":
        n = int(args[0])
        fake.add_issue(n, "Test issue", "")
        await fake.close_task(n)
        assert fake._issues[n].state == "closed"
        return FakeOutput(exit_code=0, stdout="", stderr=f"✓ Closed issue #{n}\n")

    if method == "create_task":
        title = str(args[0])
        body = str(args[1]) if len(args) > 1 else ""
        # FakeGitHub.create_task seeds an issue starting at 9001 when the
        # store is empty; the cassette hard-codes that initial value so the
        # contract is deterministic.
        new_number = await fake.create_task(title, body)
        return FakeOutput(
            exit_code=0,
            stdout=f"https://github.com/test-org/test-repo/issues/{new_number}\n",
            stderr="",
        )

    if method == "add_labels":
        issue_number = int(args[0])
        fake.add_issue(issue_number, "Seed issue", "")
        labels = [str(a) for a in args[1:]]
        await fake.add_labels(issue_number, labels)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "ensure_labels_exist":
        await fake.ensure_labels_exist()
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "get_latest_ci_status":
        # Default FakeGitHub._ci_main_status is ("success", "").
        conclusion, url = await fake.get_latest_ci_status()
        stdout = f"{conclusion}\n{url}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_issues_by_label":
        import json as _json

        label = str(args[0])
        # Seed one issue carrying the label so the list is non-empty and
        # the contract covers the dict shape, not just the empty-list path.
        fake.add_issue(42, "CI failure detected", "main is red", labels=[label])
        issues = await fake.list_issues_by_label(label)
        stdout = _json.dumps(issues) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "create_issue":
        title = str(args[0])
        body = str(args[1]) if len(args) > 1 else ""
        labels = [str(a) for a in args[2:]] if len(args) > 2 else None
        # Empty store: max(keys, default=9000)+1 = 9001; cassette hard-codes
        # that value so the contract is deterministic.
        new_number = await fake.create_issue(title, body, labels=labels)
        return FakeOutput(
            exit_code=0,
            stdout=f"https://github.com/test-org/test-repo/issues/{new_number}\n",
            stderr="",
        )

    if method == "post_comment":
        issue_number = int(args[0])
        body = str(args[1]) if len(args) > 1 else ""
        fake.add_issue(issue_number, "Seed issue", "")
        await fake.post_comment(issue_number, body)
        # Side-effect: comment must be recorded on the issue.
        assert body in fake._issues[issue_number].comments, (
            f"post_comment did not record comment on issue #{issue_number}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

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
