"""Simple TCP supervisor for hf CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import supervisor_state
from .config import DEFAULT_SUPERVISOR_PORT, STATE_DIR, SUPERVISOR_PORT_FILE


class RepoProcess:
    def __init__(
        self, slug: str, proc: subprocess.Popen[str], port: int, repo_path: Path
    ) -> None:
        self.slug = slug
        self.proc = proc
        self.port = port
        self.repo_path = repo_path


RUNNERS: dict[str, RepoProcess] = {}


def _slug_for_log_filename(slug: str) -> str:
    cleaned = slug.strip().replace("/", "-").replace("\\", "-")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned)
    cleaned = cleaned.strip("-").lstrip(".")
    return cleaned or "repo"


def _repo_log_file(slug: str, port: int) -> Path:
    log_dir = STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = _slug_for_log_filename(slug)
    return (log_dir / f"{safe_slug}-{port}.log").resolve()


def _is_repo_running(slug: str) -> bool:
    proc = RUNNERS.get(slug)
    return proc is not None and proc.proc.poll() is None


def _is_repo_running_for_repo(repo: dict[str, Any]) -> bool:
    """Return runtime status for a persisted repo entry.

    Prefer path matching so duplicate slugs across worktrees don't all appear
    as running when only one path-backed process is active.
    """
    path = str(repo.get("path") or "").strip()
    if path:
        with suppress(OSError, RuntimeError):
            normalized = str(Path(path).resolve())
            for proc in RUNNERS.values():
                if proc.proc.poll() is not None:
                    continue
                if str(proc.repo_path.resolve()) == normalized:
                    return True
    return _is_repo_running(str(repo.get("slug", "")))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _slug_for_repo(path: Path) -> str:
    slug = path.name.replace(" ", "-")
    return slug or "repo"


def _start_repo(path: str, *, slug: str | None = None) -> tuple[int, str, str, str]:
    repo_path = Path(path)
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo path not found: {path}")
    slug = slug or _slug_for_repo(repo_path)
    existing = RUNNERS.get(slug)
    if existing and existing.proc.poll() is None:
        log_file = _repo_log_file(existing.slug, existing.port)
        return (
            existing.port,
            existing.slug,
            str(existing.repo_path.resolve()),
            str(log_file),
        )
    state_root = STATE_DIR / slug
    state_root.mkdir(parents=True, exist_ok=True)
    port = _find_free_port()
    log_file = _repo_log_file(slug, port)
    env = os.environ.copy()
    env.setdefault("HYDRAFLOW_HOME", str(state_root))
    src_path = str((repo_path / "src").resolve())
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else src_path
    )
    env.setdefault("HF_SUPERVISOR_PORT_FILE", str(SUPERVISOR_PORT_FILE))
    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            str(repo_path / "src" / "cli.py"),
            "--dashboard-port",
            str(port),
        ],
        cwd=str(repo_path),
        stdout=log_file.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
        text=True,
    )
    RUNNERS[slug] = RepoProcess(slug, proc, port, repo_path)
    try:
        _wait_for_port(port, proc, log_file)
    except Exception:
        RUNNERS.pop(slug, None)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise
    return port, slug, str(repo_path.resolve()), str(log_file)


def _stop_repo(path: str | None = None, *, slug: str | None = None) -> bool:
    target_slug = slug
    if target_slug is None and path is not None:
        target_slug = _slug_for_repo(Path(path))
    if not target_slug:
        return False
    proc = RUNNERS.pop(target_slug, None)
    if proc is None:
        return False
    proc.proc.terminate()
    try:
        proc.proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.proc.kill()
    return True


def _wait_for_port(
    port: int, proc: subprocess.Popen[str], log_file: Path, timeout: float = 20.0
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError as exc:
                time.sleep(0.2)
                if proc.poll() is not None:
                    code = proc.returncode
                    raise RuntimeError(
                        f"Repo process exited with code {code}; see {log_file}"
                    ) from exc
    raise RuntimeError(
        f"Timed out waiting for repo dashboard on port {port}; see {log_file}"
    )


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw = await reader.readline()
        if not raw:
            return
        request = json.loads(raw.decode())
        action = request.get("action")
        if action == "ping":
            response = {"status": "ok"}
        elif action == "list_repos":
            response = {"status": "ok", "repos": _build_repo_status_payload()}
        elif action == "add_repo":
            path = request.get("path")
            requested_slug = request.get("repo_slug")
            if not path:
                response = {"status": "error", "error": "Missing path"}
            else:
                existing = supervisor_state.get_repo(path=path, slug=requested_slug)
                slug_hint = requested_slug or (
                    existing.get("slug") if existing else None
                )
                started = True
                try:
                    port, slug, normalized_path, log_file = _start_repo(
                        path, slug=slug_hint
                    )
                except FileNotFoundError as exc:
                    response = {"status": "error", "error": str(exc)}
                else:
                    supervisor_state.upsert_repo(normalized_path, slug, port, log_file)
                    if (
                        existing
                        and existing.get("port") == port
                        and _is_repo_running(slug)
                    ):
                        started = False
                    response = {
                        "status": "ok",
                        "slug": slug,
                        "port": port,
                        "dashboard_url": f"http://localhost:{port}",
                        "log_file": log_file,
                        "started": started,
                    }
        elif action == "register_repo":
            path = request.get("path")
            requested_slug = request.get("repo_slug")
            if not path:
                response = {"status": "error", "error": "Missing path"}
            else:
                repo_path = Path(path)
                if not repo_path.exists():
                    response = {
                        "status": "error",
                        "error": f"Repo path not found: {path}",
                    }
                else:
                    slug = requested_slug or _slug_for_repo(repo_path)
                    normalized = str(repo_path.resolve())
                    supervisor_state.upsert_repo(normalized, slug, port=0, log_file="")
                    response = {
                        "status": "ok",
                        "slug": slug,
                        "path": normalized,
                    }
        elif action == "remove_repo":
            path = request.get("path")
            slug = request.get("slug")
            if not path and not slug:
                response = {"status": "error", "error": "Missing path or slug"}
            elif not supervisor_state.remove_repo(path=path, slug=slug):
                response = {"status": "error", "error": "Repo not found"}
            else:
                _stop_repo(path, slug=slug)
                response = {"status": "ok"}
        else:
            response = {"status": "error", "error": "unknown action"}
    except Exception as exc:  # noqa: BLE001
        response = {"status": "error", "error": str(exc)}
    writer.write((json.dumps(response) + "\n").encode())
    await writer.drain()
    writer.close()


def _build_repo_status_payload() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for repo in supervisor_state.list_repos():
        running = _is_repo_running_for_repo(repo)
        payload.append({**repo, "running": running})
    return payload


async def _serve(port: int) -> None:
    server = await asyncio.start_server(_handle, "127.0.0.1", port)
    SUPERVISOR_PORT_FILE.write_text(str(port))
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hf supervisor")
    parser.add_argument("serve", nargs="?", default="serve")
    parser.add_argument("--port", type=int, default=DEFAULT_SUPERVISOR_PORT)
    args = parser.parse_args(argv)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, loop.stop)
    try:
        loop.run_until_complete(_serve(args.port))
    finally:
        loop.close()
        if SUPERVISOR_PORT_FILE.exists():
            SUPERVISOR_PORT_FILE.unlink()


if __name__ == "__main__":
    main()
