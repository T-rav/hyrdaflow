"""Unit tests for src/contract_refresh_loop.py (§4.2 Phase 2).

Covers the Task 11/12 skeleton surface plus the Task 15/16 PR-filing +
replay-gate wiring, plus the Task 20 per-loop telemetry emission:

- construction (worker_name wired, deps stored)
- ``_get_default_interval`` reads ``config.contract_refresh_interval``
- ``_do_work`` short-circuits with ``{"status": "disabled"}`` when the
  ``enabled_cb`` kill-switch returns ``False``
- Task 15: on drift, stages cassettes + calls
  ``auto_pr.open_automated_pr_async`` with the right title/body/labels
  and records a dedup key so identical drift does not refile.
- Task 16: after the refresh PR opens, re-runs ``make trust-contracts``
  via subprocess. Replay failure → ``hydraflow-find`` + ``fake-drift``
  issue via ``PRManager.create_issue``. Replay pass → no companion issue.
- Task 20: each recorder subprocess + the replay gate emits one
  ``trace_collector.emit_loop_subprocess_trace`` call with the
  expected ``loop=contract_refresh`` / ``command`` / ``exit_code`` /
  ``duration_ms`` shape so deploy-time fleet observability catches
  slow/broken recorders without cracking open the refresh loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import contract_refresh_loop as crl_module
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from events import EventBus


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


class _FakeState:
    """Minimal in-memory stand-in for ``StateTracker`` contract-refresh surface.

    Task 18 added three mixin methods; using a real ``StateTracker``
    here would pull in the filesystem and all other mixins for tests
    that only care about a single ``dict[str, int]``.
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


def _loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: Any | None = None,
    state: Any | None = None,
    **config_overrides: object,
) -> ContractRefreshLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **config_overrides,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    pr_manager = prs if prs is not None else AsyncMock()
    state_obj = state if state is not None else _FakeState()
    return ContractRefreshLoop(
        config=cfg,
        prs=pr_manager,
        state=state_obj,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


# ---------------------------------------------------------------------------
# Skeleton tests (Tasks 11/12)
# ---------------------------------------------------------------------------


def test_loop_constructs_with_expected_worker_name(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._worker_name == "contract_refresh"


def test_default_interval_reads_from_config(tmp_path: Path) -> None:
    # Default from the ``contract_refresh_interval`` Field (weekly cadence).
    loop = _loop(tmp_path)
    assert loop._get_default_interval() == 604800


def test_default_interval_reflects_config_override(tmp_path: Path) -> None:
    loop = _loop(tmp_path, contract_refresh_interval=86400)
    assert loop._get_default_interval() == 86400


def test_do_work_short_circuits_when_kill_switch_disabled(tmp_path: Path) -> None:
    loop = _loop(tmp_path, enabled=False)
    result = asyncio.run(loop._do_work())
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# Task 15 / 16 helpers
# ---------------------------------------------------------------------------


def _stub_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``contract_recording.record_*`` to return empty cassette lists.

    Individual tests that want to simulate fresh recordings override the
    relevant ``record_*`` entry after this helper runs.
    """
    monkeypatch.setattr(crl_module, "record_github", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_docker", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_claude_stream", lambda *_a, **_k: [])


def _stub_make_trust_contracts_ok(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Stub ``asyncio.create_subprocess_exec`` for ``make trust-contracts`` ok.

    G14: the replay gate is async (asyncio.create_subprocess_exec). This
    stub returns a fake process whose ``communicate()`` resolves to
    canned bytes and whose ``returncode`` reads as 0.

    Returns a mutable list of invoked argv for assertions.
    """
    calls: list[list[str]] = []
    return _install_async_subprocess_stub(
        monkeypatch, calls, returncode=0, stdout=b"ok", stderr=b""
    )


def _stub_make_trust_contracts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[str]]:
    calls: list[list[str]] = []
    return _install_async_subprocess_stub(
        monkeypatch,
        calls,
        returncode=2,
        stdout=b"FAILED tests/trust/contracts/test_fake_git_contract.py",
        stderr=b"replay mismatch",
    )


def _install_async_subprocess_stub(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[list[str]],
    *,
    returncode: int,
    stdout: bytes,
    stderr: bytes,
) -> list[list[str]]:
    class _FakeProc:
        def __init__(self) -> None:
            self.returncode = returncode

        async def communicate(self) -> tuple[bytes, bytes]:
            return stdout, stderr

        async def wait(self) -> int:
            return returncode

        def kill(self) -> None:
            pass

    async def _fake_create_subprocess_exec(*argv: str, **_kwargs: Any) -> _FakeProc:
        calls.append(list(argv))
        return _FakeProc()

    monkeypatch.setattr(
        crl_module.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec
    )
    return calls


class _FakeAutoPR:
    """Captures ``open_automated_pr_async`` calls and returns a canned result."""

    def __init__(self, status: str = "opened") -> None:
        self.calls: list[dict[str, Any]] = []
        self.status = status

    async def __call__(self, **kwargs: Any) -> AutoPrResult:
        self.calls.append(kwargs)
        return AutoPrResult(
            status=self.status,  # type: ignore[arg-type]
            pr_url="https://github.com/x/y/pull/42"
            if self.status == "opened"
            else None,
            branch=kwargs.get("branch", ""),
        )


def _seed_recorded_cassette(tmp_dir: Path, adapter: str, slug: str) -> Path:
    """Write a stub recorded cassette under ``tmp_dir`` so diff can see it."""
    suffix = ".jsonl" if adapter == "claude" else ".yaml"
    path = tmp_dir / f"{slug}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"recorded-bytes-v2")
    return path


# ---------------------------------------------------------------------------
# Task 15: refresh PR opening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_do_work_no_drift_no_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All adapters clean → no PR, no replay gate run, no issue."""
    _stub_recording(monkeypatch)
    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    calls = _stub_make_trust_contracts_ok(monkeypatch)

    # Force detect_fleet_drift to report no drift regardless of input.
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: crl_module.FleetDriftReport(reports=[], has_drift=False),
    )

    loop = _loop(tmp_path)
    result = await loop._do_work()

    assert fake.calls == []
    assert calls == []  # replay gate not invoked when no drift
    assert isinstance(result, dict)
    assert result.get("adapters_drifted") == 0


