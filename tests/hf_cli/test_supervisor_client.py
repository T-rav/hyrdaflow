from __future__ import annotations

import json

import pytest

from hf_cli import supervisor_client


class TestSupervisorResponseError:
    def test_stores_action_and_response(self) -> None:
        resp = {"status": "error", "error": "boom"}
        err = supervisor_client.SupervisorResponseError("list_repos", resp)
        assert err.action == "list_repos"
        assert err.response is resp

    def test_message_includes_action_and_error(self) -> None:
        err = supervisor_client.SupervisorResponseError(
            "add_repo", {"error": "conflict"}
        )
        assert str(err) == "add_repo failed: conflict"

    def test_missing_error_field_falls_back_to_unknown(self) -> None:
        err = supervisor_client.SupervisorResponseError("remove_repo", {})
        assert "unknown error" in str(err)

    def test_is_runtime_error_subclass(self) -> None:
        err = supervisor_client.SupervisorResponseError("ping", {"error": "x"})
        assert isinstance(err, RuntimeError)


def test_read_port_uses_default_when_file_missing(tmp_path, monkeypatch) -> None:
    missing_file = tmp_path / "missing-port-file"
    monkeypatch.setenv("HF_SUPERVISOR_PORT_FILE", str(missing_file))

    assert supervisor_client._read_port() == supervisor_client.DEFAULT_SUPERVISOR_PORT


def test_read_port_falls_back_to_default_on_invalid_file(tmp_path, monkeypatch) -> None:
    port_file = tmp_path / "port-file"
    port_file.write_text("not-a-port")
    monkeypatch.setenv("HF_SUPERVISOR_PORT_FILE", str(port_file))

    assert supervisor_client._read_port() == supervisor_client.DEFAULT_SUPERVISOR_PORT


def test_ping_returns_false_when_connection_fails(monkeypatch) -> None:
    def _raise(_request):
        raise RuntimeError("boom")

    monkeypatch.setattr(supervisor_client, "_send", _raise)
    assert supervisor_client.ping() is False


def test_list_repos_raises_supervisor_response_error_on_error_response(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        supervisor_client, "_send", lambda _request: {"status": "error", "error": "x"}
    )

    with pytest.raises(supervisor_client.SupervisorResponseError, match="x"):
        supervisor_client.list_repos()


def test_list_repos_returns_payload_on_success(monkeypatch) -> None:
    repos = [{"slug": "repo-a"}, {"slug": "repo-b"}]
    monkeypatch.setattr(
        supervisor_client, "_send", lambda _request: {"status": "ok", "repos": repos}
    )

    assert supervisor_client.list_repos() == repos


def test_add_repo_includes_slug_in_payload(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def _send(payload):
        captured.update(payload)
        return {"status": "ok", "slug": "repo-a"}

    monkeypatch.setattr(supervisor_client, "_send", _send)
    repo = tmp_path / "repo"
    repo.mkdir()

    response = supervisor_client.add_repo(repo, repo_slug="repo-a")

    assert response["slug"] == "repo-a"
    assert captured["action"] == "add_repo"
    assert captured["repo_slug"] == "repo-a"
    assert captured["path"] == str(repo.resolve())


def test_remove_repo_raises_supervisor_response_error_when_server_returns_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        supervisor_client,
        "_send",
        lambda _request: {"status": "error", "error": "not found"},
    )

    with pytest.raises(supervisor_client.SupervisorResponseError, match="not found"):
        supervisor_client.remove_repo(slug="missing")


def test_supervisor_client_errors_carry_structured_response(
    monkeypatch, tmp_path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def _add_repo_call() -> None:
        supervisor_client.add_repo(repo)

    def _register_repo_call() -> None:
        supervisor_client.register_repo(repo)

    def _remove_repo_call() -> None:
        supervisor_client.remove_repo(slug="repo")

    cases = [
        ("list_repos", supervisor_client.list_repos),
        ("add_repo", _add_repo_call),
        ("register_repo", _register_repo_call),
        ("remove_repo", _remove_repo_call),
    ]

    for action, call in cases:

        def _send(payload, *, _action=action):
            assert payload["action"] == _action
            return {"status": "error", "error": f"{_action} failure"}

        monkeypatch.setattr(supervisor_client, "_send", _send)

        with pytest.raises(supervisor_client.SupervisorResponseError) as exc_info:
            call()

        exc = exc_info.value
        assert exc.action == action
        assert exc.response["error"] == f"{action} failure"
        assert str(exc) == f"{action} failed: {action} failure"


def test_send_parses_newline_delimited_json(monkeypatch) -> None:
    timeout_applied: list[float] = []

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sendall(self, payload: bytes) -> None:
            request = json.loads(payload.decode().strip())
            assert request["action"] == "ping"

        def settimeout(self, value: float) -> None:
            timeout_applied.append(value)

        def recv(self, _size: int) -> bytes:
            return b'{"status":"ok"}\n'

    monkeypatch.setattr(supervisor_client, "_read_port", lambda: 1234)
    monkeypatch.setattr(
        supervisor_client.socket, "create_connection", lambda *_a, **_k: _FakeSocket()
    )

    assert supervisor_client._send({"action": "ping"}) == {"status": "ok"}
    assert timeout_applied[-1] == supervisor_client._DEFAULT_READ_TIMEOUT_SECONDS


def test_send_uses_extended_timeout_for_add_repo(monkeypatch) -> None:
    timeout_applied: list[float] = []

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def sendall(self, payload: bytes) -> None:
            request = json.loads(payload.decode().strip())
            assert request["action"] == "add_repo"

        def settimeout(self, value: float) -> None:
            timeout_applied.append(value)

        def recv(self, _size: int) -> bytes:
            return b'{"status":"ok"}\n'

    monkeypatch.setattr(supervisor_client, "_read_port", lambda: 1234)
    monkeypatch.setattr(
        supervisor_client.socket, "create_connection", lambda *_a, **_k: _FakeSocket()
    )

    assert supervisor_client._send({"action": "add_repo", "path": "/tmp"}) == {
        "status": "ok"
    }
    assert timeout_applied[-1] == 25.0
