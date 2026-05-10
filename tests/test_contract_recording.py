"""Unit tests for src/contract_recording.py (§4.2 Task 13).

These tests exercise the *recording code structure* without spawning real
``gh`` / ``git`` / ``docker`` / ``claude`` binaries — the recorders are
driven through a mocked :func:`subprocess.run`. For each recorder we
verify:

1. The exact argv passed to ``subprocess.run`` (so signature drift is
   caught here, not at 03:00 on a Sunday refresh tick).
2. The on-disk layout: each recorder writes to the caller-supplied
   ``tmp_cassette_dir`` / ``tmp_stream_dir`` and returns the list of
   written :class:`pathlib.Path` objects.
3. The cassette payload round-trips through
   ``tests/trust/contracts/_schema.Cassette.model_validate`` (YAML
   recorders only — the Claude stream is raw JSONL, not YAML).
4. A missing binary, non-zero exit, or missing sandbox returns an
   empty list and emits a warning — the caller (Task 14's diff loop)
   decides whether that is drift or infrastructure drift, but the
   recorder itself never raises into the background loop.

Real-binary exercise lives in the Task 23 scenario test; this file is
deliberately fast, hermetic, and side-effect free on the filesystem
outside ``tmp_path``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from contract_recording import (
    record_claude_stream,
    record_docker,
    record_git,
    record_github,
)
from tests.trust.contracts._schema import Cassette

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    *,
    argv: list[str],
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Build a ``subprocess.CompletedProcess`` matching the mock's signature."""
    return subprocess.CompletedProcess(
        args=argv, returncode=returncode, stdout=stdout, stderr=stderr
    )


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    assert isinstance(raw, dict)
    return raw


# ---------------------------------------------------------------------------
# record_github
# ---------------------------------------------------------------------------


