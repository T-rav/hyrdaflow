"""Base runner class — shared lifecycle for all agent runners."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from agent_cli import build_agent_command
from config import HydraFlowConfig
from events import EventBus
from execution import get_default_runner
from manifest import load_project_manifest
from memory import load_memory_digest
from runner_utils import stream_claude_process, terminate_processes

if TYPE_CHECKING:
    from execution import SubprocessRunner


class BaseRunner:
    """Shared base for ``AgentRunner``, ``PlannerRunner``, ``ReviewRunner``, and ``HITLRunner``.

    Provides the common ``__init__``, ``terminate``, ``_execute``,
    ``_save_transcript``, ``_inject_manifest_and_memory``, and
    ``_verify_quality`` implementations so each subclass only needs to
    implement its own prompt-building and run logic.
    """

    _log: ClassVar[logging.Logger]

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()

    def terminate(self) -> None:
        """Kill all active subprocesses."""
        terminate_processes(self._active_procs)

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        event_data: dict[str, object],
        *,
        on_output: Callable[[str], bool] | None = None,
    ) -> str:
        """Run a claude subprocess and stream its output."""
        return await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=cwd,
            active_procs=self._active_procs,
            event_bus=self._bus,
            event_data=event_data,
            logger=self._log,
            on_output=on_output,
            timeout=self._config.agent_timeout,
            runner=self._runner,
        )

    def _save_transcript(self, prefix: str, identifier: int, transcript: str) -> None:
        """Write a transcript to ``.hydraflow/logs/<prefix>-<identifier>.txt``."""
        log_dir = self._config.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{prefix}-{identifier}.txt"
            path.write_text(transcript)
            self._log.info("Transcript saved to %s", path)
        except OSError:
            self._log.warning(
                "Could not save transcript to %s",
                log_dir,
                exc_info=True,
            )

    def _inject_manifest_and_memory(self) -> tuple[str, str]:
        """Load the project manifest and memory digest.

        Returns ``(manifest_section, memory_section)`` where each is an
        empty string when the corresponding file is missing.
        """
        manifest_section = ""
        manifest = load_project_manifest(self._config)
        if manifest:
            manifest_section = f"\n\n## Project Context\n\n{manifest}"

        memory_section = ""
        digest = load_memory_digest(self._config)
        if digest:
            memory_section = f"\n\n## Accumulated Learnings\n\n{digest}"

        return manifest_section, memory_section

    def _build_command(self, _worktree_path: Path) -> list[str]:
        """Construct the default implementation CLI invocation.

        Used by runners that call the implementation tool (``agent.py`` and
        ``hitl_runner.py``).  Runners that use a different tool (planner,
        reviewer) override this method.  The ``_worktree_path`` argument is
        accepted for API compatibility with overriding runners (e.g.
        ``ReviewRunner``) that need the path to build their command.
        """
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
        )

    async def _verify_quality(self, worktree_path: Path) -> tuple[bool, str]:
        """Run ``make quality`` and return ``(success, error_output)``."""
        try:
            result = await self._runner.run_simple(
                ["make", "quality"],
                cwd=str(worktree_path),
                timeout=self._config.quality_timeout,
            )
        except FileNotFoundError:
            return False, "make not found — cannot run quality checks"
        except TimeoutError:
            return (
                False,
                f"make quality timed out after {self._config.quality_timeout}s",
            )
        if result.returncode != 0:
            output = "\n".join(filter(None, [result.stdout, result.stderr]))
            return (
                False,
                f"`make quality` failed:\n{output[-self._config.error_output_max_chars :]}",
            )
        return True, "OK"