@pytest.mark.asyncio
async def test_do_work_drift_opens_refresh_pr_and_records_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drift detected → refresh PR opened with the right title/body/labels.

    Also verifies a dedup key lands in ``contract_refresh.json`` so a
    second identical tick will short-circuit.
    """
    _stub_recording(monkeypatch)
    # Simulate that ``record_git`` produced a cassette.
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])

    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    loop = _loop(tmp_path)
    result = await loop._do_work()

    assert len(fake.calls) == 1
    kwargs = fake.calls[0]
    assert kwargs["branch"].startswith("contract-refresh/")
    assert "contract-refresh" in kwargs["pr_title"]
    assert "git" in kwargs["pr_body"]
    labels = kwargs.get("labels") or []
    assert "contract-refresh" in labels
    # At least the drifted cassette is in the file list.
    staged_names = [Path(p).name for p in kwargs["files"]]
    assert "commit.yaml" in staged_names

    # Dedup key recorded.
    dedup_path = loop._config.data_root / "dedup" / "contract_refresh.json"
    assert dedup_path.exists()
    assert dedup_path.read_text().strip() not in ("", "[]")

    assert isinstance(result, dict)
    assert result.get("adapters_drifted", 0) >= 1


@pytest.mark.asyncio
async def test_do_work_dedup_hit_skips_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Identical drift on a second tick must not open a second PR."""
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])

    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    loop = _loop(tmp_path)

    # First tick: PR filed.
    await loop._do_work()
    assert len(fake.calls) == 1

    # Second tick: dedup hit, no additional PR.
    await loop._do_work()
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Task 16: replay gate + fake-drift companion issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_do_work_replay_gate_fails_files_companion_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay fails after refresh PR → hydraflow-find + fake-drift issue."""
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])
    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    calls = _stub_make_trust_contracts_fail(monkeypatch)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=101)
    loop = _loop(tmp_path, prs=prs)
    await loop._do_work()

    # Replay gate was invoked (``make trust-contracts``).
    assert calls, "make trust-contracts should have been invoked"
    assert calls[0][:2] == ["make", "trust-contracts"]

    # Companion issue filed with the right labels.
    prs.create_issue.assert_awaited()
    kwargs = prs.create_issue.await_args.kwargs
    assert "hydraflow-find" in kwargs["labels"]
    assert "fake-drift" in kwargs["labels"]
    assert "trust-contracts" in kwargs["body"] or "replay" in kwargs["body"].lower()


@pytest.mark.asyncio
async def test_do_work_replay_gate_passes_no_companion_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay passes after refresh PR → no companion issue filed."""
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])
    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=0)
    loop = _loop(tmp_path, prs=prs)
    await loop._do_work()

    prs.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Task 20: per-loop telemetry emission
