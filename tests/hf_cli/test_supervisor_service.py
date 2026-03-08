from __future__ import annotations

from pathlib import Path

import pytest

from hf_cli import supervisor_service


def _create_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    (repo_path / "src").mkdir(parents=True)
    (repo_path / "src" / "cli.py").write_text("print('hello world')\n")
    return repo_path


def test_slug_for_repo_replaces_spaces() -> None:
    assert supervisor_service._slug_for_repo(Path("/tmp/my repo")) == "my-repo"


def test_start_repo_raises_for_missing_path() -> None:
    with pytest.raises(FileNotFoundError, match="Repo path not found"):
        supervisor_service._start_repo("/definitely/missing/path")


def test_start_repo_closes_log_file_handle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_path = _create_repo(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setattr(supervisor_service, "STATE_DIR", state_dir)
    monkeypatch.setattr(supervisor_service, "RUNNERS", {})
    monkeypatch.setattr(
        supervisor_service, "SUPERVISOR_PORT_FILE", state_dir / "port-file"
    )
    monkeypatch.setattr(supervisor_service, "_wait_for_port", lambda *_a, **_k: None)

    captured: dict[str, object] = {}

    class _Proc:
        returncode: int | None = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            return None

        def wait(self, _timeout: float) -> None:
            return None

        def kill(self) -> None:
            return None

    def _fake_popen(*_a, **kwargs):
        captured["stdout"] = kwargs["stdout"]
        return _Proc()

    monkeypatch.setattr(supervisor_service.subprocess, "Popen", _fake_popen)

    supervisor_service._start_repo(str(repo_path))

    stdout_handle = captured["stdout"]
    assert getattr(stdout_handle, "closed", False) is True


def test_start_repo_closes_log_handle_on_popen_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_path = _create_repo(tmp_path)
    state_dir = tmp_path / "state"
    monkeypatch.setattr(supervisor_service, "STATE_DIR", state_dir)
    monkeypatch.setattr(supervisor_service, "RUNNERS", {})
    monkeypatch.setattr(
        supervisor_service, "SUPERVISOR_PORT_FILE", state_dir / "port-file"
    )
    monkeypatch.setattr(supervisor_service, "_wait_for_port", lambda *_a, **_k: None)

    captured: dict[str, object] = {}

    def _boom_popen(*_a, **kwargs):
        captured["stdout"] = kwargs["stdout"]
        raise OSError("spawn failed")

    monkeypatch.setattr(supervisor_service.subprocess, "Popen", _boom_popen)

    with pytest.raises(OSError):
        supervisor_service._start_repo(str(repo_path))

    stdout_handle = captured["stdout"]
    assert getattr(stdout_handle, "closed", False) is True


def test_find_free_port_returns_positive_int() -> None:
    assert supervisor_service._find_free_port() > 0


def test_slug_for_log_filename_sanitizes_owner_repo() -> None:
    assert (
        supervisor_service._slug_for_log_filename("8thlight/insightmesh")
        == "8thlight-insightmesh"
    )


def test_repo_log_file_flattens_slug_and_creates_logs_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(supervisor_service, "STATE_DIR", tmp_path)
    log_file = supervisor_service._repo_log_file("8thlight/insightmesh", 57475)

    assert log_file == (tmp_path / "logs" / "8thlight-insightmesh-57475.log").resolve()
    assert log_file.parent.exists()


def test_build_repo_status_payload_marks_running(monkeypatch) -> None:
    monkeypatch.setattr(
        supervisor_service.supervisor_state,
        "list_repos",
        lambda: [
            {"slug": "running-repo", "path": "/tmp/r"},
            {"slug": "stopped-repo", "path": "/tmp/s"},
        ],
    )
    monkeypatch.setattr(
        supervisor_service, "_is_repo_running", lambda slug: slug == "running-repo"
    )

    payload = supervisor_service._build_repo_status_payload()

    assert payload == [
        {"slug": "running-repo", "path": "/tmp/r", "running": True},
        {"slug": "stopped-repo", "path": "/tmp/s", "running": False},
    ]


def test_stop_repo_returns_false_without_target() -> None:
    assert supervisor_service._stop_repo() is False


def test_stop_repo_terminates_and_kills_after_timeout(monkeypatch) -> None:
    class _Proc:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> None:
            raise supervisor_service.subprocess.TimeoutExpired(cmd="x", timeout=timeout)

        def kill(self) -> None:
            self.killed = True

    proc = _Proc()
    supervisor_service.RUNNERS["repo"] = supervisor_service.RepoProcess(
        "repo", proc, 9999, Path("/tmp/repo")
    )

    assert supervisor_service._stop_repo(slug="repo") is True
    assert proc.terminated is True
    assert proc.killed is True


@pytest.mark.asyncio
async def test_handle_returns_missing_path_error_for_add_repo() -> None:
    class _Reader:
        async def readline(self):
            return b'{"action":"add_repo"}\n'

    class _Writer:
        def __init__(self):
            self.buffer = b""

        def write(self, data: bytes) -> None:
            self.buffer += data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    writer = _Writer()
    await supervisor_service._handle(_Reader(), writer)

    assert b'"status": "error"' in writer.buffer
    assert b'"Missing path"' in writer.buffer


@pytest.mark.asyncio
async def test_handle_returns_unknown_action_error() -> None:
    class _Reader:
        async def readline(self):
            return b'{"action":"wat"}\n'

    class _Writer:
        def __init__(self):
            self.buffer = b""

        def write(self, data: bytes) -> None:
            self.buffer += data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    writer = _Writer()
    await supervisor_service._handle(_Reader(), writer)

    assert b'"status": "error"' in writer.buffer
    assert b'"unknown action"' in writer.buffer