def test_record_github_invokes_gh_api_with_sandbox_repo(tmp_path: Path) -> None:
    """``record_github`` shells out to ``gh`` against the sandbox repo."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv=argv, stdout='[{"number": 1}]\n')

    with patch("contract_recording.subprocess.run", side_effect=fake_run):
        paths = record_github(
            sandbox_repo="T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
            tmp_cassette_dir=tmp_path,
        )

    assert len(paths) == 1
    # First call must be ``gh`` with the sandbox repo slug — we pin the
    # subcommand enough that an accidental ``gh repo view`` swap trips this.
    first = calls[0]
    assert first[0] == "gh"
    assert "T-rav-Hydra-Ops/hydraflow-contracts-sandbox" in first
    assert "--json" in first or "api" in first[1]


def test_record_github_writes_schema_valid_cassette(tmp_path: Path) -> None:
    """The YAML written by ``record_github`` round-trips through ``Cassette``."""
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(
            argv=argv, stdout='[{"number": 1, "title": "t"}]\n'
        ),
    ):
        paths = record_github(
            sandbox_repo="T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
            tmp_cassette_dir=tmp_path,
        )

    assert paths, "recorder must write at least one cassette"
    for path in paths:
        assert path.parent == tmp_path
        assert path.suffix == ".yaml"
        cassette = Cassette.model_validate(_load_yaml(path))
        assert cassette.adapter == "github"
        assert cassette.fixture_repo == "T-rav-Hydra-Ops/hydraflow-contracts-sandbox"


def test_record_github_returns_empty_when_gh_missing(tmp_path: Path) -> None:
    """``FileNotFoundError`` (missing ``gh``) yields an empty list, not a raise."""
    with patch(
        "contract_recording.subprocess.run",
        side_effect=FileNotFoundError("gh not installed"),
    ):
        paths = record_github(
            sandbox_repo="T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
            tmp_cassette_dir=tmp_path,
        )
    assert paths == []


def test_record_github_returns_empty_on_nonzero_exit(tmp_path: Path) -> None:
    """A non-zero ``gh`` exit is treated as a failed recording (empty list)."""
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(
            argv=argv, stderr="network error\n", returncode=1
        ),
    ):
        paths = record_github(
            sandbox_repo="T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
            tmp_cassette_dir=tmp_path,
        )
    assert paths == []


# ---------------------------------------------------------------------------
# record_git
# ---------------------------------------------------------------------------


def test_record_git_runs_init_add_commit_in_sandbox(tmp_path: Path) -> None:
    """``record_git`` drives a real-looking git sequence in the sandbox dir."""
    sandbox = tmp_path / "git_sandbox"
    sandbox.mkdir()
    (sandbox / "hello.txt").write_text("hi\n", encoding="utf-8")
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()

    calls: list[list[str]] = []
    sha_40 = "a" * 40

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if "rev-parse" in argv:
            return _completed(argv=argv, stdout=f"{sha_40}\n")
        return _completed(argv=argv, stdout="[main abc1234] initial\n")

    with patch("contract_recording.subprocess.run", side_effect=fake_run):
        paths = record_git(sandbox_dir=sandbox, tmp_cassette_dir=cassette_dir)

    # We expect at least four git calls: init, add, commit, rev-parse.
    subcommands = [c[c.index("git") + 1 :] for c in calls if "git" in c]
    flat = [tok for seq in subcommands for tok in seq]
    assert "init" in flat
    assert "add" in flat
    assert "commit" in flat
    assert "rev-parse" in flat
    # Two cassettes are written: commit.yaml and rev_parse.yaml.
    assert len(paths) == 2
    assert all(p.parent == cassette_dir for p in paths)
    assert all(p.suffix == ".yaml" for p in paths)


def test_record_git_writes_schema_valid_cassette(tmp_path: Path) -> None:
    sandbox = tmp_path / "git_sandbox"
    sandbox.mkdir()
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()

    sha_40 = "b" * 40

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in argv:
            return _completed(argv=argv, stdout=f"{sha_40}\n")
        return _completed(argv=argv, stdout="[main abc1234] initial\n")

    with patch("contract_recording.subprocess.run", side_effect=fake_run):
        paths = record_git(sandbox_dir=sandbox, tmp_cassette_dir=cassette_dir)

    assert paths
    by_stem = {p.stem: p for p in paths}
    commit_cas = Cassette.model_validate(_load_yaml(by_stem["commit"]))
    assert commit_cas.adapter == "git"
    assert commit_cas.interaction == "commit"
    rev_parse_cas = Cassette.model_validate(_load_yaml(by_stem["rev_parse"]))
    assert rev_parse_cas.adapter == "git"
    assert rev_parse_cas.interaction == "rev_parse"
    assert rev_parse_cas.input.command == "rev_parse"
    assert rev_parse_cas.input.args == ["HEAD"]
    assert "sha:long" in rev_parse_cas.normalizers


def test_record_git_returns_empty_when_sandbox_missing(tmp_path: Path) -> None:
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()

    with patch("contract_recording.subprocess.run") as run_mock:
        paths = record_git(
            sandbox_dir=tmp_path / "does_not_exist",
            tmp_cassette_dir=cassette_dir,
        )

    assert paths == []
    run_mock.assert_not_called()


def test_record_git_returns_empty_when_binary_missing(tmp_path: Path) -> None:
    sandbox = tmp_path / "git_sandbox"
    sandbox.mkdir()
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()

    with patch(
        "contract_recording.subprocess.run",
        side_effect=FileNotFoundError("git not installed"),
    ):
        paths = record_git(sandbox_dir=sandbox, tmp_cassette_dir=cassette_dir)
    assert paths == []


# ---------------------------------------------------------------------------
# record_docker
# ---------------------------------------------------------------------------


def test_record_docker_runs_alpine_echo(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _completed(argv=argv, stdout="hello\n")

    with patch("contract_recording.subprocess.run", side_effect=fake_run):
        paths = record_docker(tmp_cassette_dir=tmp_path)

    # Exactly one ``docker`` invocation (the recorder also stamps a
    # ``git rev-parse`` into the cassette — that's fine, we just care
    # the docker side is minimal and pinned).
    docker_calls = [c for c in calls if c and c[0] == "docker"]
    assert len(docker_calls) == 1
    argv = docker_calls[0]
    assert argv[0] == "docker"
    assert "run" in argv
    assert "--rm" in argv
    # Pinned alpine tag must be present so a floating :latest can't leak in.
    assert any(tok.startswith("alpine:") for tok in argv)
    assert "echo" in argv
    assert len(paths) == 1
    assert paths[0].parent == tmp_path
    assert paths[0].suffix == ".yaml"


def test_record_docker_writes_schema_valid_cassette(tmp_path: Path) -> None:
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(argv=argv, stdout="hello\n"),
    ):
        paths = record_docker(tmp_cassette_dir=tmp_path)
    cassette = Cassette.model_validate(_load_yaml(paths[0]))
    assert cassette.adapter == "docker"
    assert cassette.interaction == "run_alpine_echo"


def test_record_docker_returns_empty_on_failure(tmp_path: Path) -> None:
    with patch(
        "contract_recording.subprocess.run",
        side_effect=FileNotFoundError("docker not installed"),
    ):
        paths = record_docker(tmp_cassette_dir=tmp_path)
    assert paths == []


def test_record_docker_returns_empty_on_nonzero_exit(tmp_path: Path) -> None:
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(
            argv=argv, stderr="daemon offline\n", returncode=125
        ),
    ):
        paths = record_docker(tmp_cassette_dir=tmp_path)
    assert paths == []


# ---------------------------------------------------------------------------
# record_claude_stream
# ---------------------------------------------------------------------------


def test_record_claude_stream_invokes_claude_with_ping(tmp_path: Path) -> None:
    captured: list[list[str]] = []
    sample_stream = (
        '{"type": "session", "session_id": "sess_001"}\n'
        '{"type": "result", "result": "pong"}\n'
    )

    def fake_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.append(list(argv))
        return _completed(argv=argv, stdout=sample_stream)

    with patch("contract_recording.subprocess.run", side_effect=fake_run):
        paths = record_claude_stream(tmp_stream_dir=tmp_path)

    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == "claude"
    assert "-p" in argv
    # The prompt is ``ping`` per the task spec.
    assert "ping" in argv
    assert len(paths) == 1
    assert paths[0].parent == tmp_path
    assert paths[0].suffix == ".jsonl"


def test_record_claude_stream_writes_raw_jsonl(tmp_path: Path) -> None:
    """Claude output is stored as raw .jsonl (not YAML)."""
    sample_stream = '{"type": "session", "session_id": "sess_001"}\n'
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(argv=argv, stdout=sample_stream),
    ):
        paths = record_claude_stream(tmp_stream_dir=tmp_path)

    text = paths[0].read_text(encoding="utf-8")
    # Each line must parse as a standalone JSON object.
    import json

    for line in text.splitlines():
        if line.strip():
            json.loads(line)


def test_record_claude_stream_returns_empty_when_binary_missing(
    tmp_path: Path,
) -> None:
    with patch(
        "contract_recording.subprocess.run",
        side_effect=FileNotFoundError("claude not installed"),
    ):
        paths = record_claude_stream(tmp_stream_dir=tmp_path)
    assert paths == []


def test_record_claude_stream_returns_empty_on_nonzero_exit(tmp_path: Path) -> None:
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(
            argv=argv, stderr="auth error\n", returncode=2
        ),
    ):
        paths = record_claude_stream(tmp_stream_dir=tmp_path)
    assert paths == []


def test_record_claude_stream_returns_empty_when_stdout_blank(tmp_path: Path) -> None:
    """Empty stdout is treated as a failed recording — zero-byte streams are
    not useful as fixtures and would only corrupt later diffs."""
    with patch(
        "contract_recording.subprocess.run",
        side_effect=lambda argv, **_: _completed(argv=argv, stdout=""),
    ):
        paths = record_claude_stream(tmp_stream_dir=tmp_path)
    assert paths == []


# ---------------------------------------------------------------------------
# Cross-cutting: logging on failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recorder_args",
    [
        (
            record_github,
            {
                "sandbox_repo": "T-rav-Hydra-Ops/hydraflow-contracts-sandbox",
            },
        ),
        (record_docker, {}),
        (record_claude_stream, {}),
    ],
)
def test_recorder_logs_warning_on_missing_binary(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    recorder_args: tuple[object, dict[str, object]],
) -> None:
    recorder, kwargs = recorder_args
    # Each recorder takes one ``tmp_*_dir`` kwarg — normalize.
    if recorder is record_claude_stream:
        kwargs = {**kwargs, "tmp_stream_dir": tmp_path}
    else:
        kwargs = {**kwargs, "tmp_cassette_dir": tmp_path}

    with (
        patch(
            "contract_recording.subprocess.run",
            side_effect=FileNotFoundError("binary missing"),
        ),
        caplog.at_level("WARNING", logger="hydraflow.contract_recording"),
    ):
        result = recorder(**kwargs)  # type: ignore[operator]

    assert result == []
    assert any(
        "contract_recording" in rec.name or "binary missing" in rec.message
        for rec in caplog.records
    )


def test_record_git_logs_warning_when_sandbox_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    with caplog.at_level("WARNING", logger="hydraflow.contract_recording"):
        result = record_git(
            sandbox_dir=tmp_path / "missing", tmp_cassette_dir=cassette_dir
        )
    assert result == []
    assert any("missing" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Contract: ``subprocess.run`` is always invoked with ``capture_output`` +
# ``text`` so we get strings back. The recorders must pass these — otherwise
# the cassette builder would try to encode bytes with YAML.
# ---------------------------------------------------------------------------


def test_recorders_invoke_subprocess_run_with_text_capture(tmp_path: Path) -> None:
    """All recorders call ``subprocess.run`` with ``capture_output=True, text=True``."""
    cassette_dir = tmp_path / "cassettes"
    cassette_dir.mkdir()
    sandbox = tmp_path / "sbx"
    sandbox.mkdir()

    for recorder, kwargs in (
        (
            record_github,
            {
                "sandbox_repo": "x/y",
                "tmp_cassette_dir": cassette_dir,
            },
        ),
        (record_git, {"sandbox_dir": sandbox, "tmp_cassette_dir": cassette_dir}),
        (record_docker, {"tmp_cassette_dir": cassette_dir}),
        (record_claude_stream, {"tmp_stream_dir": cassette_dir}),
    ):
        run_mock = MagicMock(
            side_effect=lambda argv, **_: _completed(argv=argv, stdout="{}\n")
        )
        with patch("contract_recording.subprocess.run", run_mock):
            recorder(**kwargs)  # type: ignore[operator]
        assert run_mock.call_count >= 1
        for call in run_mock.call_args_list:
            kwargs_passed = call.kwargs
            assert kwargs_passed.get("capture_output") is True, (
                f"{recorder.__name__} must call subprocess.run with capture_output=True"
            )
            assert kwargs_passed.get("text") is True, (
                f"{recorder.__name__} must call subprocess.run with text=True"
            )
            # ``check=False`` — we handle non-zero exits ourselves.
            assert kwargs_passed.get("check", False) is False
