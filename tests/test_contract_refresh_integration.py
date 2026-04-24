"""End-to-end integration tests for :mod:`contract_refresh_loop` (§4.2 Task 21).

This file is intentionally separate from
``tests/test_contract_refresh_loop.py`` — that module mocks
:func:`contract_diff.detect_fleet_drift` and
:func:`auto_pr.open_automated_pr_async` as independent pinholes,
never exercising the recorder→diff→stage→PR ladder as one unit. The
integration tests below stitch those stages together against the
*real* ``detect_fleet_drift`` implementation + the real
:class:`DedupStore` file round-trip + the real PR-body synthesis,
mocking only the two genuine external surfaces:

* the per-adapter recorders (``record_github`` / ``record_git`` /
  ``record_docker`` / ``record_claude_stream``) — these spawn real
  binaries and must not run in a unit-test harness.
* :func:`auto_pr.open_automated_pr_async` — this shells out to
  ``git`` + ``gh``; stubbing it keeps the test hermetic without
  coupling to the real worktree / gh auth machinery.

The replay gate (``make trust-contracts``) is mocked at the
``subprocess.run`` seam the loop reads — the same seam the Task 16
unit tests drive — so both gate-pass and gate-fail paths flow through
the real issue-filing code.

Scope (per Task 21 of the plan):

* **Happy-path drift** — seeded mismatched cassettes flow through the
  real ``detect_fleet_drift`` → ``_stage_drifted_cassettes`` →
  ``_open_refresh_pr`` → ``_run_replay_gate`` ladder. Assertions:
  PR opened with the expected title/labels/files, dedup entry
  persisted to JSON, replay gate invoked, no companion issue filed.
* **Replay-gate fail → companion issue** — same drift, but the
  replay gate exits non-zero. Assertions: refresh PR still opens,
  ``PRManager.create_issue`` fires with ``hydraflow-find`` +
  ``fake-drift`` labels and the stderr tail embedded in the body.

Each scenario completes in well under a second because there is no
real I/O to ``gh`` / ``git`` / ``docker`` / ``claude``, and the
dedup JSON round-trip is a few bytes on tmpfs.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

import contract_refresh_loop as crl_module
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from events import EventBus

# ---------------------------------------------------------------------------
# Helpers — kept local so the unit-test monkeypatch helpers from
# ``tests/test_contract_refresh_loop`` never leak into this module.
# ---------------------------------------------------------------------------


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


class _FakeState:
    """Minimal in-memory stand-in for the contract-refresh StateTracker surface.

    ``ContractRefreshLoop.__init__`` stores the state ref; no integration
    scenario here exercises the Task 18 attempt counters, so a no-op
    stand-in is enough to satisfy the constructor contract without
    pulling in the filesystem-backed ``StateTracker``.
    """

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}

    def get_contract_refresh_attempts(self, adapter: str) -> int:
        return int(self._attempts.get(adapter, 0))

    def inc_contract_refresh_attempts(self, adapter: str) -> int:
        self._attempts[adapter] = self._attempts.get(adapter, 0) + 1
        return self._attempts[adapter]

    def clear_contract_refresh_attempts(self, adapter: str) -> None:
        self._attempts.pop(adapter, None)


def _loop(tmp_path: Path, *, prs: Any | None = None) -> ContractRefreshLoop:
    """Build a :class:`ContractRefreshLoop` rooted at ``tmp_path``.

    The loop's ``config.repo_root`` is set to ``tmp_path / "repo"`` so
    cassette writes from :meth:`_stage_drifted_cassettes` land under
    the sandbox and never escape to the real HydraFlow tree.
    """
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    pr_manager = prs if prs is not None else AsyncMock()
    return ContractRefreshLoop(
        config=cfg,
        prs=pr_manager,
        state=_FakeState(),
        deps=_deps(asyncio.Event(), enabled=True),
    )


def _write_committed_git_cassette(repo_root: Path, *, stdout: str) -> Path:
    """Seed a committed git cassette under the loop's repo_root.

    Returns the committed path. The ``stdout`` field is the only knob
    exercised in these tests — swap it between two calls to simulate
    drift (a fake whose observable output has changed) or leave it
    equal to simulate a clean tick.
    """
    committed_dir = repo_root / "tests" / "trust" / "contracts" / "cassettes" / "git"
    committed_dir.mkdir(parents=True, exist_ok=True)
    path = committed_dir / "commit.yaml"
    payload = {
        "adapter": "git",
        "interaction": "commit",
        "recorded_at": "2026-04-22T14:00:00Z",
        "recorder_sha": "deadbeef",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {
            "command": "commit",
            "args": ["initial"],
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
        },
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


def _write_recorded_git_cassette(tmp_dir: Path, *, stdout: str) -> Path:
    """Write a tmp-dir "fresh recording" cassette with the same slug.

    The recorder returns ``[<this path>]`` from the mocked seam; the
    loop then passes it into the real :func:`detect_fleet_drift` which
    diffs against the committed cassette seeded by
    :func:`_write_committed_git_cassette`.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_dir / "commit.yaml"
    payload = {
        "adapter": "git",
        "interaction": "commit",
        # Different volatile fields — stripped by canonicalization, so
        # any drift we see here is real semantic drift, not audit noise.
        "recorded_at": "2026-04-23T09:15:30Z",
        "recorder_sha": "cafef00d",
        "fixture_repo": "tests/trust/contracts/fixtures/git_sandbox",
        "input": {
            "command": "commit",
            "args": ["initial"],
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": 0,
            "stdout": stdout,
            "stderr": "",
        },
        "normalizers": ["sha:short"],
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)
    return path


