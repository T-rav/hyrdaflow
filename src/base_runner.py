"""Base runner class — shared lifecycle for all agent runners."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from agent_cli import build_agent_command
from config import HydraFlowConfig
from context_cache import ContextSectionCache
from events import EventBus
from execution import get_default_runner
from manifest import load_project_manifest
from memory import load_memory_digest
from models import TranscriptEventData
from prompt_telemetry import PromptTelemetry, parse_command_tool_model
from runner_utils import (
    AuthenticationRetryError,
    stream_claude_process,
    terminate_processes,
)

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
        self._context_cache = ContextSectionCache(config)
        self._prompt_telemetry = PromptTelemetry(config)
        self._last_context_stats: dict[str, int] = {"cache_hits": 0, "cache_misses": 0}

    def terminate(self) -> None:
        """Kill all active subprocesses."""
        terminate_processes(self._active_procs)

    _AUTH_RETRY_MAX = 3
    _AUTH_RETRY_BASE_DELAY = 5.0  # seconds

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        event_data: TranscriptEventData,
        *,
        on_output: Callable[[str], bool] | None = None,
        telemetry_stats: Mapping[str, object] | None = None,
    ) -> str:
        """Run a claude subprocess and stream its output.

        Retries up to ``_AUTH_RETRY_MAX`` times on transient authentication
        failures (OAuth token refresh blips) with exponential backoff.
        """
        start = time.monotonic()
        transcript = ""
        succeeded = False
        usage_stats: dict[str, object] = {}
        try:
            last_auth_error: AuthenticationRetryError | None = None
            for attempt in range(1, self._AUTH_RETRY_MAX + 1):
                try:
                    transcript = await stream_claude_process(
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
                        usage_stats=usage_stats,
                        gh_token=self._config.gh_token,
                    )
                    succeeded = True
                    return transcript
                except AuthenticationRetryError as exc:
                    last_auth_error = exc
                    if attempt < self._AUTH_RETRY_MAX:
                        delay = self._AUTH_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        self._log.warning(
                            "Auth failed (attempt %d/%d), retrying in %.0fs: %s",
                            attempt,
                            self._AUTH_RETRY_MAX,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        self._log.error(
                            "Auth failed after %d attempts: %s",
                            self._AUTH_RETRY_MAX,
                            exc,
                        )
            raise last_auth_error  # type: ignore[misc]
        finally:
            duration = time.monotonic() - start
            source = str(event_data.get("source", "unknown"))
            issue_number = event_data.get("issue")
            pr_number = event_data.get("pr")
            tool, model = parse_command_tool_model(cmd)
            merged_stats = {
                **self._consume_context_stats(),
                **usage_stats,
                **(telemetry_stats or {}),
            }
            self._prompt_telemetry.record(
                source=source,
                tool=tool,
                model=model,
                issue_number=issue_number,
                pr_number=pr_number,
                session_id=self._bus.current_session_id,
                prompt_chars=len(prompt),
                transcript_chars=len(transcript),
                duration_seconds=duration,
                success=succeeded,
                stats=merged_stats,
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
        cache_hits = 0
        cache_misses = 0

        manifest_section = ""
        manifest_path = self._config.data_path("manifest", "manifest.md")
        manifest, manifest_hit = self._context_cache.get_or_load(
            key="manifest",
            source_path=manifest_path,
            loader=load_project_manifest,
        )
        cache_hits += 1 if manifest_hit else 0
        cache_misses += 0 if manifest_hit else 1
        if manifest:
            manifest_section = f"\n\n## Project Context\n\n{manifest}"

        memory_section = ""
        digest_path = self._config.data_path("memory", "digest.md")
        digest, digest_hit = self._context_cache.get_or_load(
            key="memory_digest",
            source_path=digest_path,
            loader=load_memory_digest,
        )
        cache_hits += 1 if digest_hit else 0
        cache_misses += 0 if digest_hit else 1
        if digest:
            memory_section = f"\n\n## Accumulated Learnings\n\n{digest}"

        self._last_context_stats = {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "context_chars_before": len(manifest) + len(digest),
            "context_chars_after": len(manifest_section) + len(memory_section),
        }

        return manifest_section, memory_section

    def _consume_context_stats(self) -> dict[str, int]:
        stats = dict(self._last_context_stats)
        self._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
        return stats

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the default implementation CLI invocation.

        Used by runners that call the implementation tool (``agent.py`` and
        ``hitl_runner.py``).  Runners that use a different tool (planner,
        reviewer, triage) override this method.  The ``_worktree_path``
        parameter is optional — no current override uses the path to build
        the command; runners that operate against ``repo_root`` (e.g.
        ``PlannerRunner``, ``TriageRunner``, ``ReviewRunner``) call this
        without a path.
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
