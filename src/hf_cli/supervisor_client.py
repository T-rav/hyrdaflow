"""Client helpers for talking to the hf supervisor."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

from .config import DEFAULT_SUPERVISOR_PORT, SUPERVISOR_PORT_FILE


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
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as sock:
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
    if resp.get("status") == "ok":
        return list(resp.get("repos", []))
    raise RuntimeError(resp.get("error", "unknown error"))


def add_repo(path: Path, repo_slug: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": "add_repo",
        "path": str(path.resolve()),
    }
    if repo_slug:
        payload["repo_slug"] = repo_slug
    resp = _send(payload)
    if resp.get("status") != "ok":
        raise RuntimeError(resp.get("error", "unknown error"))
    return resp


def remove_repo(path: Path | None = None, slug: str | None = None) -> None:
    payload: dict[str, Any] = {"action": "remove_repo"}
    if path is not None:
        payload["path"] = str(path.resolve())
    if slug:
        payload["slug"] = slug
    resp = _send(payload)
    if resp.get("status") != "ok":
        raise RuntimeError(resp.get("error", "unknown error"))
