"""FakeSubprocessRunner — satisfies SubprocessRunner by driving FakeDocker.

Serializes FakeDocker event dicts to NDJSON on a duck-typed
``asyncio.subprocess.Process`` object so real ``stream_claude_process``
(``src/runner_utils.py``) consumes them without any production code change.

The fake Process exposes: stdout/stderr (StreamReader), stdin
(_SilentStdinWriter), pid (None), returncode, async wait(), kill(),
terminate(). pid is None so ``terminate_processes`` in ``runner_utils`` skips
``killpg`` (no real process group exists for a fake process).

``run_simple`` dispatches real ``git`` commands to the host (via
``asyncio.create_subprocess_exec``) so that ``AgentRunner._count_commits`` and
``_force_commit_uncommitted`` observe the actual worktree state.  All other
commands (``make``, agent CLI) route through FakeDocker and return its scripted
default success event; scenarios that need a real ``make quality`` signal must
extend ``_HOST_COMMANDS`` or script a specific FakeDocker response.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from execution import SimpleResult
from mockworld.fakes.fake_docker import FakeDocker

# Commands that must run on the real host rather than through FakeDocker.
# Only ``git`` is listed here: AgentRunner._count_commits and _get_branch_diff
# need to observe real worktree commits written by script_run_with_commits.
# NOTE: ``make`` is NOT in this set — quality-gate checks (make quality) are
# routed through FakeDocker and use its scripted responses.  Scenarios that
# need a real ``make quality`` result must add "make" here or script a
# specific FakeDocker response via docker.script_run(...).
_HOST_COMMANDS: frozenset[str] = frozenset({"git"})


class _SilentStdinWriter:
    """Stub stdin writer — absorbs writes silently.

    Exists so production code that does ``proc.stdin.write(...)`` +
    ``proc.stdin.drain()`` + ``proc.stdin.close()`` (when ``stdin_mode`` is
    ``asyncio.subprocess.PIPE``) works without error. The written bytes are
    discarded — scenario tests drive behavior through ``FakeDocker.script_run``,
    not through prompts.
    """

    def write(self, data: bytes) -> None:
        _ = data  # intentionally discarded — scenarios assert via FakeDocker events

    async def drain(self) -> None:
        return

    def close(self) -> None:
        return


class _FakeProcess:
    """Duck-typed ``asyncio.subprocess.Process`` for scenario tests."""

    def __init__(self, event_source: AsyncIterator[dict[str, Any]]) -> None:
        self._event_source = event_source
        self.stdout: asyncio.StreamReader = asyncio.StreamReader()
        self.stderr: asyncio.StreamReader = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.stdin: _SilentStdinWriter | None = _SilentStdinWriter()
        self.pid: int | None = None
        self.returncode: int | None = None
        self._killed = False
        self._feeder_task: asyncio.Task[None] = asyncio.create_task(self._feed_stdout())

    async def _feed_stdout(self) -> None:
        try:
            async for event in self._event_source:
                if self._killed:
                    break
                self.stdout.feed_data((json.dumps(event) + "\n").encode())
                if event.get("type") == "result":
                    self.returncode = int(event.get("exit_code", 1))
        except TimeoutError as exc:
            self.stdout.set_exception(exc)
            return
        except asyncio.CancelledError:
            return
        finally:
            if self.stdout.at_eof() is False and self.stdout.exception() is None:
                self.stdout.feed_eof()
            if self.returncode is None:
                self.returncode = 1  # incomplete stream

    async def wait(self) -> int:
        with contextlib.suppress(asyncio.CancelledError):
            await self._feeder_task
        return self.returncode if self.returncode is not None else 1

    def kill(self) -> None:
        self._killed = True
        if not self._feeder_task.done():
            self._feeder_task.cancel()

    def terminate(self) -> None:
        self.kill()


class FakeSubprocessRunner:
    """SubprocessRunner backed by FakeDocker."""

    def __init__(self, docker: FakeDocker) -> None:
        self._docker = docker

    async def create_streaming_process(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        limit: int = 1024 * 1024,
        start_new_session: bool = True,
    ) -> asyncio.subprocess.Process:
        _ = (cwd, stdin, stdout, stderr, limit, start_new_session)
        event_iter = await self._docker.run_agent(
            command=list(cmd),
            env=env,
        )
        return cast(asyncio.subprocess.Process, _FakeProcess(event_iter))

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
    ) -> SimpleResult:
        # Host-side utilities (git, make) run for real so that AgentRunner's
        # commit-counting and quality-gate checks observe the actual worktree.
        if cmd and cmd[0] in _HOST_COMMANDS:
            return await self._run_on_host(
                cmd, cwd=cwd, env=env, timeout=timeout, input=input
            )

        _ = (cwd, input)

        async def _drain() -> tuple[str, int]:
            event_iter = await self._docker.run_agent(command=list(cmd), env=env)
            lines: list[str] = []
            returncode = 1
            async for event in event_iter:
                lines.append(json.dumps(event))
                if event.get("type") == "result":
                    returncode = int(event.get("exit_code", 1))
            return "\n".join(lines), returncode

        stdout, returncode = await asyncio.wait_for(_drain(), timeout=timeout)
        return SimpleResult(stdout=stdout, stderr="", returncode=returncode)

    @staticmethod
    async def _run_on_host(
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        input: bytes | None = None,  # noqa: A002
    ) -> SimpleResult:
        """Run *cmd* directly on the host via asyncio subprocess."""
        stdin_pipe = asyncio.subprocess.PIPE if input is not None else None
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdin=stdin_pipe,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=input), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return SimpleResult(
            stdout=stdout_bytes.decode(errors="replace").strip()
            if stdout_bytes
            else "",
            stderr=stderr_bytes.decode(errors="replace").strip()
            if stderr_bytes
            else "",
            returncode=proc.returncode if proc.returncode is not None else -1,
        )

    async def cleanup(self) -> None:
        return
