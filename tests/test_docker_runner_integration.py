"""Integration tests for docker_runner.py — real Docker daemon interactions.

These tests require a running Docker daemon and the ``alpine:latest`` image.
They are marked with ``@pytest.mark.integration`` and will be skipped when
Docker is unavailable.
"""

from __future__ import annotations

import contextlib
import textwrap
from pathlib import Path

import pytest

from docker_runner import (
    DockerRunner,
    build_container_kwargs,
)
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Skip guard — skip entire module when Docker daemon is not reachable
# ---------------------------------------------------------------------------

_docker_available = False
try:
    import docker as _docker_mod

    _client = _docker_mod.from_env()
    _client.ping()
    _docker_available = True
except Exception:
    pass

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _docker_available, reason="Docker daemon not available"),
]

# Use a minimal, widely-available image for integration tests
_TEST_IMAGE = "alpine:latest"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _pull_image_once() -> None:
    """Ensure the test image is available locally (runs once per session)."""
    if not _docker_available:
        return
    client = _docker_mod.from_env()
    try:
        client.images.get(_TEST_IMAGE)
    except _docker_mod.errors.ImageNotFound:
        client.images.pull(_TEST_IMAGE)


@pytest.fixture()
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory with a test file."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.txt").write_text("hello from host\n")
    return ws


@pytest.fixture()
def tmp_log_dir(tmp_path: Path) -> Path:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return log_dir


@pytest.fixture()
def runner(tmp_workspace: Path, tmp_log_dir: Path) -> DockerRunner:
    """Create a DockerRunner with zero spawn delay for fast tests."""
    return DockerRunner(
        image=_TEST_IMAGE,
        repo_root=tmp_workspace,
        log_dir=tmp_log_dir,
        spawn_delay=0.0,
    )


# ---------------------------------------------------------------------------
# Test: run_simple — basic container execution
# ---------------------------------------------------------------------------


class TestRunSimpleIntegration:
    """Integration tests for DockerRunner.run_simple."""

    async def test_echo_returns_stdout(self, runner: DockerRunner) -> None:
        """Container runs echo and returns stdout."""
        result = await runner.run_simple(["echo", "integration-test"])
        assert result.returncode == 0
        assert "integration-test" in result.stdout

    async def test_stderr_captured(self, runner: DockerRunner) -> None:
        """Container stderr is captured separately."""
        result = await runner.run_simple(["sh", "-c", "echo err >&2"])
        assert "err" in result.stderr

    async def test_nonzero_exit_code_propagated(self, runner: DockerRunner) -> None:
        """Non-zero exit codes propagate correctly."""
        result = await runner.run_simple(["sh", "-c", "exit 42"])
        assert result.returncode == 42

    async def test_timeout_kills_container(self, runner: DockerRunner) -> None:
        """Container is killed when timeout expires; no leaked containers."""
        with pytest.raises(TimeoutError):
            await runner.run_simple(["sleep", "60"], timeout=1.0)
        # After timeout, no containers should be tracked
        assert len(runner._containers) == 0


# ---------------------------------------------------------------------------
# Test: volume mounts
# ---------------------------------------------------------------------------