# ---------------------------------------------------------------------------


def _patch_emit_trace(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch ``trace_collector.emit_loop_subprocess_trace`` and capture calls.

    Returns a list the tests can inspect after ``_do_work`` completes.
    """
    import trace_collector  # noqa: PLC0415

    emitted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        trace_collector,
        "emit_loop_subprocess_trace",
        lambda **kwargs: emitted.append(kwargs),
    )
    return emitted


@pytest.mark.asyncio
async def test_do_work_emits_telemetry_for_each_recorder_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each recorder subprocess + the replay gate emits one trace call.

    With the happy path — all four recorders returning, drift detected,
    PR opened, replay gate green — we expect five
    ``emit_loop_subprocess_trace`` invocations: one per adapter
    recorder plus one for ``make trust-contracts``. The ``auto_pr``
    seam is mocked at the module level so its own git/gh subprocesses
    do not run (and thus emit nothing from this loop's perspective).
    """
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])

    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_ok(monkeypatch)

    emitted = _patch_emit_trace(monkeypatch)

    loop = _loop(tmp_path)
    await loop._do_work()

    # Four recorder calls + one replay gate = five traces.
    assert len(emitted) == 5, emitted

    # Every trace is tagged as the contract_refresh loop.
    assert all(e["loop"] == "contract_refresh" for e in emitted), emitted
    # Every trace carries a duration and an integer exit code.
    for entry in emitted:
        assert isinstance(entry["command"], list)
        assert isinstance(entry["exit_code"], int)
        assert isinstance(entry["duration_ms"], int)
        assert entry["duration_ms"] >= 0

    # The per-recorder traces are labeled with the adapter name so
    # deploy-time triage can filter by `command` without parsing.
    recorder_commands = [e["command"] for e in emitted[:4]]
    joined = [" ".join(c) for c in recorder_commands]
    assert any("record_github" in s for s in joined), joined
    assert any("record_git" in s for s in joined), joined
    assert any("record_docker" in s for s in joined), joined
    assert any("record_claude_stream" in s for s in joined), joined

    # The replay-gate trace is the final entry.
    replay = emitted[-1]
    assert replay["command"] == ["make", "trust-contracts"]
    assert replay["exit_code"] == 0


@pytest.mark.asyncio
async def test_replay_gate_failure_trace_carries_exit_code_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay-gate failure still emits a trace, with non-zero exit_code + stderr.

    The companion-issue code path must not swallow the trace — a loud
    stderr on a broken replay is the operator's only on-call clue.
    """
    _stub_recording(monkeypatch)
    recorded_git = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [recorded_git])
    drifted_report = crl_module.AdapterDriftReport(
        adapter="git",
        drifted_cassettes=[recorded_git],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    fleet = crl_module.FleetDriftReport(reports=[drifted_report], has_drift=True)
    monkeypatch.setattr(crl_module, "detect_fleet_drift", lambda *_a, **_k: fleet)

    fake = _FakeAutoPR()
    monkeypatch.setattr(crl_module, "open_automated_pr_async", fake)
    _stub_make_trust_contracts_fail(monkeypatch)

    emitted = _patch_emit_trace(monkeypatch)

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=101)
    loop = _loop(tmp_path, prs=prs)
    await loop._do_work()

    replay_entries = [e for e in emitted if e["command"] == ["make", "trust-contracts"]]
    assert len(replay_entries) == 1, emitted
    replay = replay_entries[0]
    assert replay["exit_code"] == 2
    assert replay["stderr_excerpt"] is not None
    assert "replay mismatch" in replay["stderr_excerpt"]


@pytest.mark.asyncio
async def test_no_trace_emission_when_kill_switch_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kill-switch short-circuits _do_work; no traces may be emitted."""
    _stub_recording(monkeypatch)
    emitted = _patch_emit_trace(monkeypatch)

    loop = _loop(tmp_path, enabled=False)
    await loop._do_work()

    assert emitted == []


