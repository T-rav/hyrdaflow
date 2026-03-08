"""Docker-based subprocess runner for Hydra agent execution.

Executes agent commands inside Docker containers with volume mounting,
environment isolation, and stream handling. Implements the
:class:`SubprocessRunner` protocol from :mod:`execution`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import struct
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from execution import SimpleResult, SubprocessRunner, get_default_runner

if TYPE_CHECKING:
    from config import HydraFlowConfig


class DockerSocket(Protocol):
    """Protocol for Docker attach socket objects."""

    def sendall(self, data: bytes, /) -> None: ...
    def recv(self, bufsize: int, /) -> bytes: ...


class ContainerLike(Protocol):
    """Protocol for Docker container objects."""

    def kill(self) -> None: ...
    def wait(self) -> Any: ...
    def start(self) -> None: ...
    def remove(self, *, force: bool = False) -> None: ...
    def logs(self, *, stdout: bool = True, stderr: bool = True) -> Any: ...
    def attach_socket(self, *, params: dict[str, int] | None = None) -> Any: ...


logger = logging.getLogger("hydraflow.docker_runner")

# Docker multiplexed stream constants.
# When tty=False, Docker uses an 8-byte header per frame:
#   [stream_type: 1 byte][padding: 3 bytes][payload_size: 4 bytes big-endian]
# stream_type: 0=stdin, 1=stdout, 2=stderr
_HEADER_SIZE = 8
_STDOUT_STREAM = 1
_STDERR_STREAM = 2

_CONTAINER_HOME = "/home/hydraflow"
_CONTAINER_PI_HOME = f"{_CONTAINER_HOME}/.pi"
_CONTAINER_CODEX_HOME = f"{_CONTAINER_HOME}/.codex"
_CONTAINER_CLAUDE_HOME = f"{_CONTAINER_HOME}/.claude"


def build_container_kwargs(config: HydraFlowConfig) -> dict[str, Any]:
    """Build Docker SDK kwargs for container resource limits and security.

    Returns a dict suitable for unpacking into ``client.containers.create()``
    or ``client.containers.run()``.
    """
    kwargs: dict[str, Any] = {}

    # Resource limits
    kwargs["nano_cpus"] = int(config.docker_cpu_limit * 1e9)
    kwargs["mem_limit"] = config.docker_memory_limit
    kwargs["memswap_limit"] = config.docker_memory_limit  # No swap
    kwargs["pids_limit"] = config.docker_pids_limit

    # Network
    kwargs["network_mode"] = config.docker_network_mode

    # Security
    kwargs["read_only"] = config.docker_read_only_root
    security_opt: list[str] = []
    if config.docker_no_new_privileges:
        security_opt.append("no-new-privileges:true")
    if security_opt:
        kwargs["security_opt"] = security_opt
    kwargs["cap_drop"] = ["ALL"]

    # Writable tmpfs mounts (container-internal, not host paths).
    # /tmp: general temp files.
    # /home/hydraflow: agent tools (uv, npm, etc.) need a writable HOME for
    # caches and config even when the root filesystem is read-only.
    # uid/gid=1000 matches the container's hydraflow user.
    kwargs["tmpfs"] = {
        "/tmp": f"size={config.docker_tmp_size}",  # nosec B108
        _CONTAINER_HOME: f"size={config.docker_tmp_size},uid=1000,gid=1000",
    }

    logger.info(
        "Container constraints: cpu=%.1f mem=%s pids=%d net=%s readonly=%s",
        config.docker_cpu_limit,
        config.docker_memory_limit,
        config.docker_pids_limit,
        config.docker_network_mode,
        config.docker_read_only_root,
    )

    return kwargs


class DockerStdinWriter:
    """Wraps a Docker attach socket to provide a stdin-like write interface."""

    def __init__(self, socket: DockerSocket) -> None:
        self._socket = socket
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            return
        sock = getattr(self._socket, "_sock", self._socket)
        sock.sendall(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Shut down the write side of the socket so the container
        # process receives EOF on stdin — without this, Claude CLI
        # hangs forever waiting for more input.
        import socket as _socket  # noqa: PLC0415

        sock: Any = getattr(self._socket, "_sock", self._socket)
        with contextlib.suppress(OSError):
            sock.shutdown(_socket.SHUT_WR)


class DockerStdoutReader:
    """Async iterator that demultiplexes a Docker attach stream.

    Docker non-TTY attach sockets use a multiplexed format with 8-byte
    headers per frame.  This reader parses those headers, extracts only
    stdout payloads for line iteration, and collects stderr payloads
    separately.

    Compatible with the ``async for raw in stdout_stream:`` pattern
    used in :func:`stream_claude_process`.
    """

    def __init__(self, socket: DockerSocket, loop: asyncio.AbstractEventLoop) -> None:
        self._socket = socket
        self._loop = loop
        self._buffer = b""  # Line buffer for yielding complete lines
        self._eof = False
        self._stderr_chunks: list[bytes] = []

    def __aiter__(self) -> DockerStdoutReader:
        return self

    async def __anext__(self) -> bytes:
        while True:
            if b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                return line + b"\n"
            if self._eof:
                if self._buffer:
                    remaining = self._buffer
                    self._buffer = b""
                    return remaining
                raise StopAsyncIteration

            chunk = await self._loop.run_in_executor(None, self._read_next_stdout_frame)
            if not chunk:
                self._eof = True
            else:
                self._buffer += chunk

    def _read_exact(self, n: int) -> bytes:
        """Read exactly *n* bytes from the socket, or fewer on EOF."""
        sock = getattr(self._socket, "_sock", self._socket)
        data = b""
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
            except OSError:
                break
            if not chunk:
                break
            data += chunk
        return data

    def _read_next_stdout_frame(self) -> bytes:
        """Read frames until a stdout frame is found or EOF is reached.

        Each Docker multiplexed frame starts with an 8-byte header::

            [stream_type: 1B][padding: 3B][payload_size: 4B big-endian]

        Stdout frames (type 1) are returned as payload bytes.
        Stderr frames (type 2) are collected in ``_stderr_chunks``.
        Other frame types are skipped.
        """
        while True:
            header = self._read_exact(_HEADER_SIZE)
            if len(header) < _HEADER_SIZE:
                return b""  # EOF or truncated header

            stream_type = header[0]
            payload_size = struct.unpack(">I", header[4:8])[0]

            if payload_size == 0:
                continue

            payload = self._read_exact(payload_size)
            if not payload:
                return b""  # EOF during payload read

            if stream_type == _STDOUT_STREAM:
                return payload
            if stream_type == _STDERR_STREAM:
                self._stderr_chunks.append(payload)
            # Skip other stream types (e.g. stdin=0)

    def get_stderr(self) -> bytes:
        """Return all stderr data collected during demultiplexing."""
        return b"".join(self._stderr_chunks)


class DockerStderrAdapter:
    """Provides an async ``.read()`` method that returns stderr collected by a demuxer."""

    def __init__(self, reader: DockerStdoutReader) -> None:
        self._reader = reader

    async def read(self) -> bytes:
        """Return all stderr data collected during stdout iteration."""
        return self._reader.get_stderr()


class DockerProcess:
    """Wraps a Docker container to present an ``asyncio.subprocess.Process``-like interface.

    This adapter allows :func:`stream_claude_process` to consume Docker
    container output without changes.
    """

    def __init__(
        self,
        container: ContainerLike,
        socket: DockerSocket,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._container = container
        self._socket = socket
        self._loop = loop
        stdout_reader = DockerStdoutReader(socket, loop)
        self.stdin = DockerStdinWriter(socket)
        self.stdout = stdout_reader
        self.stderr = DockerStderrAdapter(stdout_reader)
        self.returncode: int | None = None
        self.pid: int | None = None

    def kill(self) -> None:
        with contextlib.suppress(OSError, RuntimeError):
            self._container.kill()

    async def wait(self) -> int:
        result = await self._loop.run_in_executor(None, self._container.wait)
        code = int(result.get("StatusCode", 1))
        self.returncode = code
        return code


class DockerRunner:
    """Runs commands inside Docker containers with volume mounting and env isolation.

    Implements the :class:`SubprocessRunner` protocol from :mod:`execution`.
    """

    def __init__(
        self,
        *,
        image: str,
        repo_root: Path,
        log_dir: Path,
        gh_token: str = "",
        git_user_name: str = "",
        git_user_email: str = "",
        spawn_delay: float = 2.0,
        network: str = "",
        extra_mounts: list[str] | None = None,
        config: HydraFlowConfig | None = None,
    ) -> None:
        import docker  # noqa: PLC0415

        self._client = docker.from_env()
        self._image = image
        self._repo_root = repo_root
        self._log_dir = log_dir
        self._gh_token = gh_token
        self._git_user_name = git_user_name
        self._git_user_email = git_user_email
        self._spawn_delay = spawn_delay
        self._network = network
        self._extra_mounts = extra_mounts or []
        self._config = config
        self._spawn_lock = asyncio.Lock()
        self._last_spawn_time: float = 0.0
        self._containers: set[Any] = set()
        self._user_tool_mounts_cache: dict[str, dict[str, str]] | None = None
        self._user_tool_mounts_cache_key: tuple[str, str, str, str] | None = None

    async def __aenter__(self) -> DockerRunner:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.cleanup()

    def _build_mounts(self, cwd: str | None) -> dict[str, dict[str, str]]:
        """Build Docker volume mount specification."""
        mounts: dict[str, dict[str, str]] = {}
        if cwd:
            mounts[cwd] = {"bind": "/workspace", "mode": "rw"}
        # Only mount /repo separately when it differs from cwd — otherwise
        # the dict key collision overwrites the /workspace mount with /repo.
        repo_str = str(self._repo_root)
        if repo_str != cwd:
            mounts[repo_str] = {"bind": "/repo", "mode": "ro"}

        # NOTE: The host .git directory is NOT mounted.  Workspaces are
        # converted to standalone clones by prepare_workspace() before the
        # container starts, giving each container its own .git/ directory.
        # This prevents Docker containers from corrupting the host repo
        # (e.g. setting core.bare=true or core.worktree in .git/config).

        self._log_dir.mkdir(parents=True, exist_ok=True)
        mounts[str(self._log_dir)] = {"bind": "/logs", "mode": "rw"}
        mounts.update(self._get_user_tool_mounts())
        for spec in self._extra_mounts:
            parts = spec.split(":")
            if len(parts) >= 2:
                mode = parts[2] if len(parts) > 2 else "ro"
                mounts[parts[0]] = {"bind": parts[1], "mode": mode}
        return mounts

    def prepare_workspace(self, cwd: str) -> None:
        """Convert a git worktree into a standalone clone for Docker.

        Git worktrees share the parent repo's ``.git/`` directory via a
        ``.git`` *file* containing a ``gitdir:`` pointer.  Mounting the
        parent ``.git`` read-write lets containers corrupt the host config
        (e.g. setting ``core.bare=true``).

        This method replaces the worktree with a local clone so the
        container gets its own independent ``.git/`` directory.  The host
        repo is never exposed to the container.

        Idempotent — if the workspace already has a ``.git/`` directory,
        this is a no-op.
        """
        git_path = Path(cwd) / ".git"
        if git_path.is_dir():
            return  # Already a standalone repo
        if not git_path.is_file():
            return  # Not a git repo at all

        content = git_path.read_text().strip()
        if not content.startswith("gitdir:"):
            return

        # Determine the current branch
        try:
            branch: str | None = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if branch == "HEAD":
                # Detached HEAD — can't use --branch with "HEAD"
                branch = None
        except (subprocess.CalledProcessError, OSError):
            branch = None

        # Clone the repo locally, then swap .git/ into the workspace
        import shutil  # noqa: PLC0415

        clone_tmp = Path(cwd) / ".git-clone-tmp"
        try:
            clone_cmd = [
                "git",
                "clone",
                "--local",
                "--no-checkout",
            ]
            if branch:
                clone_cmd += ["--branch", branch]
            clone_cmd += [str(self._repo_root), str(clone_tmp)]
            subprocess.run(
                clone_cmd,
                check=True,
                capture_output=True,
            )
            # Replace the worktree .git file with the clone's .git directory
            git_path.unlink()
            (clone_tmp / ".git").rename(git_path)

            # Update the index to match the already-checked-out files
            subprocess.run(
                ["git", "reset", "HEAD"],
                cwd=cwd,
                check=False,
                capture_output=True,
            )
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.warning("Failed to convert worktree to standalone clone: %s", exc)
            if clone_tmp.exists():
                shutil.rmtree(clone_tmp, ignore_errors=True)
            raise
        finally:
            if clone_tmp.exists():
                shutil.rmtree(clone_tmp, ignore_errors=True)

    def _get_user_tool_mounts(self) -> dict[str, dict[str, str]]:
        """Return cached user-tool mounts, refreshing when env/home selection changes."""
        key = (
            str(Path.home()),
            os.environ.get("PI_CODING_AGENT_DIR", "").strip(),
            os.environ.get("CODEX_HOME", "").strip(),
            os.environ.get("CLAUDE_CONFIG_DIR", "").strip(),
        )
        if (
            self._user_tool_mounts_cache is None
            or key != self._user_tool_mounts_cache_key
        ):
            self._user_tool_mounts_cache = self._build_user_tool_mounts()
            self._user_tool_mounts_cache_key = key
        return dict(self._user_tool_mounts_cache)

    def _build_user_tool_mounts(self) -> dict[str, dict[str, str]]:
        """Mount host user agent settings into container when present."""
        mounts: dict[str, dict[str, str]] = {}
        home = Path.home()

        pi_dir_raw = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
        if pi_dir_raw:
            pi_dir = Path(pi_dir_raw).expanduser()
            if pi_dir.exists():
                mounts[str(pi_dir)] = {
                    "bind": f"{_CONTAINER_PI_HOME}/agent",
                    "mode": "rw",
                }
        else:
            pi_root = home / ".pi"
            if pi_root.exists():
                mounts[str(pi_root)] = {"bind": _CONTAINER_PI_HOME, "mode": "rw"}

        codex_home_raw = os.environ.get("CODEX_HOME", "").strip()
        codex_home = (
            Path(codex_home_raw).expanduser() if codex_home_raw else home / ".codex"
        )
        if codex_home.exists():
            mounts[str(codex_home)] = {"bind": _CONTAINER_CODEX_HOME, "mode": "rw"}

        claude_home_raw = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        claude_home = (
            Path(claude_home_raw).expanduser() if claude_home_raw else home / ".claude"
        )
        if claude_home.exists():
            mounts[str(claude_home)] = {"bind": _CONTAINER_CLAUDE_HOME, "mode": "rw"}

        # Claude CLI stores auth tokens in ~/.claude.json (separate from
        # the ~/.claude/ config directory).  Without this file the CLI
        # reports "Not logged in" and produces no useful output.
        claude_json = home / ".claude.json"
        if claude_json.is_file():
            mounts[str(claude_json)] = {
                "bind": f"{_CONTAINER_HOME}/.claude.json",
                "mode": "rw",
            }

        return mounts

    def _build_env(self) -> dict[str, str]:
        """Build minimal environment for the container."""
        from subprocess_util import make_docker_env  # noqa: PLC0415

        env = make_docker_env(
            gh_token=self._gh_token,
            git_user_name=self._git_user_name,
            git_user_email=self._git_user_email,
        )
        if env.get("PI_CODING_AGENT_DIR"):
            env["PI_CODING_AGENT_DIR"] = f"{_CONTAINER_PI_HOME}/agent"
        if env.get("CODEX_HOME"):
            env["CODEX_HOME"] = _CONTAINER_CODEX_HOME
        if env.get("CLAUDE_CONFIG_DIR"):
            env["CLAUDE_CONFIG_DIR"] = _CONTAINER_CLAUDE_HOME
        # Ensure temp dirs use the writable tmpfs, not the readonly root fs.
        env.setdefault("TMPDIR", "/tmp")  # nosec B108  # noqa: S108
        # HOME must point to the writable tmpfs so tools (uv, npm, git) can
        # write caches and config without fighting a read-only root fs.
        env.setdefault("HOME", _CONTAINER_HOME)
        return env

    def _get_resource_kwargs(self) -> dict[str, Any]:
        """Get resource limit and security kwargs from config, if available."""
        if self._config is not None:
            return build_container_kwargs(self._config)
        return {}

    async def _enforce_spawn_delay(self) -> None:
        """Ensure minimum delay between container starts."""
        async with self._spawn_lock:
            now = asyncio.get_running_loop().time()
            elapsed = now - self._last_spawn_time
            if elapsed < self._spawn_delay:
                await asyncio.sleep(self._spawn_delay - elapsed)
            self._last_spawn_time = asyncio.get_running_loop().time()

    async def create_streaming_process(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,  # noqa: ARG002
        stdin: int | None = None,
        stdout: int | None = None,  # noqa: ARG002
        stderr: int | None = None,  # noqa: ARG002
        limit: int = 1024 * 1024,  # noqa: ARG002
        start_new_session: bool = True,  # noqa: ARG002
    ) -> asyncio.subprocess.Process:
        """Create a streaming Docker container process.

        Mounts the worktree directory (``cwd``) as ``/workspace`` inside
        the container and returns a :class:`DockerProcess` wrapper that
        provides the same interface as ``asyncio.subprocess.Process``.

        .. note::
            The ``env`` parameter is intentionally ignored.  DockerRunner
            always builds its own minimal environment via :meth:`_build_env`
            to enforce container isolation.  Passing a full host environment
            (e.g. from :func:`subprocess_util.make_clean_env`) would leak
            ``PATH``, ``PYTHONPATH``, and other host-specific variables into
            the container, defeating the security boundary.
        """
        await self._enforce_spawn_delay()

        if cwd:
            self.prepare_workspace(cwd)

        loop = asyncio.get_running_loop()
        mounts = self._build_mounts(cwd)
        container_env = self._build_env()
        working_dir = "/workspace" if cwd else None

        needs_stdin = stdin is None or stdin == asyncio.subprocess.PIPE

        container_kwargs: dict[str, Any] = {
            "image": self._image,
            "command": list(cmd),
            "environment": container_env,
            "volumes": mounts,
            "stdin_open": needs_stdin,
            "detach": True,
        }
        if working_dir:
            container_kwargs["working_dir"] = working_dir
        if self._network:
            container_kwargs["network"] = self._network

        # Apply resource limits and security settings from config
        container_kwargs.update(self._get_resource_kwargs())

        container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.create(**container_kwargs),  # type: ignore[arg-type]
        )
        self._containers.add(container)

        try:
            await loop.run_in_executor(None, container.start)
            attach_params = {"stdout": 1, "stderr": 1, "stream": 1}
            if needs_stdin:
                attach_params["stdin"] = 1
            socket = await loop.run_in_executor(
                None,
                lambda: container.attach_socket(params=attach_params),
            )
            proc = DockerProcess(
                cast(ContainerLike, container),
                cast(DockerSocket, socket),
                loop,
            )
            return cast(asyncio.subprocess.Process, proc)
        except Exception:
            with contextlib.suppress(Exception):
                await loop.run_in_executor(None, lambda: container.remove(force=True))
            self._containers.discard(container)
            raise

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,  # noqa: ARG002
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
    ) -> SimpleResult:
        """Run a command in a Docker container and return the result.

        .. note::
            The ``env`` parameter is intentionally ignored — see
            :meth:`create_streaming_process` for the rationale.
        """
        if input is not None:
            msg = "stdin input not supported in Docker mode"
            raise NotImplementedError(msg)
        await self._enforce_spawn_delay()

        if cwd:
            self.prepare_workspace(cwd)

        loop = asyncio.get_running_loop()
        mounts = self._build_mounts(cwd)
        container_env = self._build_env()
        working_dir = "/workspace" if cwd else None

        container_kwargs: dict[str, Any] = {
            "image": self._image,
            "command": list(cmd),
            "environment": container_env,
            "volumes": mounts,
            "detach": True,
        }
        if working_dir:
            container_kwargs["working_dir"] = working_dir
        if self._network:
            container_kwargs["network"] = self._network

        # Apply resource limits and security settings from config
        container_kwargs.update(self._get_resource_kwargs())

        container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.create(**container_kwargs),
        )
        self._containers.add(container)

        try:
            await loop.run_in_executor(None, container.start)

            result = await asyncio.wait_for(
                loop.run_in_executor(None, container.wait),
                timeout=timeout,
            )

            logs_stdout = await loop.run_in_executor(
                None,
                lambda: container.logs(stdout=True, stderr=False).decode(
                    errors="replace"
                ),
            )
            logs_stderr = await loop.run_in_executor(
                None,
                lambda: container.logs(stdout=False, stderr=True).decode(
                    errors="replace"
                ),
            )

            return SimpleResult(
                stdout=logs_stdout.strip(),
                stderr=logs_stderr.strip(),
                returncode=result["StatusCode"],
            )
        except TimeoutError:
            with contextlib.suppress(Exception):
                await loop.run_in_executor(None, container.kill)
            raise
        finally:
            with contextlib.suppress(Exception):
                await loop.run_in_executor(None, lambda: container.remove(force=True))
            self._containers.discard(container)

    async def cleanup(self) -> None:
        """Remove all tracked containers."""
        loop = asyncio.get_running_loop()
        for container in list(self._containers):
            with contextlib.suppress(Exception):
                await loop.run_in_executor(
                    None, lambda c=container: c.remove(force=True)
                )
        self._containers.clear()


def _check_docker_available() -> bool:
    """Check if Docker daemon is accessible."""
    try:
        import docker  # noqa: PLC0415

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        logger.debug("Docker availability check failed", exc_info=True)
        return False


def get_docker_runner(config: HydraFlowConfig) -> SubprocessRunner:
    """Factory: returns a :class:`SubprocessRunner` for agent execution.

    Returns a ``DockerRunner`` when Docker is available and configured,
    otherwise falls back to a ``HostRunner`` with a warning if:

    - ``execution_mode`` is not ``"docker"``
    - ``docker_image`` is not configured
    - Docker daemon is not available
    """
    if config.execution_mode != "docker":
        return get_default_runner()

    if not config.docker_image:
        logger.warning(
            "execution_mode='docker' but no docker_image configured; "
            "falling back to host runner"
        )
        return get_default_runner()

    if not _check_docker_available():
        logger.warning("Docker daemon not available; falling back to host runner")
        return get_default_runner()

    log_dir = config.log_dir
    return DockerRunner(
        image=config.docker_image,
        repo_root=config.repo_root,
        log_dir=log_dir,
        gh_token=config.gh_token,
        git_user_name=config.git_user_name,
        git_user_email=config.git_user_email,
        spawn_delay=config.docker_spawn_delay,
        network=config.docker_network,
        extra_mounts=config.docker_extra_mounts,
        config=config,
    )
