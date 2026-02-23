"""Tests for docker_runner.py — DockerProcess, DockerRunner, and fallback factory."""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docker_runner import (
    DockerProcess,
    DockerRunner,
    DockerStderrAdapter,
    DockerStdinWriter,
    DockerStdoutReader,
    _check_docker_available,
    get_docker_runner,
)
from execution import HostRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Docker multiplexed stream type constants (match docker_runner.py)
_STDOUT_STREAM = 1
_STDERR_STREAM = 2


def _frame(stream_type: int, data: bytes) -> bytes:
    """Wrap *data* in a Docker multiplexed 8-byte-header frame."""
    return struct.pack(">BxxxI", stream_type, len(data)) + data


def _frame_stdout(data: bytes) -> bytes:
    """Wrap *data* as a Docker stdout frame."""
    return _frame(_STDOUT_STREAM, data)


def _frame_stderr(data: bytes) -> bytes:
    """Wrap *data* as a Docker stderr frame."""
    return _frame(_STDERR_STREAM, data)


class _MockSocketBuffer:
    """Simulates a real socket that returns up to *n* bytes per ``recv(n)``."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def recv(self, n: int) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def sendall(self, data: bytes) -> None:  # noqa: ARG002
        pass


def _make_mock_socket_from_frames(*frames: bytes) -> MagicMock:
    """Build a mock Docker attach socket backed by concatenated *frames*."""
    raw = b"".join(frames)
    buf = _MockSocketBuffer(raw)
    sock = MagicMock()
    sock._sock = buf
    return sock


def _make_mock_socket(data: bytes = b"") -> MagicMock:
    """Build a mock Docker attach socket with framed stdout data.

    Wraps *data* in a single Docker stdout frame so the demultiplexer
    can parse it correctly.
    """
    if data:
        return _make_mock_socket_from_frames(_frame_stdout(data))
    # Empty stream — just return empty on recv
    buf = _MockSocketBuffer(b"")
    sock = MagicMock()
    sock._sock = buf
    return sock


def _make_mock_container(
    exit_code: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    """Build a mock Docker container object."""
    container = MagicMock()
    container.wait.return_value = {"StatusCode": exit_code}
    container.logs.return_value = stdout
    container.kill.return_value = None
    container.start.return_value = None
    container.remove.return_value = None
    return container


def _make_mock_docker_client(
    container: MagicMock | None = None,
    socket: MagicMock | None = None,
) -> MagicMock:
    """Build a mock docker.DockerClient."""
    client = MagicMock()
    mock_container = container or _make_mock_container()
    mock_socket = socket or _make_mock_socket()

    client.containers.create.return_value = mock_container
    mock_container.attach_socket.return_value = mock_socket
    client.ping.return_value = True
    return client


# ---------------------------------------------------------------------------
# DockerStdinWriter tests
# ---------------------------------------------------------------------------


class TestDockerStdinWriter:
    """Tests for the DockerStdinWriter wrapper."""

    def test_write_delegates_to_socket(self) -> None:
        sock = MagicMock()
        sock._sock = MagicMock()
        sock._sock.sendall = MagicMock()
        writer = DockerStdinWriter(sock)
        writer.write(b"hello")
        sock._sock.sendall.assert_called_once_with(b"hello")

    def test_close_prevents_further_writes(self) -> None:
        sock = MagicMock()
        sock._sock = MagicMock()
        sock._sock.sendall = MagicMock()
        writer = DockerStdinWriter(sock)
        writer.close()
        writer.write(b"should not send")
        sock._sock.sendall.assert_not_called()

    @pytest.mark.asyncio
    async def test_drain_is_noop(self) -> None:
        sock = _make_mock_socket()
        writer = DockerStdinWriter(sock)
        await writer.drain()  # Should not raise


# ---------------------------------------------------------------------------
# DockerStdoutReader tests — demultiplexing
# ---------------------------------------------------------------------------


class TestDockerStdoutReader:
    """Tests for the DockerStdoutReader async demultiplexing iterator."""

    @pytest.mark.asyncio
    async def test_yields_lines_from_stdout_frames(self) -> None:
        sock = _make_mock_socket(b"line1\nline2\n")
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [b"line1\n", b"line2\n"]

    @pytest.mark.asyncio
    async def test_handles_partial_lines(self) -> None:
        sock = _make_mock_socket(b"partial")
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [b"partial"]

    @pytest.mark.asyncio
    async def test_empty_stream(self) -> None:
        sock = _make_mock_socket(b"")
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == []

    @pytest.mark.asyncio
    async def test_demux_strips_8_byte_headers(self) -> None:
        """Binary frame headers must NOT appear in yielded lines."""
        payload = b'{"type":"assistant","message":{}}\n'
        sock = _make_mock_socket_from_frames(_frame_stdout(payload))
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [payload]
        # Verify no binary header bytes leaked through
        for line in lines:
            assert line[0:1] != b"\x01"  # Not a raw stream-type byte

    @pytest.mark.asyncio
    async def test_demux_multiple_stdout_frames(self) -> None:
        """Multiple stdout frames are concatenated and line-split correctly."""
        sock = _make_mock_socket_from_frames(
            _frame_stdout(b"hello "),
            _frame_stdout(b"world\n"),
        )
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [b"hello world\n"]

    @pytest.mark.asyncio
    async def test_demux_interleaved_stdout_stderr(self) -> None:
        """Stderr frames are collected, not mixed into stdout lines."""
        sock = _make_mock_socket_from_frames(
            _frame_stdout(b"out1\n"),
            _frame_stderr(b"err1"),
            _frame_stdout(b"out2\n"),
            _frame_stderr(b"err2"),
        )
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [b"out1\n", b"out2\n"]
        assert reader.get_stderr() == b"err1err2"

    @pytest.mark.asyncio
    async def test_demux_only_stderr_frames(self) -> None:
        """When only stderr frames are present, no stdout lines are yielded."""
        sock = _make_mock_socket_from_frames(
            _frame_stderr(b"error output"),
        )
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == []
        assert reader.get_stderr() == b"error output"

    @pytest.mark.asyncio
    async def test_demux_realistic_stream_json(self) -> None:
        """Realistic Claude stream-json payloads survive demultiplexing intact."""
        json_line1 = b'{"type":"assistant","message":{"id":"msg_1","content":[{"type":"text","text":"hello"}]}}\n'
        json_line2 = b'{"type":"result","result":"done"}\n'
        sock = _make_mock_socket_from_frames(
            _frame_stdout(json_line1),
            _frame_stdout(json_line2),
        )
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [json_line1, json_line2]
        # Verify JSON is parseable
        import json

        for line in lines:
            json.loads(line)  # Should not raise

    @pytest.mark.asyncio
    async def test_demux_large_payload(self) -> None:
        """Payloads larger than typical recv buffer sizes are handled correctly."""
        big_payload = b"x" * 16384 + b"\n"
        sock = _make_mock_socket_from_frames(_frame_stdout(big_payload))
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [big_payload]

    @pytest.mark.asyncio
    async def test_get_stderr_empty_when_no_stderr_frames(self) -> None:
        sock = _make_mock_socket(b"stdout only\n")
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        async for _ in reader:
            pass

        assert reader.get_stderr() == b""

    @pytest.mark.asyncio
    async def test_demux_zero_length_payload_skipped(self) -> None:
        """Frames with zero-length payloads are skipped without error."""
        # Create a zero-length frame followed by a real frame
        zero_frame = struct.pack(">BxxxI", _STDOUT_STREAM, 0)
        sock = _make_mock_socket_from_frames(
            zero_frame,
            _frame_stdout(b"real data\n"),
        )
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)

        lines: list[bytes] = []
        async for line in reader:
            lines.append(line)

        assert lines == [b"real data\n"]


# ---------------------------------------------------------------------------
# DockerStderrAdapter tests
# ---------------------------------------------------------------------------


class TestDockerStderrAdapter:
    """Tests for the DockerStderrAdapter."""

    @pytest.mark.asyncio
    async def test_read_returns_collected_stderr(self) -> None:
        sock = _make_mock_socket_from_frames(
            _frame_stdout(b"out\n"),
            _frame_stderr(b"err data"),
        )
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)
        adapter = DockerStderrAdapter(reader)

        # Consume stdout to trigger demuxing
        async for _ in reader:
            pass

        result = await adapter.read()
        assert result == b"err data"

    @pytest.mark.asyncio
    async def test_read_returns_empty_when_no_stderr(self) -> None:
        sock = _make_mock_socket(b"stdout\n")
        loop = asyncio.get_running_loop()
        reader = DockerStdoutReader(sock, loop)
        adapter = DockerStderrAdapter(reader)

        async for _ in reader:
            pass

        result = await adapter.read()
        assert result == b""


# ---------------------------------------------------------------------------
# DockerProcess tests
# ---------------------------------------------------------------------------


class TestDockerProcess:
    """Tests for the DockerProcess wrapper."""

    def test_kill_calls_container_kill(self) -> None:
        container = _make_mock_container()
        sock = _make_mock_socket()
        loop = MagicMock()
        proc = DockerProcess(container, sock, loop)

        proc.kill()
        container.kill.assert_called_once()

    def test_kill_suppresses_exceptions(self) -> None:
        container = _make_mock_container()
        container.kill.side_effect = RuntimeError("already dead")
        sock = _make_mock_socket()
        loop = MagicMock()
        proc = DockerProcess(container, sock, loop)

        proc.kill()  # Should not raise

    @pytest.mark.asyncio
    async def test_wait_returns_exit_code(self) -> None:
        container = _make_mock_container(exit_code=0)
        sock = _make_mock_socket()
        loop = asyncio.get_running_loop()
        proc = DockerProcess(container, sock, loop)

        code = await proc.wait()
        assert code == 0
        assert proc.returncode == 0

    @pytest.mark.asyncio
    async def test_wait_returns_nonzero_exit_code(self) -> None:
        container = _make_mock_container(exit_code=42)
        sock = _make_mock_socket()
        loop = asyncio.get_running_loop()
        proc = DockerProcess(container, sock, loop)

        code = await proc.wait()
        assert code == 42
        assert proc.returncode == 42

    def test_pid_is_none(self) -> None:
        container = _make_mock_container()
        sock = _make_mock_socket()
        loop = MagicMock()
        proc = DockerProcess(container, sock, loop)
        assert proc.pid is None

    def test_has_stdin_stdout_stderr(self) -> None:
        container = _make_mock_container()
        sock = _make_mock_socket()
        loop = MagicMock()
        proc = DockerProcess(container, sock, loop)

        assert isinstance(proc.stdin, DockerStdinWriter)
        assert isinstance(proc.stdout, DockerStdoutReader)
        assert isinstance(proc.stderr, DockerStderrAdapter)


# ---------------------------------------------------------------------------
# DockerRunner tests
# ---------------------------------------------------------------------------


def _make_runner(
    *,
    image: str = "hydra-agent:latest",
    repo_root: Path | None = None,
    log_dir: Path | None = None,
    spawn_delay: float = 0.0,
    network: str = "",
    extra_mounts: list[str] | None = None,
    gh_token: str = "",
    git_user_name: str = "",
    git_user_email: str = "",
    mock_client: MagicMock | None = None,
) -> tuple[DockerRunner, MagicMock]:
    """Create a DockerRunner with mocked Docker client."""
    client = mock_client or _make_mock_docker_client()

    with patch("docker.from_env", return_value=client):
        runner = DockerRunner(
            image=image,
            repo_root=repo_root or Path("/tmp/test-repo"),
            log_dir=log_dir or Path("/tmp/test-logs"),
            gh_token=gh_token,
            git_user_name=git_user_name,
            git_user_email=git_user_email,
            spawn_delay=spawn_delay,
            network=network,
            extra_mounts=extra_mounts,
        )
    # Swap the real client with the mock
    runner._client = client
    return runner, client


class TestDockerRunnerCreateStreamingProcess:
    """Tests for DockerRunner.create_streaming_process."""

    @pytest.mark.asyncio
    async def test_creates_container_with_correct_volumes(self, tmp_path: Path) -> None:
        runner, client = _make_runner(
            repo_root=tmp_path / "repo",
            log_dir=tmp_path / "logs",
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.create_streaming_process(["claude", "-p"], cwd="/tmp/worktree")

        create_call = client.containers.create.call_args
        volumes = create_call.kwargs.get("volumes", {})

        assert "/tmp/worktree" in volumes
        assert volumes["/tmp/worktree"] == {"bind": "/workspace", "mode": "rw"}
        assert str(tmp_path / "repo") in volumes
        assert volumes[str(tmp_path / "repo")] == {"bind": "/repo", "mode": "ro"}
        assert str(tmp_path / "logs") in volumes
        assert volumes[str(tmp_path / "logs")] == {"bind": "/logs", "mode": "rw"}

    @pytest.mark.asyncio
    async def test_passes_minimal_env_vars(self, tmp_path: Path) -> None:
        runner, client = _make_runner(
            log_dir=tmp_path / "logs",
            gh_token="ghp_test",
            git_user_name="Bot",
            git_user_email="bot@test.com",
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            await runner.create_streaming_process(["claude", "-p"])

        create_call = client.containers.create.call_args
        env = create_call.kwargs.get("environment", {})
        assert env["HOME"] == "/root"
        assert env["GH_TOKEN"] == "ghp_test"
        assert env["ANTHROPIC_API_KEY"] == "sk-test"
        assert env["GIT_AUTHOR_NAME"] == "Bot"
        assert env["GIT_COMMITTER_EMAIL"] == "bot@test.com"

    @pytest.mark.asyncio
    async def test_no_host_path_or_python_vars_leaked(self, tmp_path: Path) -> None:
        runner, client = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        with patch.dict(
            "os.environ",
            {"PATH": "/usr/bin", "PYTHONPATH": "/lib", "SHELL": "/bin/zsh"},
            clear=True,
        ):
            await runner.create_streaming_process(["claude", "-p"])

        create_call = client.containers.create.call_args
        env = create_call.kwargs.get("environment", {})
        assert "PATH" not in env
        assert "PYTHONPATH" not in env
        assert "SHELL" not in env

    @pytest.mark.asyncio
    async def test_returns_docker_process_wrapper(self, tmp_path: Path) -> None:
        runner, _client = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        proc = await runner.create_streaming_process(["claude", "-p"])

        assert isinstance(proc, DockerProcess)
        assert hasattr(proc, "stdin")
        assert hasattr(proc, "stdout")
        assert hasattr(proc, "stderr")
        assert hasattr(proc, "kill")
        assert hasattr(proc, "wait")

    @pytest.mark.asyncio
    async def test_uses_configured_image(self, tmp_path: Path) -> None:
        runner, client = _make_runner(
            image="custom-image:v2", log_dir=tmp_path / "logs"
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.create_streaming_process(["echo", "hi"])

        create_call = client.containers.create.call_args
        assert create_call.kwargs.get("image") == "custom-image:v2"

    @pytest.mark.asyncio
    async def test_uses_configured_network(self, tmp_path: Path) -> None:
        runner, client = _make_runner(network="hydra-net", log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.create_streaming_process(["echo", "hi"])

        create_call = client.containers.create.call_args
        assert create_call.kwargs.get("network") == "hydra-net"

    @pytest.mark.asyncio
    async def test_no_network_when_empty(self, tmp_path: Path) -> None:
        runner, client = _make_runner(network="", log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.create_streaming_process(["echo", "hi"])

        create_call = client.containers.create.call_args
        assert "network" not in create_call.kwargs

    @pytest.mark.asyncio
    async def test_extra_mounts_applied(self, tmp_path: Path) -> None:
        runner, client = _make_runner(
            log_dir=tmp_path / "logs",
            extra_mounts=["/host/data:/container/data:rw", "/host/config:/config"],
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.create_streaming_process(["echo", "hi"])

        create_call = client.containers.create.call_args
        volumes = create_call.kwargs.get("volumes", {})
        assert volumes["/host/data"] == {"bind": "/container/data", "mode": "rw"}
        assert volumes["/host/config"] == {"bind": "/config", "mode": "ro"}

    @pytest.mark.asyncio
    async def test_sets_working_dir_when_cwd_provided(self, tmp_path: Path) -> None:
        runner, client = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.create_streaming_process(["claude", "-p"], cwd="/tmp/worktree")

        create_call = client.containers.create.call_args
        assert create_call.kwargs.get("working_dir") == "/workspace"

    @pytest.mark.asyncio
    async def test_env_param_is_ignored_for_isolation(self, tmp_path: Path) -> None:
        """DockerRunner must ignore caller-supplied env and always use _build_env().

        Production callers (stream_claude_process) pass env=make_clean_env() which
        contains the full host environment.  Accepting it would leak PATH, PYTHONPATH,
        and other host vars into the container, defeating the security boundary.
        """
        runner, client = _make_runner(
            log_dir=tmp_path / "logs",
            gh_token="ghp_secret",
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        # Simulate what runner_utils.stream_claude_process does: pass the full host env
        full_host_env = {
            "PATH": "/usr/local/bin:/usr/bin",
            "PYTHONPATH": "/home/user/lib",
            "SHELL": "/bin/zsh",
            "HOME": "/home/user",
            "GH_TOKEN": "ghp_secret",
        }
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            await runner.create_streaming_process(["claude", "-p"], env=full_host_env)

        create_call = client.containers.create.call_args
        env = create_call.kwargs.get("environment", {})

        # Host-specific vars must be stripped
        assert "PATH" not in env
        assert "PYTHONPATH" not in env
        assert "SHELL" not in env
        # Approved vars must be present
        assert env.get("GH_TOKEN") == "ghp_secret"
        assert env.get("ANTHROPIC_API_KEY") == "sk-test"
        assert env.get("HOME") == "/root"

    @pytest.mark.asyncio
    async def test_cleanup_on_start_failure(self, tmp_path: Path) -> None:
        runner, client = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        container = client.containers.create.return_value
        container.start.side_effect = RuntimeError("start failed")

        with pytest.raises(RuntimeError, match="start failed"):
            await runner.create_streaming_process(["echo", "hi"])

        container.remove.assert_called_once_with(force=True)
        assert container not in runner._containers


# ---------------------------------------------------------------------------
# DockerRunner.run_simple tests
# ---------------------------------------------------------------------------


class TestDockerRunnerRunSimple:
    """Tests for DockerRunner.run_simple."""

    @pytest.mark.asyncio
    async def test_run_simple_success(self, tmp_path: Path) -> None:
        container = _make_mock_container(exit_code=0)
        # Override logs to return different values based on call
        container.logs.side_effect = [b"hello output", b""]
        client = _make_mock_docker_client(container=container)
        runner, _ = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        result = await runner.run_simple(["echo", "hello"])

        assert result.returncode == 0
        assert result.stdout == "hello output"

    @pytest.mark.asyncio
    async def test_run_simple_nonzero_exit(self, tmp_path: Path) -> None:
        container = _make_mock_container(exit_code=1)
        container.logs.side_effect = [b"", b"error output"]
        client = _make_mock_docker_client(container=container)
        runner, _ = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        result = await runner.run_simple(["false"])

        assert result.returncode == 1

    @pytest.mark.asyncio
    async def test_container_removed_after_run_simple(self, tmp_path: Path) -> None:
        container = _make_mock_container()
        container.logs.side_effect = [b"ok", b""]
        client = _make_mock_docker_client(container=container)
        runner, _ = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.run_simple(["echo", "hi"])

        container.remove.assert_called_once_with(force=True)
        assert container not in runner._containers

    @pytest.mark.asyncio
    async def test_container_removed_on_error(self, tmp_path: Path) -> None:
        container = _make_mock_container()
        container.start.side_effect = RuntimeError("docker error")
        client = _make_mock_docker_client(container=container)
        runner, _ = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        with pytest.raises(RuntimeError, match="docker error"):
            await runner.run_simple(["echo", "hi"])

        container.remove.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_run_simple_timeout(self, tmp_path: Path) -> None:
        container = _make_mock_container()

        client = _make_mock_docker_client(container=container)
        runner, _ = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        # Use very short timeout to trigger TimeoutError from wait_for
        with (
            patch("asyncio.wait_for", side_effect=TimeoutError),
            pytest.raises(TimeoutError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=0.01)

        container.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Staggered spawning tests
# ---------------------------------------------------------------------------


class TestStaggeredSpawning:
    """Tests for staggered container spawn delay."""

    @pytest.mark.asyncio
    async def test_staggered_spawning_enforces_delay(self, tmp_path: Path) -> None:
        runner, _client = _make_runner(spawn_delay=0.1, log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        times: list[float] = []

        original_enforce = runner._enforce_spawn_delay

        async def tracking_enforce():
            await original_enforce()
            times.append(asyncio.get_running_loop().time())

        runner._enforce_spawn_delay = tracking_enforce

        # Two rapid calls
        await runner.create_streaming_process(["echo", "1"])
        await runner.create_streaming_process(["echo", "2"])

        assert len(times) == 2
        assert times[1] - times[0] >= 0.09  # Allow small tolerance

    @pytest.mark.asyncio
    async def test_spawn_delay_configurable(self, tmp_path: Path) -> None:
        runner, _client = _make_runner(spawn_delay=5.0, log_dir=tmp_path / "logs")
        assert runner._spawn_delay == 5.0

    @pytest.mark.asyncio
    async def test_zero_delay_allows_immediate_spawn(self, tmp_path: Path) -> None:
        runner, _client = _make_runner(spawn_delay=0.0, log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        # Should not delay
        with patch("asyncio.sleep") as mock_sleep:
            await runner.create_streaming_process(["echo", "1"])
            mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Container cleanup tests
# ---------------------------------------------------------------------------


class TestDockerRunnerCleanup:
    """Tests for DockerRunner.cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_all_tracked_containers(self, tmp_path: Path) -> None:
        # Use distinct container mocks so the set tracks both
        container1 = _make_mock_container()
        container2 = _make_mock_container()
        client = _make_mock_docker_client()
        client.containers.create.side_effect = [container1, container2]

        runner, _ = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        # Create two containers
        await runner.create_streaming_process(["echo", "1"])
        await runner.create_streaming_process(["echo", "2"])

        assert len(runner._containers) == 2

        await runner.cleanup()

        assert len(runner._containers) == 0
        container1.remove.assert_called_once_with(force=True)
        container2.remove.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_cleanup_suppresses_errors(self, tmp_path: Path) -> None:
        runner, client = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        container = client.containers.create.return_value
        container.remove.side_effect = RuntimeError("already removed")

        await runner.create_streaming_process(["echo", "1"])
        await runner.cleanup()  # Should not raise

        assert len(runner._containers) == 0


