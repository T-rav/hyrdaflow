"""Contract tests: FakeGit output must match recorded git-CLI cassettes.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2. Replay-side gate: drive `FakeGit` with cassette inputs and assert the
output matches (after the `sha:short` normalizer collapses commit hashes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_git import FakeGit
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "git"


async def _invoke_fake_git(cassette: Cassette) -> FakeOutput:
    """Dispatch the cassette input through FakeGit's matching method."""
    fake = FakeGit()
    method = cassette.input.command
    args = cassette.input.args

    # Every method operates on a path in the fake's in-memory worktree map.
    cwd = Path("/sandbox")

    if method == "worktree_add":
        await fake.worktree_add(cwd, branch=str(args[0]), new_branch=True)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "commit":
        sha = await fake.commit(cwd, message=str(args[0]))
        # Emit a git-like confirmation line so the cassette shape matches
        # real `git commit` output after the `sha:short` normalizer collapses
        # the hex hash.
        return FakeOutput(
            exit_code=0,
            stdout=f"[main {sha[:7]}] {args[0]}\n",
            stderr="",
        )

    if method == "rev_parse_head":
        # Seed a commit so rev_parse returns something non-zero.
        await fake.commit(cwd, message="seed")
        sha = await fake.rev_parse(cwd, "HEAD")
        return FakeOutput(exit_code=0, stdout=f"{sha}\n", stderr="")

    if method == "worktree_prune":
        await fake.worktree_prune()
        return FakeOutput(exit_code=0, stdout="", stderr="")

    msg = f"FakeGit has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_git_matches_cassette(cassette_path: Path) -> None:
    """Replay a git cassette; assert FakeGit's output matches under normalizers."""
    await replay_cassette(cassette_path, _invoke_fake_git)


def test_cassette_directory_not_empty() -> None:
    """A trust gate with zero cassettes is a silent pass — guard against that."""
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
