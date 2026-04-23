"""Tests for tests/trust/contracts/_replay.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_YAML = textwrap.dedent(
    """\
    adapter: git
    interaction: commit
    recorded_at: 2026-04-22T14:00:00Z
    recorder_sha: abc1234
    fixture_repo: tests/trust/contracts/fixtures/git_sandbox
    input:
      command: git commit
      args: ["-m", "hello"]
    output:
      exit_code: 0
      stdout: "[main deadbeef] hello\\n"
      stderr: ""
    normalizers:
      - sha:short
    """
)


@pytest.mark.asyncio
async def test_replay_passes_when_fake_matches_with_normalizer(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASSETTE_YAML)

    async def fake(_cas: Cassette) -> FakeOutput:
        # Different SHA, but normalizer collapses it.
        return FakeOutput(exit_code=0, stdout="[main cafebabe] hello\n", stderr="")

    await replay_cassette(path, fake)


@pytest.mark.asyncio
async def test_replay_fails_on_exit_code_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASSETTE_YAML)

    async def fake(_cas: Cassette) -> FakeOutput:
        return FakeOutput(exit_code=1, stdout="[main deadbeef] hello\n", stderr="")

    with pytest.raises(AssertionError, match="exit_code mismatch"):
        await replay_cassette(path, fake)


@pytest.mark.asyncio
async def test_replay_fails_on_stdout_body_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(_CASSETTE_YAML)

    async def fake(_cas: Cassette) -> FakeOutput:
        return FakeOutput(exit_code=0, stdout="[main deadbeef] goodbye\n", stderr="")

    with pytest.raises(AssertionError, match="stdout drift"):
        await replay_cassette(path, fake)


def test_list_cassettes_is_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.yaml").write_text("x")
    (tmp_path / "a.yaml").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    out = list_cassettes(tmp_path)
    assert [p.name for p in out] == ["a.yaml", "b.yaml"]
