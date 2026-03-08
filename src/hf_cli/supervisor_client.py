"""Client helpers for talking to the hf supervisor."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, NoReturn

from .config import DEFAULT_SUPERVISOR_PORT, SUPERVISOR_PORT_FILE

_CONNECT_TIMEOUT_SECONDS = 1.0
_DEFAULT_READ_TIMEOUT_SECONDS = 1.0
_READ_TIMEOUT_BY_ACTION_SECONDS: dict[str, float] = {
    # add_repo may block while the supervisor boots a repo dashboard process
    # and waits for the health-check port to come up.
    "add_repo": 25.0,
}


class SupervisorResponseError(RuntimeError):
    """Structured error for supervisor responses with ``status != \"ok\"``."""

    def __init__(self, action: str, response: dict[str, Any]) -> None:
        self.action = action
        self.response = response
        message = response.get("error", "unknown error")
        super().__init__(f"{action} failed: {message}" if action else message)


def _raise_response_error(action: str, response: dict[str, Any]) -> NoReturn:
    """Raise a SupervisorResponseError for a failed supervisor response."""
    raise SupervisorResponseError(action, response)


def _read_port() -> int:
    port_file_override = os.environ.get("HF_SUPERVISOR_PORT_FILE")
    port_file = (
        Path(port_file_override).expanduser()
        if port_file_override
        else SUPERVISOR_PORT_FILE
    )
    if port_file.is_file():
        try:
            return int(port_file.read_text().strip())
        except ValueError:
            pass
    return DEFAULT_SUPERVISOR_PORT


def _send(request: dict[str, Any]) -> dict[str, Any]:
    port = _read_port()
    action = str(request.get("action", ""))
    read_timeout = _READ_TIMEOUT_BY_ACTION_SECONDS.get(
        action, _DEFAULT_READ_TIMEOUT_SECONDS
    )
    try:
        with socket.create_connection(
            ("127.0.0.1", port), timeout=_CONNECT_TIMEOUT_SECONDS
        ) as sock:
            if hasattr(sock, "settimeout"):
                sock.settimeout(read_timeout)
            sock.sendall((json.dumps(request) + "\n").encode())
            data = sock.recv(65535).decode()
    except ConnectionRefusedError as exc:
        raise RuntimeError(
            "hf supervisor is not running. Run `hf run` inside a repo to start it."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Supervisor connection failed: {exc}") from exc
    return json.loads(data)


def ping() -> bool:
    try:
        resp = _send({"action": "ping"})
        return resp.get("status") == "ok"
    except (OSError, RuntimeError):
        return False


def list_repos() -> list[dict[str, Any]]:
    resp = _send({"action": "list_repos"})
    if resp.get("status") != "ok":
        _raise_response_error("list_repos", resp)
    return list(resp.get("repos", []))


def add_repo(path: Path, repo_slug: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "add_repo",
        "path": str(path.resolve()),
    }
    if repo_slug:
        payload["repo_slug"] = repo_slug
    resp = _send(payload)
    if resp.get("status") != "ok":
        _raise_response_error("add_repo", resp)
    return resp


def register_repo(path: Path, repo_slug: str | None = None) -> dict[str, Any]:
    """Register a repo without starting it (port=0)."""
    payload: dict[str, Any] = {
        "action": "register_repo",
        "path": str(path.resolve()),
    }
    if repo_slug:
        payload["repo_slug"] = repo_slug
    resp = _send(payload)
    if resp.get("status") != "ok":
        _raise_response_error("register_repo", resp)
    return resp


def remove_repo(path: Path | None = None, slug: str | None = None) -> None:
    payload: dict[str, Any] = {"action": "remove_repo"}
    if path is not None:
        payload["path"] = str(path.resolve())
    if slug:
        payload["slug"] = slug
    resp = _send(payload)
    if resp.get("status") != "ok":
        _raise_response_error("remove_repo", resp)
