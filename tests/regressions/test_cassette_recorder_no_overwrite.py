"""Regression: cassette recorder must not overwrite non-empty stdout with empty.

Observed 2026-05-13 in this repo: ``tests/trust/contracts/cassettes/git/commit.yaml``
got rewritten with empty ``output.stdout`` after a local factory run. The replay
test (``test_fake_git_contract::test_fake_git_matches_cassette[commit]``)
then failed because ``FakeGit.commit`` legitimately emits
``[main <SHA>] initial`` — i.e. the existing contract was correct and the
recorder produced degenerate output.

Two failure modes contributed:

1. ``record_git`` used ``git commit -q``, which suppresses the confirmation
   line. The "real" output the fake emulates is the non-quiet form.
2. ``_write_yaml_cassette`` blindly overwrote the existing cassette even
   when the new payload's stdout was empty and the old payload's wasn't.

These tests guard both: removing ``-q`` plus a defence-in-depth refusal
to overwrite a non-empty cassette with an empty one.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest
import yaml


def _write_existing(path: Path, stdout: str) -> None:
    """Drop a minimal-but-valid cassette at ``path`` with the given stdout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-04-22T14:00:00Z",
        "recorder_sha": "abc1234",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {"command": "commit", "args": ["initial"], "stdin": None, "env": {}},
        "output": {"exit_code": 0, "stdout": stdout, "stderr": ""},
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)


def test_write_refuses_empty_stdout_over_non_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """If the existing cassette had non-empty stdout and the new payload's
    stdout is empty, the file must NOT be overwritten — preserves the
    committed contract until a healthy recorder run produces a real value."""
    from contract_recording import _build_cassette_payload, _write_yaml_cassette

    cassette = tmp_path / "commit.yaml"
    _write_existing(cassette, stdout="[main abc1234] initial\n")
    original_bytes = cassette.read_bytes()

    degenerate = _build_cassette_payload(
        adapter="git",
        interaction="commit",
        fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
        command="commit",
        args=["initial"],
        exit_code=0,
        stdout="",
        stderr="",
        normalizers=["sha:short"],
    )

    with caplog.at_level(logging.WARNING, logger="hydraflow.contract_recording"):
        _write_yaml_cassette(cassette, degenerate)

    assert cassette.read_bytes() == original_bytes, (
        "cassette was overwritten despite empty new stdout"
    )
    assert any(
        "empty" in r.message.lower() or "degenerate" in r.message.lower()
        for r in caplog.records
    ), f"expected a warning about the skip; got {[r.message for r in caplog.records]}"


def test_write_allows_empty_when_existing_was_also_empty(tmp_path: Path) -> None:
    """When both old and new have empty stdout, the rewrite is fine (refreshes
    other fields like ``recorded_at`` / ``recorder_sha``)."""
    from contract_recording import _build_cassette_payload, _write_yaml_cassette

    cassette = tmp_path / "push.yaml"
    _write_existing(cassette, stdout="")  # legitimately empty
    new_payload = _build_cassette_payload(
        adapter="git",
        interaction="push",
        fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
        command="push",
        args=["origin", "main"],
        exit_code=0,
        stdout="",
        stderr="",
        normalizers=[],
    )

    _write_yaml_cassette(cassette, new_payload)

    loaded = yaml.safe_load(cassette.read_text())
    assert loaded["output"]["stdout"] == ""
    assert loaded["interaction"] == "push"


def test_write_allows_first_time_creation(tmp_path: Path) -> None:
    """First-time creation (no existing file) must always succeed, even when
    stdout is empty — there's nothing to compare against."""
    from contract_recording import _build_cassette_payload, _write_yaml_cassette

    cassette = tmp_path / "brand_new.yaml"
    payload = _build_cassette_payload(
        adapter="git",
        interaction="push",
        fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
        command="push",
        args=["origin", "main"],
        exit_code=0,
        stdout="",
        stderr="",
        normalizers=[],
    )

    _write_yaml_cassette(cassette, payload)

    assert cassette.exists()


def test_record_git_captures_commit_confirmation_line(tmp_path: Path) -> None:
    """End-to-end: the recorder's actual git commit invocation must capture
    the ``[main <sha>] initial`` confirmation line (i.e. no ``-q`` flag)."""
    git_bin = shutil.which("git")
    if git_bin is None:
        pytest.skip("git binary not available")

    from contract_recording import record_git

    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "hello.txt").write_text("hi\n")
    out_dir = tmp_path / "cassettes"

    paths = record_git(fixture, out_dir)

    assert paths, "recorder returned no cassettes"
    commit_cassette = next(p for p in paths if p.name == "commit.yaml")
    loaded = yaml.safe_load(commit_cassette.read_text())
    stdout = loaded["output"]["stdout"]
    assert "[main" in stdout and "] initial" in stdout, (
        f"git commit confirmation line missing from recording; got stdout={stdout!r}"
    )
