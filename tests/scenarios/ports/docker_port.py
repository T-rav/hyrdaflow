"""DockerPort — container/agent-cli runtime surface for scenario tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any, runtime_checkable

from typing_extensions import Protocol


@runtime_checkable
class DockerPort(Protocol):
    async def run_agent(
        self,
        *,
        command: list[str],
        mounts: Mapping[str, Path] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 3600.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch an agent-cli container; yield streamed JSON events.

        Each yielded event is a dict with keys like ``type`` and payload data.
        The final event normally has ``type == "result"`` with ``success: bool``
        and ``exit_code: int``.

        Standard event types yielded by production ``agent-cli``:

        - ``"tool_use"`` — tool invocation recorded in the transcript.
        - ``"message"`` — plain assistant output chunk.
        - ``"result"`` — terminal event with ``success`` and ``exit_code``.

        Scenario-test fault events (yielded by ``FakeDocker`` only, not recognized
        by production code — they are silently skipped unless followed by a
        terminal ``result`` event):

        - ``"budget_exceeded"`` (payload: ``tokens_used: int``) — scripted signal
          that the agent would have exceeded its token budget. Scenario tests
          follow this with a ``result`` having ``success=False`` to exercise the
          failure-result handling path.
        - ``"auth_retry_required"`` — emitted before a retry. Production does
          not recognize this specific type; scenarios use it to prove the stream
          processor handles unknown-type events gracefully.

        ``FakeDocker.fail_next(kind=...)`` injects single-shot failure modes
        (``"timeout"``, ``"oom"``, ``"exit_nonzero"``, ``"malformed_stream"``)
        directly at the iterator layer; those kinds do not appear as event types.
        """
        ...