# ---------------------------------------------------------------------------
# Docker availability check tests
# ---------------------------------------------------------------------------


class TestCheckDockerAvailable:
    """Tests for _check_docker_available."""

    def test_returns_true_when_docker_available(self) -> None:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        with patch("docker.from_env", return_value=mock_client):
            assert _check_docker_available() is True

    def test_returns_false_when_docker_unavailable(self) -> None:
        with patch("docker.from_env", side_effect=Exception("no daemon")):
            assert _check_docker_available() is False

    def test_returns_false_when_ping_fails(self) -> None:
        mock_client = MagicMock()
        mock_client.ping.side_effect = Exception("connection refused")
        with patch("docker.from_env", return_value=mock_client):
            assert _check_docker_available() is False

    def test_returns_false_when_docker_not_installed(self) -> None:
        with patch.dict("sys.modules", {"docker": None}):
            # Force ImportError by reloading
            assert _check_docker_available() is False


# ---------------------------------------------------------------------------
# Fallback factory tests
# ---------------------------------------------------------------------------


class TestGetDockerRunner:
    """Tests for get_docker_runner factory."""

    def test_returns_host_when_disabled(self) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(docker_enabled=False)
        runner = get_docker_runner(config)
        assert isinstance(runner, HostRunner)

    def test_returns_host_when_no_image(self) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(docker_enabled=True, docker_image="")
        runner = get_docker_runner(config)
        assert isinstance(runner, HostRunner)

    def test_returns_host_when_docker_unavailable(self) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(docker_enabled=True, docker_image="hydra:latest")
        with patch("docker_runner._check_docker_available", return_value=False):
            runner = get_docker_runner(config)
        assert isinstance(runner, HostRunner)

    def test_returns_docker_runner_when_available(self) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(
            docker_enabled=True,
            docker_image="hydra:latest",
            docker_spawn_delay=3.0,
            docker_network="test-net",
        )
        mock_client = _make_mock_docker_client()
        with (
            patch("docker_runner._check_docker_available", return_value=True),
            patch("docker.from_env", return_value=mock_client),
        ):
            runner = get_docker_runner(config)
        assert isinstance(runner, DockerRunner)

    def test_logs_warning_when_no_image(self, caplog: pytest.LogCaptureFixture) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(docker_enabled=True, docker_image="")
        with caplog.at_level("WARNING"):
            get_docker_runner(config)
        assert "no docker_image configured" in caplog.text

    def test_logs_warning_when_docker_unavailable(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(docker_enabled=True, docker_image="hydra:latest")
        with (
            caplog.at_level("WARNING"),
            patch("docker_runner._check_docker_available", return_value=False),
        ):
            get_docker_runner(config)
        assert "Docker daemon not available" in caplog.text


# ---------------------------------------------------------------------------
# Volume mount construction tests
# ---------------------------------------------------------------------------


class TestBuildMounts:
    """Tests for DockerRunner._build_mounts."""

    def test_includes_workspace_when_cwd_provided(self, tmp_path: Path) -> None:
        runner, _ = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        mounts = runner._build_mounts("/tmp/worktree")

        assert "/tmp/worktree" in mounts
        assert mounts["/tmp/worktree"]["bind"] == "/workspace"
        assert mounts["/tmp/worktree"]["mode"] == "rw"

    def test_no_workspace_when_cwd_is_none(self, tmp_path: Path) -> None:
        runner, _ = _make_runner(log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        mounts = runner._build_mounts(None)

        assert not any(v["bind"] == "/workspace" for v in mounts.values())

    def test_repo_root_mounted_readonly(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        runner, _ = _make_runner(repo_root=repo, log_dir=tmp_path / "logs")
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        mounts = runner._build_mounts(None)

        assert str(repo) in mounts
        assert mounts[str(repo)]["mode"] == "ro"

    def test_log_dir_mounted_readwrite(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        runner, _ = _make_runner(log_dir=log_dir)

        mounts = runner._build_mounts(None)

        assert str(log_dir) in mounts
        assert mounts[str(log_dir)]["mode"] == "rw"

    def test_log_dir_created_if_missing(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "new" / "logs"
        runner, _ = _make_runner(log_dir=log_dir)

        runner._build_mounts(None)

        assert log_dir.exists()

    def test_extra_mounts_with_mode(self, tmp_path: Path) -> None:
        runner, _ = _make_runner(
            log_dir=tmp_path / "logs",
            extra_mounts=["/host/path:/container/path:rw"],
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        mounts = runner._build_mounts(None)

        assert "/host/path" in mounts
        assert mounts["/host/path"] == {"bind": "/container/path", "mode": "rw"}

    def test_extra_mounts_default_readonly(self, tmp_path: Path) -> None:
        runner, _ = _make_runner(
            log_dir=tmp_path / "logs",
            extra_mounts=["/host/path:/container/path"],
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        mounts = runner._build_mounts(None)

        assert mounts["/host/path"]["mode"] == "ro"

    def test_invalid_mount_spec_ignored(self, tmp_path: Path) -> None:
        runner, _ = _make_runner(
            log_dir=tmp_path / "logs",
            extra_mounts=["invalid-no-colon"],
        )
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        mounts = runner._build_mounts(None)

        assert "invalid-no-colon" not in mounts
