"""Simple TCP supervisor for hf CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _slug_for_repo(path: Path) -> str:
    slug = path.name.replace(" ", "-")
    return slug or "repo"


def _start_repo(path: str) -> int:
    repo_path = Path(path)
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo path not found: {path}")
    slug = _slug_for_repo(repo_path)
    if slug in RUNNERS:
        return RUNNERS[slug].port
    state_root = STATE_DIR / slug
    state_root.mkdir(parents=True, exist_ok=True)
    port = _find_free_port()
    log_dir = STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{slug}-{port}.log"
    env = os.environ.copy()
    env.setdefault("HYDRAFLOW_HOME", str(state_root))
    env.setdefault("PYTHONPATH", os.getcwd())
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(repo_path / "cli.py"), "--dashboard-port", str(port)],
        cwd=str(repo_path),
        stdout=log_file.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
        text=True,
    )
    RUNNERS[slug] = RepoProcess(slug, proc, port, repo_path)
    _wait_for_port(port)
    return port


def _stop_repo(path: str) -> bool:
    slug = _slug_for_repo(Path(path))
    proc = RUNNERS.pop(slug, None)
    if proc is None:
        return False
    proc.proc.terminate()
    try:
        proc.proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.proc.kill()
    return True


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.connect(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for repo dashboard on port {port}")


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
            response = {"status": "ok", "repos": supervisor_state.list_repos()}
        elif action == "add_repo":
            path = request.get("path")
            if not path:
                response = {"status": "error", "error": "Missing path"}
            else:
                port = _start_repo(path)
                slug = _slug_for_repo(Path(path))
                log_file = str((STATE_DIR / "logs" / f"{slug}-{port}.log").resolve())
                supervisor_state.upsert_repo(path, slug, port, log_file)
                response = {
                    "status": "ok",
                    "slug": slug,
                    "port": port,
                    "dashboard_url": f"http://localhost:{port}",
                    "log_file": log_file,
                }
        elif action == "remove_repo":
            path = request.get("path")
            if not path:
                response = {"status": "error", "error": "Missing path"}
            elif not supervisor_state.remove_repo(path):
                response = {"status": "error", "error": "Repo not found"}
            else:
                _stop_repo(path)
                response = {"status": "ok"}
        else:
            response = {"status": "error", "error": "unknown action"}
    except Exception as exc:  # noqa: BLE001
        response = {"status": "error", "error": str(exc)}
    writer.write((json.dumps(response) + "\n").encode())
    await writer.drain()
    writer.close()


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
