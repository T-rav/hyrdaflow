"""FakeSubprocessRunner — satisfies SubprocessRunner by driving FakeDocker.

Serializes FakeDocker event dicts to NDJSON on a duck-typed
``asyncio.subprocess.Process`` object so real ``stream_claude_process``
(``src/runner_utils.py``) consumes them without any production code change.

The fake Process exposes: stdout/stderr (StreamReader), stdin (None),
pid (None), returncode, async wait(), kill(), terminate(). pid is None so
``terminate_processes`` in ``runner_utils`` skips ``killpg`` (no real process
group exists for a fake process).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from execution import SimpleResult
from tests.scenarios.fakes.fake_docker import FakeDocker


class _FakeProcess:
    """Duck-typed ``asyncio.subprocess.Process`` for scenario tests."""

    def __init__(self, event_source: AsyncIterator[dict[str, Any]]) -> None:
        self._event_source = event_source
        self.stdout: asyncio.StreamReader = asyncio.StreamReader()
        self.stderr: asyncio.StreamReader = asyncio.StreamReader()
        self.stderr.feed_eof()
        self.stdin: asyncio.StreamWriter | None = None
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
        _ = (cwd, timeout, input)
        event_iter = await self._docker.run_agent(command=list(cmd), env=env)
        lines: list[str] = []
        returncode = 1
        async for event in event_iter:
            lines.append(json.dumps(event))
            if event.get("type") == "result":
                returncode = int(event.get("exit_code", 1))
        return SimpleResult(
            stdout="\n".join(lines),
            stderr="",
            returncode=returncode,
        )

    async def cleanup(self) -> None:
        return
