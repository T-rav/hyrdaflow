"""Tests for tests/trust/contracts/_schema.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.trust.contracts._schema import (
    NORMALIZERS,
    Cassette,
    apply_normalizers,
    dump_cassette,
    load_cassette,
)

_MINIMAL_YAML = textwrap.dedent(
    """\
    adapter: github
    interaction: pr_create
    recorded_at: 2026-04-22T14:07:03Z
    recorder_sha: abc1234
    fixture_repo: T-rav-Hydra-Ops/hydraflow-contracts-sandbox
    input:
      command: gh pr create
      args: ["--title", "test"]
    output:
      exit_code: 0
      stdout: "https://github.com/test/repo/pull/42\\n"
      stderr: ""
    normalizers:
      - pr_number
    """
)


class TestLoadCassette:
    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(_MINIMAL_YAML)
        cas = load_cassette(path)
        assert cas.adapter == "github"
        assert cas.interaction == "pr_create"
        assert cas.input.command == "gh pr create"
        assert cas.output.exit_code == 0
        assert cas.normalizers == ["pr_number"]

    def test_rejects_unknown_adapter(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(_MINIMAL_YAML.replace("adapter: github", "adapter: slack"))
        with pytest.raises(ValueError, match="adapter must be one of"):
            load_cassette(path)

    def test_rejects_unknown_normalizer(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        bad = _MINIMAL_YAML.replace("pr_number", "not_a_real_normalizer")
        path.write_text(bad)
        with pytest.raises(ValueError, match="unknown normalizer"):
            load_cassette(path)


class TestNormalizers:
    def test_pr_number_replaces_pull_url(self) -> None:
        result = NORMALIZERS["pr_number"]("see https://github.com/a/b/pull/8123 merged")
        assert "<PR_NUMBER>" in result
        assert "8123" not in result

    def test_iso8601_replaces_timestamps(self) -> None:
        text = (
            "started at 2026-04-22T14:07:03Z and ended at 2026-04-22T14:10:45.123+00:00"
        )
        result = NORMALIZERS["timestamps.ISO8601"](text)
        assert "<ISO8601>" in result
        assert "2026-04-22" not in result

    def test_short_sha_replaces_hexes(self) -> None:
        result = NORMALIZERS["sha:short"]("commit abc1234 authored")
        assert "<SHORT_SHA>" in result
        assert "abc1234" not in result

    def test_apply_chains_all_names(self) -> None:
        text = "pr #7 at 2026-04-22T14:00:00Z sha deadbeef"
        result = apply_normalizers(
            text, ["pr_number", "timestamps.ISO8601", "sha:short"]
        )
        assert "2026-04-22" not in result
        assert "deadbeef" not in result


class TestDumpCassette:
    def test_dump_produces_loadable_file(self, tmp_path: Path) -> None:
        cas = Cassette(
            adapter="git",
            interaction="commit",
            recorded_at="2026-04-22T14:07:03Z",
            recorder_sha="abc1234",
            fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
            input={"command": "git commit", "args": ["-m", "x"]},
            output={"exit_code": 0, "stdout": "", "stderr": ""},
            normalizers=[],
        )
        out = tmp_path / "out.yaml"
        dump_cassette(cas, out)
        loaded = load_cassette(out)
        assert loaded.adapter == "git"
        assert loaded.interaction == "commit"
