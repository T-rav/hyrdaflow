"""Per-adapter recording subroutines for the fake-contract test cassettes.

§4.2 Task 13 of
``docs/superpowers/plans/2026-04-22-fake-contract-tests.md``.

Each ``record_<adapter>`` function runs the *real* CLI for its adapter
(``gh`` / ``git`` / ``docker`` / ``claude``) and writes one or more
cassette fixtures to a caller-supplied temp directory. The shape of the
YAML payload matches :class:`tests.trust.contracts._schema.Cassette` so
later stages of the ``ContractRefreshLoop`` tick (Tasks 14–18) can diff
the fresh recordings against the committed cassettes and drive
refresh-PRs / drift-repair issues.

Design notes
------------

* **Recording, not replay.** These functions intentionally spawn real
  binaries and talk to real services. The *replay* harness
  (``tests/trust/contracts/_replay.py``) reads the cassettes these
  recorders produce and does not talk to any network.
* **Graceful failure.** A missing binary (``FileNotFoundError``), a
  non-zero CLI exit, a missing sandbox directory, or any
  ``OSError`` / ``subprocess.SubprocessError`` returns an empty
  ``list[Path]`` and emits a ``WARNING``. The caller (the background
  loop's ``_do_work``) decides whether that indicates drift or
  infrastructure trouble — the recorder itself never raises into the
  loop.
* **No side-effects outside the passed-in dir.** Every file written by
  a recorder lives under its ``tmp_cassette_dir`` / ``tmp_stream_dir``
  argument. The background loop is responsible for copying accepted
  cassettes to their committed path (Task 15).
* **Synchronous on purpose.** ``subprocess.run`` is used rather than
  ``asyncio.create_subprocess_exec`` because the refresh tick runs once
  a week and these calls are dominated by network/IO latency; the
  synchronous form is simpler to mock and simpler to reason about. The
  loop wraps these calls behind ``asyncio.to_thread`` so the event
  loop is not blocked while the recorder runs. As a defence-in-depth
  measure, every ``subprocess.run`` here passes
  ``timeout=_RECORDER_SUBPROCESS_TIMEOUT_S`` (120 s) so a hung
  subprocess (network-degraded host, expired auth, rate-limited
  ``api.anthropic.com``) cannot deadlock the event loop even if the
  ``to_thread`` wrapper is bypassed.

Ubiquitous language
-------------------

``cassette``, ``adapter``, ``fixture_repo``, ``interaction``,
``normalizers`` — see ``tests/trust/contracts/_schema.py``.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("hydraflow.contract_recording")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pinned alpine image — a floating ``:latest`` would cause cassette churn
# every time a new alpine layer lands on Docker Hub.
_ALPINE_IMAGE = "alpine:3.19"

# Stable prompt for the Claude stream recorder. "ping" is cheap,
# deterministic in shape (session → assistant → result) even when the
# exact wording of the assistant message varies — the normalizers in
# ``_schema.py`` collapse the volatile bits.
_CLAUDE_PROMPT = "ping"

# Hard wall-clock cap on every recorder subprocess. 120s is generous
# enough for a healthy ``gh``/``git``/``docker``/``claude`` round-trip
# while ensuring a hung subprocess (network-degraded host, expired auth,
# rate-limited ``api.anthropic.com``, frozen Docker daemon) cannot
# deadlock the asyncio event loop forever. Originally surfaced by
# sandbox-tier work (PR #8452 Task 2.5c) where the air-gapped network
# made ``claude -p ping`` hang indefinitely, freezing the orchestrator
# (and the dashboard server with it).
_RECORDER_SUBPROCESS_TIMEOUT_S = 120

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recorder_sha() -> str:
    """Return the short SHA of ``HEAD`` for the recording context, or
    ``"unknown"`` if ``git`` is unavailable. Stamped into every cassette so
    ``git blame`` on a drifted fixture leads back to the recording run.

    A 120-second hard timeout prevents event-loop deadlock when the
    subprocess hangs (network failure, expired auth, frozen filesystem,
    etc.). On timeout we degrade gracefully to ``"unknown"`` rather than
    raise — the cassette payload is best-effort metadata.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_RECORDER_SUBPROCESS_TIMEOUT_S,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return "unknown"
    sha = proc.stdout.strip()
    return sha or "unknown"