class _FakeAutoPR:
    """Captures ``open_automated_pr_async`` calls and returns a canned result."""

    def __init__(self, status: str = "opened") -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    async def __call__(self, **kwargs: Any) -> AutoPrResult:
        self.calls.append(kwargs)
        return AutoPrResult(
            status=self.status,  # type: ignore[arg-type]
            pr_url="https://github.com/hydra/hydraflow/pull/777"
            if self.status == "opened"
            else None,
            branch=kwargs.get("branch", ""),
        )


def _stub_recorders_only_git(
    monkeypatch: pytest.MonkeyPatch, recorded_path: Path
) -> None:
    """Stub out every recorder except ``record_git``.

    The three remaining recorders return empty lists — the diff layer
    treats that as "tool missing / sandbox offline" no-signal, so only
    the git adapter's real diff fires.
    """
    monkeypatch.setattr(crl_module, "record_github", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_path])
    monkeypatch.setattr(crl_module, "record_docker", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_claude_stream", lambda *_a, **_k: [])


def _patch_subprocess_run(
    monkeypatch: pytest.MonkeyPatch, *, returncode: int, stderr: str = ""
) -> list[list[str]]:
    """Patch ``subprocess.run`` used by ``_run_replay_gate``.

    Returns a mutable list the tests can inspect after ``_do_work``
    completes. Every ``subprocess.run`` call goes through this stub —
    in practice the only caller inside ``_do_work`` is the replay
    gate, so the list contains exactly that one argv.
    """
    calls: list[list[str]] = []

    def _fake_run(
        argv: list[str], *_a: Any, **_k: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            args=argv,
            returncode=returncode,
            stdout="OK\n" if returncode == 0 else "FAILED\n",
            stderr=stderr,
        )

    monkeypatch.setattr(crl_module.subprocess, "run", _fake_run)
    return calls


# ---------------------------------------------------------------------------
# Scenario 1 — happy-path drift end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_drift_opens_pr_and_records_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mismatched cassette → real diff fires, PR opens, dedup persists.

    The committed cassette ships stdout ``"[main abc1234] initial\\n"``;
    the recorder side emits ``"[main feedf00d] renamed\\n"`` — the
    ``sha:short`` normalizer collapses the SHA tokens, but the commit
    *message* (``initial`` vs ``renamed``) is a real contract change
    the normalizer cannot hide, so the diff layer produces exactly one
    drifted cassette.
    """
    loop = _loop(tmp_path)
    repo_root = loop._config.repo_root

    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")
    recorded = _write_recorded_git_cassette(
        tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
    )
    _stub_recorders_only_git(monkeypatch, recorded)

    fake_pr = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake_pr)

    replay_calls = _patch_subprocess_run(monkeypatch, returncode=0)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=0)

    # Re-build the loop with our AsyncMock prs so the companion-issue
    # assertion below has a real spy to inspect.
    loop = _loop(tmp_path, prs=prs)
    result = await loop._do_work()

    # Real detect_fleet_drift saw the mismatched stdout and produced
    # exactly one drifted-cassette report; the tick's stats reflect it.
    assert result["status"] == "refreshed", result
    assert result["adapters_drifted"] == 1, result
    assert result["adapters_refreshed"] == 1, result
    assert result["replay_gate_passed"] is True, result
    assert result["fake_drift_issue"] is None, result
    assert result["pr_url"] == "https://github.com/hydra/hydraflow/pull/777", result

    # Auto-PR seam was called exactly once with the expected shape.
    assert len(fake_pr.calls) == 1
    kwargs = fake_pr.calls[0]
    assert kwargs["branch"].startswith("contract-refresh/")
    assert kwargs["pr_title"].startswith("contract-refresh: ")
    assert "git" in kwargs["pr_title"]
    assert "contract-refresh" in kwargs["labels"]
    assert "auto-merge" in kwargs["labels"]
    # The staged file is the committed cassette path under repo_root.
    staged = [Path(p) for p in kwargs["files"]]
    assert len(staged) == 1
    assert staged[0].name == "commit.yaml"
    assert staged[0].is_relative_to(repo_root)

    # The staged cassette now carries the recorder bytes — not the
    # original committed bytes — so the PR actually ships the fresh
    # recording. This is the load-bearing invariant: a refresh PR that
    # didn't overwrite the committed file would merge into a no-op.
    # We key off the distinct stdout tokens (``renamed`` in recorder,
    # ``initial`` in committed's output) because the commit-message
    # args happen to match between the two; it's the stdout the fake
    # replays, not the input args.
    staged_bytes = staged[0].read_bytes()
    assert b"renamed" in staged_bytes, staged_bytes
    # The fresh recorder_sha marker pins this down — committed side
    # had ``deadbeef``, recorder emitted ``cafef00d``.
    assert b"cafef00d" in staged_bytes, staged_bytes
    assert b"deadbeef" not in staged_bytes, staged_bytes

    # Replay gate ran exactly once.
    assert replay_calls == [["make", "trust-contracts"]]

    # Companion-issue path was NOT taken on a green replay.
    prs.create_issue.assert_not_awaited()

    # Dedup entry persisted to the per-loop JSON — a second identical
    # tick will short-circuit.
    dedup_path = loop._config.data_root / "dedup" / "contract_refresh.json"
    assert dedup_path.exists()
    text = dedup_path.read_text()
    assert text.strip() not in ("", "[]")


# ---------------------------------------------------------------------------
# Scenario 2 — replay gate fails after refresh → companion issue filed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_replay_gate_fail_files_fake_drift_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift + red replay gate → refresh PR opens + fake-drift companion issue.

    The replay gate's ``stderr`` tail is embedded in the companion
    issue body so an operator has the diff without re-running locally.
    """
    loop = _loop(tmp_path)
    repo_root = loop._config.repo_root

    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")
    recorded = _write_recorded_git_cassette(
        tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
    )
    _stub_recorders_only_git(monkeypatch, recorded)

    fake_pr = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake_pr)

    _patch_subprocess_run(
        monkeypatch,
        returncode=2,
        stderr="AssertionError: replay mismatch at fake_git commit\n",
    )

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=4321)
    loop = _loop(tmp_path, prs=prs)
    result = await loop._do_work()

    # Refresh PR still opens — the replay gate only decides whether a
    # companion issue is filed.
    assert len(fake_pr.calls) == 1, fake_pr.calls
    assert result["pr_url"] == "https://github.com/hydra/hydraflow/pull/777"
    assert result["replay_gate_passed"] is False
    assert result["fake_drift_issue"] == 4321

    # Companion issue was filed with the factory-routing labels + the
    # replay stderr tail embedded in the body.
    prs.create_issue.assert_awaited_once()
    issue_kwargs = prs.create_issue.await_args.kwargs
    labels = issue_kwargs["labels"]
    assert "hydraflow-find" in labels
    assert "fake-drift" in labels
    assert "adapter-git" in labels
    body = issue_kwargs["body"]
    assert "replay mismatch" in body
    # The refresh PR URL is threaded into the issue body so the repair
    # implementer can open the PR straight from the companion issue.
    assert "https://github.com/hydra/hydraflow/pull/777" in body


