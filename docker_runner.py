"""Docker-based subprocess runner for Hydra agent execution.

Executes agent commands inside Docker containers with volume mounting,
environment isolation, and stream handling. Implements the
:class:`SubprocessRunner` protocol from :mod:`execution`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from execution import HostRunner, SimpleResult, get_default_runner

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.docker_runner")

# Docker multiplexed stream constants.
# When tty=False, Docker uses an 8-byte header per frame:
#   [stream_type: 1 byte][padding: 3 bytes][payload_size: 4 bytes big-endian]
# stream_type: 0=stdin, 1=stdout, 2=stderr
_HEADER_SIZE = 8
_STDOUT_STREAM = 1
_STDERR_STREAM = 2


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

    # Writable tmpfs for /tmp (container-internal mount, not a host path)
    kwargs["tmpfs"] = {"/tmp": f"size={config.docker_tmp_size}"}  # nosec B108

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

    def __init__(self, socket: Any) -> None:
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
        self._closed = True


class DockerStdoutReader:
    """Async iterator that demultiplexes a Docker attach stream.

    Docker non-TTY attach sockets use a multiplexed format with 8-byte
    headers per frame.  This reader parses those headers, extracts only
    stdout payloads for line iteration, and collects stderr payloads
    separately.

    Compatible with the ``async for raw in stdout_stream:`` pattern
    used in :func:`stream_claude_process`.
    """

    def __init__(self, socket: Any, loop: asyncio.AbstractEventLoop) -> None:
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
        container: Any,
        socket: Any,
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
        with contextlib.suppress(Exception):
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

    def _build_mounts(self, cwd: str | None) -> dict[str, dict[str, str]]:
        """Build Docker volume mount specification."""
        mounts: dict[str, dict[str, str]] = {}
        if cwd:
            mounts[cwd] = {"bind": "/workspace", "mode": "rw"}
        mounts[str(self._repo_root)] = {"bind": "/repo", "mode": "ro"}
        self._log_dir.mkdir(parents=True, exist_ok=True)
        mounts[str(self._log_dir)] = {"bind": "/logs", "mode": "rw"}
        for spec in self._extra_mounts:
            parts = spec.split(":")
            if len(parts) >= 2:
                mode = parts[2] if len(parts) > 2 else "ro"
                mounts[parts[0]] = {"bind": parts[1], "mode": mode}
        return mounts

    def _build_env(self) -> dict[str, str]:
        """Build minimal environment for the container."""
        from subprocess_util import make_docker_env  # noqa: PLC0415

        return make_docker_env(
            gh_token=self._gh_token,
            git_user_name=self._git_user_name,
            git_user_email=self._git_user_email,
        )

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
        cmd: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,  # noqa: ARG002
        stdin: int | None = None,  # noqa: ARG002
        stdout: int | None = None,  # noqa: ARG002
        stderr: int | None = None,  # noqa: ARG002
        limit: int = 1024 * 1024,  # noqa: ARG002
        start_new_session: bool = True,  # noqa: ARG002
    ) -> DockerProcess:
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

        loop = asyncio.get_running_loop()
        mounts = self._build_mounts(cwd)
        container_env = self._build_env()
        working_dir = "/workspace" if cwd else None

        container_kwargs: dict[str, Any] = {
            "image": self._image,
            "command": cmd,
            "environment": container_env,
            "volumes": mounts,
            "stdin_open": True,
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
            socket = await loop.run_in_executor(
                None,
                lambda: container.attach_socket(
                    params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1}
                ),
            )
            return DockerProcess(container, socket, loop)
        except Exception:
            with contextlib.suppress(Exception):
                await loop.run_in_executor(None, lambda: container.remove(force=True))
            self._containers.discard(container)
            raise

    async def run_simple(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,  # noqa: ARG002
        timeout: float = 120.0,
    ) -> SimpleResult:
        """Run a command in a Docker container and return the result.

        .. note::
            The ``env`` parameter is intentionally ignored — see
            :meth:`create_streaming_process` for the rationale.
        """
        await self._enforce_spawn_delay()

        loop = asyncio.get_running_loop()
        mounts = self._build_mounts(cwd)
        container_env = self._build_env()
        working_dir = "/workspace" if cwd else None

        container_kwargs: dict[str, Any] = {
            "image": self._image,
            "command": cmd,
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
        return False


def get_docker_runner(config: HydraFlowConfig) -> DockerRunner | HostRunner:
    """Factory: returns DockerRunner if Docker is available, else HostRunner.

    Falls back to host runner with a warning if:
    - ``docker_enabled`` is False
    - ``docker_image`` is not configured
    - Docker daemon is not available
    """
    if not config.docker_enabled:
        return get_default_runner()

    if not config.docker_image:
        logger.warning(
            "docker_enabled=True but no docker_image configured; "
            "falling back to host runner"
        )
        return get_default_runner()

    if not _check_docker_available():
        logger.warning("Docker daemon not available; falling back to host runner")
        return get_default_runner()

    log_dir = config.repo_root / ".hydraflow" / "logs"
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
