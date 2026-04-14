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

        Each yielded event is a dict with keys like ``type`` (``"tool_use"`` |
        ``"message"`` | ``"result"``) and payload data. The final event has
        ``type == "result"`` with ``success: bool`` and ``exit_code: int``.
        """
        ...