def _now_iso() -> str:
    """UTC timestamp in the same format the existing cassettes use."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_cassette_payload(
    *,
    adapter: str,
    interaction: str,
    fixture_repo: str,
    command: str,
    args: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    normalizers: list[str],
) -> dict[str, Any]:
    """Assemble the dict that matches :class:`Cassette`'s schema."""
    return {
        "adapter": adapter,
        "interaction": interaction,
        "recorded_at": _now_iso(),
        "recorder_sha": _recorder_sha(),
        "fixture_repo": fixture_repo,
        "input": {
            "command": command,
            "args": list(args),
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        },
        "normalizers": list(normalizers),
    }


def _write_yaml_cassette(path: Path, payload: dict[str, Any]) -> None:
    """Serialize *payload* to *path* as YAML (mirrors ``_schema.dump_cassette``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run *argv* with captured text output. Return None on
    ``FileNotFoundError`` / ``OSError`` / ``SubprocessError`` /
    ``TimeoutExpired`` and warn-log the failure — the caller propagates
    that as an empty recording list.

    A 120-second hard timeout prevents event-loop deadlock when the
    subprocess hangs (network failure, expired auth, rate-limited
    ``api.anthropic.com``, frozen Docker daemon, etc.). On timeout we
    log a warning and return None so the recorder degrades to "no
    cassette written" rather than freezing the orchestrator's asyncio
    event loop. ``subprocess.TimeoutExpired`` is a subclass of
    ``SubprocessError`` but caught explicitly here for clearer logs.
    """
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_RECORDER_SUBPROCESS_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        logger.warning("contract_recording: binary missing for %s: %s", argv[0], exc)
    except subprocess.TimeoutExpired as exc:
        logger.warning(
            "contract_recording: subprocess timed out after %ss for %s: %s",
            _RECORDER_SUBPROCESS_TIMEOUT_S,
            argv[0],
            exc,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("contract_recording: subprocess failed for %s: %s", argv[0], exc)
    return None


def _require_success(
    proc: subprocess.CompletedProcess[str] | None, *, label: str
) -> bool:
    """Log a warning + return False if *proc* is None or exited non-zero."""
    if proc is None:
        return False
    if proc.returncode != 0:
        logger.warning(
            "contract_recording: %s exited %s: %s",
            label,
            proc.returncode,
            (proc.stderr or "").strip(),
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Public recorders
# ---------------------------------------------------------------------------


def record_github(sandbox_repo: str, tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for the GitHub adapter.

    Runs a stable, read-only ``gh pr list`` against *sandbox_repo* (see
    Task 0 — ``T-rav-Hydra-Ops/hydraflow-contracts-sandbox``) so the shape
    of ``gh``'s JSON output is captured without side-effects on the
    sandbox.

    Returns the list of YAML cassette paths written to
    *tmp_cassette_dir*. Returns ``[]`` if ``gh`` is missing, the call
    exits non-zero, or any other subprocess error occurs.
    """
    tmp_cassette_dir = Path(tmp_cassette_dir)
    tmp_cassette_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        "gh",
        "pr",
        "list",
        "--repo",
        sandbox_repo,
        "--json",
        "number,title,state",
    ]
    proc = _run(argv)
    if not _require_success(proc, label="gh pr list"):
        return []
    assert proc is not None  # for the type checker — guarded above

    payload = _build_cassette_payload(
        adapter="github",
        interaction="pr_list",
        fixture_repo=sandbox_repo,
        command="list_issues_by_label",
        args=[],
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        normalizers=["pr_number", "timestamps.ISO8601", "sha:short"],
    )
    path = tmp_cassette_dir / "pr_list.yaml"
    _write_yaml_cassette(path, payload)
    return [path]


def record_git(sandbox_dir: Path, tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for the git adapter against a fixture sandbox.

    ``sandbox_dir`` is expected to contain at least one file (Task 0 seeds
    ``tests/trust/contracts/fixtures/git_sandbox`` with a ``hello.txt``).
    The recorder runs ``git init`` / ``git add -A`` / ``git commit`` in
    that directory and captures the commit output.

    Returns ``[]`` if the sandbox does not exist, ``git`` is missing, or
    any step exits non-zero.
    """
    sandbox_dir = Path(sandbox_dir)
    tmp_cassette_dir = Path(tmp_cassette_dir)
    if not sandbox_dir.is_dir():
        logger.warning("contract_recording: git sandbox dir missing: %s", sandbox_dir)
        return []
    tmp_cassette_dir.mkdir(parents=True, exist_ok=True)

    sandbox_str = str(sandbox_dir)

    init = _run(["git", "-C", sandbox_str, "init", "-q"])
    if not _require_success(init, label="git init"):
        return []

    add = _run(["git", "-C", sandbox_str, "add", "-A"])
    if not _require_success(add, label="git add"):
        return []

    commit = _run(
        [
            "git",
            "-C",
            sandbox_str,
            "-c",
            "user.email=contract@refresh.local",
            "-c",
            "user.name=contract-refresh",
            "commit",
            "-q",
            "-m",
            "initial",
        ]
    )
    if not _require_success(commit, label="git commit"):
        return []
    assert commit is not None

    payload = _build_cassette_payload(
        adapter="git",
        interaction="commit",
        fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
        command="commit",
        args=["initial"],
        exit_code=commit.returncode,
        stdout=commit.stdout,
        stderr=commit.stderr,
        normalizers=["sha:short"],
    )
    path = tmp_cassette_dir / "commit.yaml"
    _write_yaml_cassette(path, payload)
    return [path]


def record_docker(tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for the docker adapter.

    Runs ``docker run --rm alpine:3.19 echo hello`` — cheap, pinned,
    deterministic. Returns ``[]`` on any docker failure (missing binary,
    daemon offline, pull failure).
    """
    tmp_cassette_dir = Path(tmp_cassette_dir)
    tmp_cassette_dir.mkdir(parents=True, exist_ok=True)

    argv = ["docker", "run", "--rm", _ALPINE_IMAGE, "echo", "hello"]
    proc = _run(argv)
    if not _require_success(proc, label="docker run alpine echo"):
        return []
    assert proc is not None

    # The fake's observable output is the JSON "result" event, not the
    # raw container stdout — store the shape the fake emits so replay
    # compares apples-to-apples. This mirrors the existing committed
    # cassette at tests/trust/contracts/cassettes/docker/run_alpine_echo.yaml.
    fake_shape_stdout = '{"exit_code": 0, "success": true, "type": "result"}\n'

    payload = _build_cassette_payload(
        adapter="docker",
        interaction="run_alpine_echo",
        fixture_repo=_ALPINE_IMAGE,
        command="run_agent",
        args=[_ALPINE_IMAGE, "echo", "hello"],
        exit_code=proc.returncode,
        stdout=fake_shape_stdout,
        stderr="",
        normalizers=[],
    )
    path = tmp_cassette_dir / "run_alpine_echo.yaml"
    _write_yaml_cassette(path, payload)
    return [path]


def record_claude_stream(tmp_stream_dir: Path) -> list[Path]:
    """Record a minimal ``claude`` stream JSONL.

    Runs ``claude -p "ping" --output-format stream-json --verbose`` and
    writes the raw stdout to ``<tmp_stream_dir>/stream_001_ping.jsonl``.
    The Claude adapter cassette is *not* YAML — it is a raw JSONL file
    because the fake replays lines verbatim.

    Returns ``[]`` if ``claude`` is missing, exits non-zero, or produces
    empty stdout (a zero-byte stream is useless as a fixture and would
    only corrupt later diffs).
    """
    tmp_stream_dir = Path(tmp_stream_dir)
    tmp_stream_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        "claude",
        "-p",
        _CLAUDE_PROMPT,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    proc = _run(argv)
    if not _require_success(proc, label="claude -p ping"):
        return []
    assert proc is not None

    if not proc.stdout.strip():
        logger.warning(
            "contract_recording: claude produced empty stream; skipping write"
        )
        return []

    path = tmp_stream_dir / "stream_001_ping.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proc.stdout, encoding="utf-8")
    return [path]