# ---------------------------------------------------------------------------
# Task 18: per-adapter 3-attempt escalation tracker
# ---------------------------------------------------------------------------


def _drift_fleet_for(adapter: str, recorded: Path) -> crl_module.FleetDriftReport:
    """Build a FleetDriftReport that flags *adapter* drift on *recorded*."""
    report = crl_module.AdapterDriftReport(
        adapter=adapter,
        drifted_cassettes=[recorded],
        new_cassettes=[],
        deleted_cassettes=[],
    )
    return crl_module.FleetDriftReport(reports=[report], has_drift=True)


@pytest.mark.asyncio
async def test_drift_detection_increments_per_adapter_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each drifted-adapter tick increments its own counter.

    The counter is load-bearing for the escalation threshold — we must
    increment exactly once per adapter per drift tick, regardless of
    how many cassettes inside that adapter drifted.
    """
    _stub_recording(monkeypatch)
    rec = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [rec])
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: _drift_fleet_for("git", rec),
    )
    monkeypatch.setattr(crl_module, "open_automated_pr_async", _FakeAutoPR())
    _stub_make_trust_contracts_ok(monkeypatch)

    state = _FakeState()
    loop = _loop(tmp_path, state=state)
    await loop._do_work()

    assert state.get_contract_refresh_attempts("git") == 1
    # Other adapters unaffected.
    assert state.get_contract_refresh_attempts("github") == 0
    assert state.get_contract_refresh_attempts("docker") == 0
    assert state.get_contract_refresh_attempts("claude") == 0


@pytest.mark.asyncio
async def test_drift_free_tick_clears_adapter_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When an adapter goes drift-free, its counter resets.

    Without this, a transient hiccup that clears before the 3rd tick
    would permanently push that adapter closer to escalation on the
    next unrelated drift.
    """
    _stub_recording(monkeypatch)
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: crl_module.FleetDriftReport(reports=[], has_drift=False),
    )

    state = _FakeState()
    # Simulate prior drift that left attempts at 2 for git.
    state.inc_contract_refresh_attempts("git")
    state.inc_contract_refresh_attempts("git")
    assert state.get_contract_refresh_attempts("git") == 2

    loop = _loop(tmp_path, state=state)
    await loop._do_work()

    assert state.get_contract_refresh_attempts("git") == 0


@pytest.mark.asyncio
async def test_drift_clears_attempts_for_adapters_not_in_this_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An adapter with stale attempts that is not in this tick's drift resets.

    The reset is per-adapter, not global, so a persistent docker drift
    does not keep a git counter alive.
    """
    _stub_recording(monkeypatch)
    rec = _seed_recorded_cassette(tmp_path / "rec" / "docker", "docker", "run")
    monkeypatch.setattr(crl_module, "record_docker", lambda *_a, **_k: [rec])
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: _drift_fleet_for("docker", rec),
    )
    monkeypatch.setattr(crl_module, "open_automated_pr_async", _FakeAutoPR())
    _stub_make_trust_contracts_ok(monkeypatch)

    state = _FakeState()
    state.inc_contract_refresh_attempts("git")  # stale, not in this tick's drift
    state.inc_contract_refresh_attempts("docker")
    loop = _loop(tmp_path, state=state)
    await loop._do_work()

    # git was not in the drift report → cleared.
    assert state.get_contract_refresh_attempts("git") == 0
    # docker drifted again → incremented.
    assert state.get_contract_refresh_attempts("docker") == 2


@pytest.mark.asyncio
async def test_third_attempt_files_escalation_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3rd consecutive drift tick for one adapter → hitl-escalation issue.

    Labels: ``hitl-escalation`` + ``fake-drift-stuck`` + ``adapter-<name>``.
    The issue body names the stuck adapter so the HITL operator can jump
    straight to it.
    """
    _stub_recording(monkeypatch)
    rec = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [rec])
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: _drift_fleet_for("git", rec),
    )
    monkeypatch.setattr(crl_module, "open_automated_pr_async", _FakeAutoPR())
    _stub_make_trust_contracts_ok(monkeypatch)

    state = _FakeState()
    # Simulate 2 prior drift ticks — this will be attempt #3.
    state.inc_contract_refresh_attempts("git")
    state.inc_contract_refresh_attempts("git")

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=555)
    loop = _loop(tmp_path, prs=prs, state=state)

    await loop._do_work()

    # The escalation issue was filed.
    assert prs.create_issue.await_count >= 1
    # Find the hitl-escalation call (there may be another for fake-drift).
    escalation_calls = [
        call
        for call in prs.create_issue.await_args_list
        if "hitl-escalation" in (call.kwargs.get("labels") or [])
    ]
    assert len(escalation_calls) == 1, prs.create_issue.await_args_list
    kwargs = escalation_calls[0].kwargs
    assert "fake-drift-stuck" in kwargs["labels"]
    assert "adapter-git" in kwargs["labels"]
    assert "git" in kwargs["title"].lower() or "git" in kwargs["body"].lower()