# ---------------------------------------------------------------------------
# Scenario 3 — post-refresh quiescence: second tick reads clean
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_tick_after_refresh_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a successful refresh, the next tick sees no drift.

    ``_stage_drifted_cassettes`` overwrites the committed file with
    the recorder bytes. On the next tick the recorder emits those
    same bytes again, so the real ``detect_fleet_drift`` canonicalizes
    both sides identically and reports no drift — the loop returns
    ``status="clean"`` without touching ``auto_pr`` or the replay
    gate a second time. This is the load-bearing "weekly loop
    quiesces after a successful refresh" guarantee.

    Note: the dedup short-circuit (``status="dedup_hit"``) is
    exercised by the unit test ``test_do_work_dedup_hit_skips_pr``
    against a mocked ``detect_fleet_drift`` — in integration, real
    diff sees matching bytes and returns no reports, which is the
    happy-path the dedup guard exists to defend.
    """
    loop = _loop(tmp_path)
    repo_root = loop._config.repo_root

    _write_committed_git_cassette(repo_root, stdout="[main abc1234] initial\n")
    recorded = _write_recorded_git_cassette(
        tmp_path / "rec" / "git", stdout="[main feedf00d] renamed\n"
    )
    _stub_recorders_only_git(monkeypatch, recorded)

    fake_pr = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake_pr)
    replay_calls = _patch_subprocess_run(monkeypatch, returncode=0)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=0)
    loop = _loop(tmp_path, prs=prs)

    # Tick #1: PR filed, staged cassette overwrites committed.
    first = await loop._do_work()
    assert first["status"] == "refreshed"
    assert len(fake_pr.calls) == 1
    assert len(replay_calls) == 1

    # Tick #2: committed matches recorder → no drift, no extra work.
    second = await loop._do_work()
    assert second["status"] == "clean", second
    assert second["adapters_drifted"] == 0
    assert len(fake_pr.calls) == 1, "clean tick must not fire a second PR"
    assert len(replay_calls) == 1, "clean tick must not fire a second replay gate"
