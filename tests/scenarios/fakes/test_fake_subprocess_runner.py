"""FakeSubprocessRunner — NDJSON adapter over FakeDocker."""

from __future__ import annotations

import json

import pytest

from execution import SubprocessRunner
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner


def test_satisfies_subprocess_runner_protocol() -> None:
    fake = FakeSubprocessRunner(FakeDocker())
    assert isinstance(fake, SubprocessRunner)


async def test_create_streaming_process_emits_ndjson_on_stdout() -> None:
    docker = FakeDocker()
    docker.script_run(
        [
            {"type": "tool_use", "name": "edit_file"},
            {"type": "message", "text": "hi"},
            {"type": "result", "success": True, "exit_code": 0},
        ]
    )
    runner = FakeSubprocessRunner(docker)

    proc = await runner.create_streaming_process(["agent"])

    assert proc.stdout is not None
    lines: list[str] = []
    async for raw in proc.stdout:
        lines.append(raw.decode().rstrip("\n"))

    decoded = [json.loads(line) for line in lines if line]
    assert [e["type"] for e in decoded] == ["tool_use", "message", "result"]

    await proc.wait()
    assert proc.returncode == 0


async def test_returncode_reflects_result_exit_code() -> None:
    docker = FakeDocker()
    docker.script_run([{"type": "result", "success": False, "exit_code": 42}])
    runner = FakeSubprocessRunner(docker)

    proc = await runner.create_streaming_process(["agent"])
    assert proc.stdout is not None
    async for _ in proc.stdout:
        pass
    await proc.wait()
    assert proc.returncode == 42


async def test_timeout_fault_raises_on_stream_read() -> None:
    docker = FakeDocker()
    docker.fail_next(kind="timeout")
    runner = FakeSubprocessRunner(docker)

    proc = await runner.create_streaming_process(["agent"])
    assert proc.stdout is not None
    with pytest.raises(TimeoutError):
        async for _ in proc.stdout:
            pass


async def test_stderr_is_empty_and_closed() -> None:
    docker = FakeDocker()
    docker.script_run([{"type": "result", "success": True, "exit_code": 0}])
    runner = FakeSubprocessRunner(docker)

    proc = await runner.create_streaming_process(["agent"])
    assert proc.stderr is not None
    stderr_bytes = await proc.stderr.read()
    assert stderr_bytes == b""


async def test_kill_is_idempotent() -> None:
    docker = FakeDocker()
    runner = FakeSubprocessRunner(docker)
    proc = await runner.create_streaming_process(["agent"])
    proc.kill()
    proc.kill()  # no raise
    await proc.wait()


async def test_run_simple_returns_stdout_as_string() -> None:
    docker = FakeDocker()
    docker.script_run([{"type": "result", "success": True, "exit_code": 0}])
    runner = FakeSubprocessRunner(docker)
    result = await runner.run_simple(["agent"])
    assert '"type": "result"' in result.stdout
    assert result.returncode == 0


async def test_cleanup_is_noop() -> None:
    runner = FakeSubprocessRunner(FakeDocker())
    await runner.cleanup()  # no raise


async def test_stdin_absorbs_writes_and_close() -> None:
    docker = FakeDocker()
    docker.script_run([{"type": "result", "success": True, "exit_code": 0}])
    runner = FakeSubprocessRunner(docker)

    proc = await runner.create_streaming_process(["agent"])
    assert proc.stdin is not None
    proc.stdin.write(b"prompt bytes")
    await proc.stdin.drain()
    proc.stdin.close()

    # Still able to consume stdout and exit normally
    assert proc.stdout is not None
    async for _ in proc.stdout:
        pass
    await proc.wait()
    assert proc.returncode == 0


async def test_run_simple_git_command_routes_to_host(tmp_path) -> None:
    """git commands bypass FakeDocker and run on the real host."""
    import subprocess

    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    runner = FakeSubprocessRunner(FakeDocker())
    result = await runner.run_simple(
        ["git", "rev-parse", "--git-dir"], cwd=str(tmp_path)
    )
    assert result.returncode == 0
    assert result.stdout == ".git"


async def test_run_simple_non_host_command_still_goes_to_docker() -> None:
    """Commands outside _HOST_COMMANDS route through FakeDocker."""
    docker = FakeDocker()
    docker.script_run([{"type": "result", "success": True, "exit_code": 7}])
    runner = FakeSubprocessRunner(docker)

    result = await runner.run_simple(["make", "quality"])
    # Routes through FakeDocker — returncode comes from scripted result event
    assert result.returncode == 7


async def test_run_simple_docker_timeout_raises() -> None:
    """A FakeDocker script that never yields a result must hit the wait_for timeout."""
    import asyncio

    class _NeverYieldingDocker:
        invocations: list = []

        async def run_agent(self, **_kwargs):  # type: ignore[no-untyped-def]
            async def _iter():
                await asyncio.sleep(10)  # never completes within timeout
                yield {"type": "result", "success": True, "exit_code": 0}

            return _iter()

    # Wrap our hanging fake in a FakeSubprocessRunner
    docker = _NeverYieldingDocker()
    runner = FakeSubprocessRunner(docker)  # type: ignore[arg-type]

    with pytest.raises(asyncio.TimeoutError):
        await runner.run_simple(["make", "quality"], timeout=0.05)