@pytest.mark.asyncio
async def test_escalation_is_deduped_across_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same stuck adapter on a 4th tick → no second escalation issue.

    The dedup store keyed on adapter name prevents refiling once the
    HITL issue is already open.
    """
    _stub_recording(monkeypatch)
    rec = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [rec])
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: _drift_fleet_for("git", rec),
    )
    monkeypatch.setattr(crl_module, "open_automated_pr_async", _FakeAutoPR())
    _stub_make_trust_contracts_ok(monkeypatch)

    state = _FakeState()
    state.inc_contract_refresh_attempts("git")
    state.inc_contract_refresh_attempts("git")

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=555)
    loop = _loop(tmp_path, prs=prs, state=state)

    # Tick 3: escalation filed.
    await loop._do_work()
    first_escalations = [
        c
        for c in prs.create_issue.await_args_list
        if "hitl-escalation" in (c.kwargs.get("labels") or [])
    ]
    assert len(first_escalations) == 1

    # Tick 4: same adapter still stuck → dedup hit → no new escalation.
    await loop._do_work()
    all_escalations = [
        c
        for c in prs.create_issue.await_args_list
        if "hitl-escalation" in (c.kwargs.get("labels") or [])
    ]
    assert len(all_escalations) == 1, all_escalations


@pytest.mark.asyncio
async def test_escalation_resets_after_clean_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean tick → attempts cleared → escalation dedup also cleared.

    After a human fixes the drift and the adapter goes clean, a fresh
    drift some weeks later must file a NEW escalation — not silently
    suppress it because of a dedup entry from the last stuck run.
    """
    _stub_recording(monkeypatch)
    rec = _seed_recorded_cassette(tmp_path / "rec" / "git", "git", "commit")
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [rec])
    monkeypatch.setattr(crl_module, "open_automated_pr_async", _FakeAutoPR())
    _stub_make_trust_contracts_ok(monkeypatch)

    state = _FakeState()
    state.inc_contract_refresh_attempts("git")
    state.inc_contract_refresh_attempts("git")

    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=555)
    loop = _loop(tmp_path, prs=prs, state=state)

    # Tick 3: drift + escalation.
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: _drift_fleet_for("git", rec),
    )
    await loop._do_work()
    assert state.get_contract_refresh_attempts("git") == 3

    # Tick 4: clean — attempts cleared AND escalation dedup cleared.
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: crl_module.FleetDriftReport(reports=[], has_drift=False),
    )
    await loop._do_work()
    assert state.get_contract_refresh_attempts("git") == 0

    # Tick 5: drift returns — pre-seed attempts to 2 so this tick is #3
    # and verify a NEW escalation fires (dedup was cleared on clean tick).
    state.inc_contract_refresh_attempts("git")
    state.inc_contract_refresh_attempts("git")
    monkeypatch.setattr(
        crl_module,
        "detect_fleet_drift",
        lambda *_a, **_k: _drift_fleet_for("git", rec),
    )
    pre_count = len(
        [
            c
            for c in prs.create_issue.await_args_list
            if "hitl-escalation" in (c.kwargs.get("labels") or [])
        ]
    )
    await loop._do_work()
    post_count = len(
        [
            c
            for c in prs.create_issue.await_args_list
            if "hitl-escalation" in (c.kwargs.get("labels") or [])
        ]
    )
    assert post_count == pre_count + 1, (
        "Escalation should re-fire after an adapter goes clean then drifts again"
    )
