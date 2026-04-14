"""FakeDocker — emulates the agent-cli container streaming protocol.

Scenario tests script event sequences; `run_agent` yields them in order.
Falls back to a default success result when the script queue is empty.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class _Invocation:
    command: list[str]
    mounts: dict[str, Path] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 3600.0


class FakeDocker:
    """Scripted agent-cli container runner."""

    def __init__(self) -> None:
        self._scripts: deque[list[dict[str, Any]]] = deque()
        self.invocations: list[_Invocation] = []

    def script_run(self, events: list[dict[str, Any]]) -> None:
        """Queue the events that the NEXT run_agent call will yield."""
        self._scripts.append(list(events))

    async def run_agent(
        self,
        *,
        command: list[str],
        mounts: Mapping[str, Path] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 3600.0,
    ) -> AsyncIterator[dict[str, Any]]:
        self.invocations.append(
            _Invocation(
                command=list(command),
                mounts=dict(mounts) if mounts else {},
                env=dict(env) if env else {},
                timeout_seconds=timeout_seconds,
            )
        )
        if self._scripts:
            events = self._scripts.popleft()
        else:
            events = [{"type": "result", "success": True, "exit_code": 0}]
        return _aiter(events)


async def _aiter(events: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    for event in events:
        yield event
