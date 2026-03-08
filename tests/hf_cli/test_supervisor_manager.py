from __future__ import annotations

import pytest

from hf_cli import supervisor_manager


def test_ensure_running_returns_when_ping_is_true(monkeypatch) -> None:
    monkeypatch.setattr(supervisor_manager.supervisor_client, "ping", lambda: True)

    supervisor_manager.ensure_running()


def test_ensure_running_raises_if_process_exits_early(monkeypatch) -> None:
    class _Proc:
        returncode = 7

        def poll(self):
            return self.returncode

    calls = {"n": 0}

    def _ping() -> bool:
        calls["n"] += 1
        return False

    monkeypatch.setattr(supervisor_manager.supervisor_client, "ping", _ping)
    monkeypatch.setattr(
        supervisor_manager.subprocess, "Popen", lambda *_a, **_k: _Proc()
    )
    monkeypatch.setattr(supervisor_manager.time, "sleep", lambda _x: None)

    with pytest.raises(RuntimeError, match="Supervisor exited unexpectedly"):
        supervisor_manager.ensure_running()


def test_ensure_running_times_out_when_no_ping(monkeypatch) -> None:
    class _Proc:
        returncode = None

        def poll(self):
            return None

    tick = {"t": 0.0}

    def _time() -> float:
        tick["t"] += 1.0
        return tick["t"]

    monkeypatch.setattr(supervisor_manager.supervisor_client, "ping", lambda: False)
    monkeypatch.setattr(
        supervisor_manager.subprocess, "Popen", lambda *_a, **_k: _Proc()
    )
    monkeypatch.setattr(supervisor_manager.time, "time", _time)
    monkeypatch.setattr(supervisor_manager.time, "sleep", lambda _x: None)

    with pytest.raises(RuntimeError, match="Timed out waiting for supervisor"):
        supervisor_manager.ensure_running()


def test_ensure_running_starts_and_waits_until_ping_succeeds(monkeypatch) -> None:
    class _Proc:
        returncode = None

        def poll(self):
            return None

    calls = {"ping": 0, "sleep": 0}

    def _ping() -> bool:
        calls["ping"] += 1
        return calls["ping"] >= 3

    monkeypatch.setattr(supervisor_manager.supervisor_client, "ping", _ping)
    monkeypatch.setattr(
        supervisor_manager.subprocess, "Popen", lambda *_a, **_k: _Proc()
    )
    monkeypatch.setattr(
        supervisor_manager.time,
        "sleep",
        lambda _x: calls.__setitem__("sleep", calls["sleep"] + 1),
    )

    supervisor_manager.ensure_running()

    assert calls["ping"] >= 3
    assert calls["sleep"] >= 1


def test_ensure_running_closes_log_file_handle(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    state_dir = tmp_path / "state"
    log_file = tmp_path / "supervisor.log"
    monkeypatch.setattr(supervisor_manager, "STATE_DIR", state_dir)
    monkeypatch.setattr(supervisor_manager, "_SUPERVISOR_LOG", log_file)

    calls = {"ping": 0}

    def _ping() -> bool:
        calls["ping"] += 1
        return calls["ping"] >= 2

    monkeypatch.setattr(supervisor_manager.supervisor_client, "ping", _ping)

    captured: dict[str, object] = {}

    class _Proc:
        returncode = None

        def poll(self):
            return None

    def _fake_popen(*_a, **kwargs):
        captured["stdout"] = kwargs["stdout"]
        return _Proc()

    monkeypatch.setattr(supervisor_manager.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(supervisor_manager.time, "sleep", lambda _x: None)

    supervisor_manager.ensure_running()

    stdout_handle = captured["stdout"]
    assert getattr(stdout_handle, "closed", False) is True