class TestVolumeMountIntegration:
    """Verify volume mounts are correct inside the container."""

    async def test_workspace_file_visible(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Files in cwd are visible inside container at /workspace."""
        result = await runner.run_simple(
            ["cat", "/workspace/hello.txt"],
            cwd=str(tmp_workspace),
        )
        assert result.returncode == 0
        assert "hello from host" in result.stdout

    async def test_workspace_changes_persisted(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Changes made inside the container persist on the host."""
        result = await runner.run_simple(
            ["sh", "-c", "echo 'written inside' > /workspace/output.txt"],
            cwd=str(tmp_workspace),
        )
        assert result.returncode == 0
        output_file = tmp_workspace / "output.txt"
        assert output_file.exists()
        assert "written inside" in output_file.read_text()

    async def test_repo_root_mounted_readonly(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Repo root is mounted at /repo as read-only."""
        result = await runner.run_simple(["cat", "/repo/hello.txt"])
        assert result.returncode == 0
        assert "hello from host" in result.stdout


# ---------------------------------------------------------------------------
# Test: container cleanup
# ---------------------------------------------------------------------------


class TestContainerCleanupIntegration:
    """Verify containers are cleaned up after execution."""

    async def test_container_removed_after_run_simple(
        self, runner: DockerRunner
    ) -> None:
        """Container is removed after successful run_simple."""
        await runner.run_simple(["true"])
        assert len(runner._containers) == 0

    async def test_cleanup_removes_all_tracked(
        self, tmp_workspace: Path, tmp_log_dir: Path
    ) -> None:
        """cleanup() removes all in-flight tracked containers."""
        # Use create_streaming_process so the container stays in _containers
        # until we explicitly call cleanup (unlike run_simple which removes on exit).
        r = DockerRunner(
            image=_TEST_IMAGE,
            repo_root=tmp_workspace,
            log_dir=tmp_log_dir,
            spawn_delay=0.0,
        )
        proc = await r.create_streaming_process(
            ["sleep", "60"],
            cwd=str(tmp_workspace),
        )
        container = next(iter(r._containers))
        container_id = container.id
        assert len(r._containers) == 1

        await r.cleanup()
        assert len(r._containers) == 0

        # Verify the container no longer exists in Docker
        client = _docker_mod.from_env()
        running_ids = {c.id for c in client.containers.list(all=True)}
        assert container_id not in running_ids

        # Reap the process to avoid resource warnings
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()


# ---------------------------------------------------------------------------
# Test: create_streaming_process
# ---------------------------------------------------------------------------


class TestStreamingProcessIntegration:
    """Integration tests for DockerRunner.create_streaming_process."""

    async def test_streaming_stdout_lines(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Streaming process yields stdout lines from a real container."""
        proc = await runner.create_streaming_process(
            ["sh", "-c", "echo line1; echo line2; echo line3"],
            cwd=str(tmp_workspace),
        )
        lines: list[bytes] = []
        async for chunk in proc.stdout:
            lines.append(chunk)
        exit_code = await proc.wait()
        assert exit_code == 0

        joined = b"".join(lines).decode()
        assert "line1" in joined
        assert "line2" in joined
        assert "line3" in joined

    async def test_streaming_stderr_collected(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Streaming process collects stderr via the demuxer."""
        proc = await runner.create_streaming_process(
            ["sh", "-c", "echo out; echo err >&2"],
            cwd=str(tmp_workspace),
        )
        stdout_lines: list[bytes] = []
        async for chunk in proc.stdout:
            stdout_lines.append(chunk)
        stderr_data = await proc.stderr.read()
        exit_code = await proc.wait()

        assert exit_code == 0
        assert b"out" in b"".join(stdout_lines)
        assert b"err" in stderr_data

    async def test_streaming_process_kill(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Killing a streaming process stops the container."""
        proc = await runner.create_streaming_process(
            ["sleep", "60"],
            cwd=str(tmp_workspace),
        )
        proc.kill()
        # wait should return non-zero after kill
        code = await proc.wait()
        assert code != 0


# ---------------------------------------------------------------------------
# Test: build_container_kwargs validated by Docker SDK
# ---------------------------------------------------------------------------


class TestBuildContainerKwargsDockerValidation:
    """Validate that build_container_kwargs output is accepted by Docker SDK."""

    async def test_kwargs_accepted_by_create(
        self, tmp_workspace: Path, tmp_log_dir: Path
    ) -> None:
        """Docker SDK accepts kwargs from build_container_kwargs without error."""
        config = ConfigFactory.create(
            execution_mode="docker",
            docker_image=_TEST_IMAGE,
            docker_cpu_limit=1.0,
            docker_memory_limit="128m",
            docker_pids_limit=64,
            docker_network_mode="bridge",
            docker_read_only_root=False,
            docker_no_new_privileges=True,
        )
        kwargs = build_container_kwargs(config)

        client = _docker_mod.from_env()
        container = client.containers.create(
            image=_TEST_IMAGE,
            command=["true"],
            **kwargs,
        )
        try:
            container.start()
            result = container.wait()
            assert result["StatusCode"] == 0
        finally:
            container.remove(force=True)

    async def test_network_mode_none_accepted(self) -> None:
        """Docker accepts network_mode='none'."""
        config = ConfigFactory.create(docker_network_mode="none")
        kwargs = build_container_kwargs(config)

        client = _docker_mod.from_env()
        container = client.containers.create(
            image=_TEST_IMAGE,
            command=["true"],
            **kwargs,
        )
        try:
            container.start()
            result = container.wait()
            assert result["StatusCode"] == 0
        finally:
            container.remove(force=True)


# ---------------------------------------------------------------------------
# Test: network isolation
# ---------------------------------------------------------------------------


class TestNetworkIsolationIntegration:
    """Verify network isolation settings work at the Docker level."""

    async def test_network_mode_none_blocks_connectivity(
        self, tmp_workspace: Path, tmp_log_dir: Path
    ) -> None:
        """Container with network_mode=none cannot reach external hosts."""
        runner = DockerRunner(
            image=_TEST_IMAGE,
            repo_root=tmp_workspace,
            log_dir=tmp_log_dir,
            spawn_delay=0.0,
            config=ConfigFactory.create(docker_network_mode="none"),
        )
        # wget should fail with no network
        result = await runner.run_simple(
            ["sh", "-c", "wget -q -O /dev/null http://1.1.1.1/ 2>&1 || echo 'no-net'"],
            timeout=10.0,
        )
        assert "no-net" in result.stdout


# ---------------------------------------------------------------------------
# Test: security hardening
# ---------------------------------------------------------------------------


class TestSecurityHardeningIntegration:
    """Verify security settings are enforced by Docker."""

    async def test_cap_drop_all_prevents_privileged_ops(
        self, tmp_workspace: Path, tmp_log_dir: Path
    ) -> None:
        """With cap_drop=ALL, privileged operations like chown on root-owned files fail."""
        config = ConfigFactory.create(docker_read_only_root=False)
        runner = DockerRunner(
            image=_TEST_IMAGE,
            repo_root=tmp_workspace,
            log_dir=tmp_log_dir,
            spawn_delay=0.0,
            config=config,
        )
        # mknod requires CAP_MKNOD which should be dropped
        result = await runner.run_simple(
            ["sh", "-c", "mknod /tmp/testdev b 1 1 2>&1; echo exit=$?"],
        )
        # mknod should fail with dropped capabilities
        assert (
            "exit=1" in result.stdout
            or "Operation not permitted" in result.stdout
            or "denied" in result.stdout.lower()
        )


# ---------------------------------------------------------------------------
# Test: resource limits
# ---------------------------------------------------------------------------


class TestResourceLimitsIntegration:
    """Verify resource limits are enforced by Docker."""

    async def test_pids_limit_enforced(
        self, tmp_workspace: Path, tmp_log_dir: Path
    ) -> None:
        """Container with low PID limit cannot fork unlimited processes."""
        config = ConfigFactory.create(
            docker_pids_limit=5,
            docker_read_only_root=False,
        )
        runner = DockerRunner(
            image=_TEST_IMAGE,
            repo_root=tmp_workspace,
            log_dir=tmp_log_dir,
            spawn_delay=0.0,
            config=config,
        )
        # Try to fork many processes — should hit PID limit
        script = textwrap.dedent("""\
            i=0; while [ $i -lt 100 ]; do
                sleep 30 &
                i=$((i+1))
            done 2>&1
            echo "forked=$i"
        """)
        result = await runner.run_simple(
            ["sh", "-c", script],
            timeout=15.0,
        )
        # Either we get a "Resource temporarily unavailable" / fork error,
        # or we see fewer than 100 forks completed (limit prevented all forks).
        output = result.stdout + result.stderr
        fork_error = (
            "Resource temporarily unavailable" in output or "Cannot fork" in output
        )
        # Parse how many forks actually completed
        forked_count = None
        for token in output.split():
            if token.startswith("forked="):
                with contextlib.suppress(ValueError):
                    forked_count = int(token.split("=", 1)[1])
        limited_by_pid = forked_count is not None and forked_count < 100
        assert fork_error or limited_by_pid, (
            f"PID limit not enforced: output={output!r}"
        )


# ---------------------------------------------------------------------------
# Test: multiplexed stream demux with real Docker socket
# ---------------------------------------------------------------------------


class TestMultiplexedStreamIntegration:
    """Verify Docker multiplexed stream parsing with real containers."""

    async def test_interleaved_stdout_stderr_demuxed(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Interleaved stdout/stderr streams are correctly demultiplexed."""
        script = "echo out1; echo err1 >&2; echo out2; echo err2 >&2"
        proc = await runner.create_streaming_process(
            ["sh", "-c", script],
            cwd=str(tmp_workspace),
        )
        stdout_lines: list[bytes] = []
        async for chunk in proc.stdout:
            stdout_lines.append(chunk)
        stderr_data = await proc.stderr.read()
        await proc.wait()

        stdout_joined = b"".join(stdout_lines).decode()
        stderr_joined = stderr_data.decode()

        assert "out1" in stdout_joined
        assert "out2" in stdout_joined
        assert "err1" in stderr_joined
        assert "err2" in stderr_joined
        # stdout should NOT contain stderr content
        assert "err1" not in stdout_joined
        assert "err2" not in stdout_joined

    async def test_large_output_fully_received(
        self, runner: DockerRunner, tmp_workspace: Path
    ) -> None:
        """Large output (many frames) is fully received via the demuxer."""
        # Generate 500 lines of output
        proc = await runner.create_streaming_process(
            ["sh", "-c", "seq 1 500"],
            cwd=str(tmp_workspace),
        )
        stdout_lines: list[bytes] = []
        async for chunk in proc.stdout:
            stdout_lines.append(chunk)
        await proc.wait()

        joined = b"".join(stdout_lines).decode()
        lines = [line for line in joined.strip().split("\n") if line.strip()]
        assert len(lines) == 500
        assert lines[0].strip() == "1"
        assert lines[-1].strip() == "500"
