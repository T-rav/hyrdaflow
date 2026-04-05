"""Base runner class — shared lifecycle for all agent runners."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from agent_cli import build_agent_command
from config import Credentials, HydraFlowConfig
from events import EventBus
from execution import get_default_runner
from models import LoopResult, TranscriptEventData
from prompt_telemetry import PromptTelemetry, parse_command_tool_model
from runner_utils import (
    AuthenticationRetryError,
    stream_claude_process,
    terminate_processes,
)

if TYPE_CHECKING:
    from execution import SubprocessRunner
    from hindsight import HindsightClient


class BaseRunner:
    """Shared base for ``AgentRunner``, ``PlannerRunner``, ``ReviewRunner``, and ``HITLRunner``.

    Provides the common ``__init__``, ``terminate``, ``_execute``,
    ``_save_transcript``, ``_inject_memory``, and
    ``_verify_quality`` implementations so each subclass only needs to
    implement its own prompt-building and run logic.
    """

    _log: ClassVar[logging.Logger]

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
        *,
        hindsight: HindsightClient | None = None,
        credentials: Credentials | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()
        self._prompt_telemetry = PromptTelemetry(config)
        self._last_context_stats: dict[str, int] = {"cache_hits": 0, "cache_misses": 0}
        self._hindsight = hindsight
        self._credentials = credentials or Credentials()

    @property
    def active_count(self) -> int:
        """Number of currently running subprocesses."""
        return len(self._active_procs)

    @property
    def hindsight(self) -> HindsightClient | None:
        """Read-only access to the Hindsight client for shared prefix building."""
        return self._hindsight

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
            try:
                import sentry_sdk as _sentry  # noqa: PLC0415

                _sentry.set_tag("hydraflow.issue", str(event_data.get("issue", "")))
                _sentry.set_tag("hydraflow.source", str(event_data.get("source", "")))
                _sentry.set_context(
                    "hydraflow_runner",
                    {
                        "model": self._config.model,
                        "tool": self._config.implementation_tool,
                    },
                )
            except Exception:
                pass  # Sentry not installed or not initialized
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
                        gh_token=self._credentials.gh_token,
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

    async def _inject_memory(self, *, query_context: str = "") -> str:
        """Load the memory digest via Hindsight semantic recall.

        Returns the memory section as a string, or an empty string when
        Hindsight is not configured or recall produces no results.
        """
        memory_section = ""
        memory_raw = ""
        troubleshooting_raw = ""
        retrospectives_raw = ""
        review_insights_raw = ""
        harness_insights_raw = ""
        dedup_items_removed = 0
        dedup_chars_saved = 0

        if self._hindsight and query_context:
            from hindsight import Bank, format_memories_as_markdown, recall_safe

            max_chars = self._config.max_memory_prompt_chars
            banks_recalled: list[str] = []

            # All banks wrapped in try/except — recall failures must never
            # interrupt the pipeline.  Priority order determines prompt
            # assembly; each bank is independently capped at max_chars.
            try:
                memories = await recall_safe(
                    self._hindsight, Bank.LEARNINGS, query_context
                )
                memory_raw = format_memories_as_markdown(memories)
                if memory_raw:
                    memory_raw = memory_raw[:max_chars]
                    banks_recalled.append("learnings")
            except Exception:  # noqa: BLE001
                pass  # Must not interrupt pipeline

            try:
                ts_memories = await recall_safe(
                    self._hindsight, Bank.TROUBLESHOOTING, query_context
                )
                troubleshooting_raw = format_memories_as_markdown(ts_memories)
                if troubleshooting_raw:
                    troubleshooting_raw = troubleshooting_raw[:max_chars]
                    banks_recalled.append("troubleshooting")
            except Exception:  # noqa: BLE001
                pass  # Must not interrupt pipeline

            try:
                retro_memories = await recall_safe(
                    self._hindsight, Bank.RETROSPECTIVES, query_context
                )
                retrospectives_raw = format_memories_as_markdown(retro_memories)
                if retrospectives_raw:
                    retrospectives_raw = retrospectives_raw[:max_chars]
                    banks_recalled.append("retrospectives")
            except Exception:  # noqa: BLE001
                pass  # Must not interrupt pipeline

            try:
                ri_memories = await recall_safe(
                    self._hindsight, Bank.REVIEW_INSIGHTS, query_context
                )
                review_insights_raw = format_memories_as_markdown(ri_memories)
                if review_insights_raw:
                    review_insights_raw = review_insights_raw[:max_chars]
                    banks_recalled.append("review_insights")
            except Exception:  # noqa: BLE001
                pass  # Must not interrupt pipeline

            try:
                hi_memories = await recall_safe(
                    self._hindsight, Bank.HARNESS_INSIGHTS, query_context
                )
                harness_insights_raw = format_memories_as_markdown(hi_memories)
                if harness_insights_raw:
                    harness_insights_raw = harness_insights_raw[:max_chars]
                    banks_recalled.append("harness_insights")
            except Exception:  # noqa: BLE001
                pass  # Must not interrupt pipeline

            # Sentry breadcrumb for memory recall observability
            try:
                import sentry_sdk as _sentry  # noqa: PLC0415

                _sentry.add_breadcrumb(
                    category="memory.recall",
                    message=f"Recalled {len(banks_recalled)} memory banks",
                    level="info",
                    data={
                        "banks": banks_recalled,
                        "query_context": query_context[:100],
                    },
                )
            except ImportError:
                pass

        # Deduplicate memory items across banks before assembly.
        from prompt_dedup import PromptDeduplicator  # noqa: PLC0415

        deduper = PromptDeduplicator()
        all_raw = {
            "memory": memory_raw,
            "troubleshooting": troubleshooting_raw,
            "retrospectives": retrospectives_raw,
            "review_insights": review_insights_raw,
            "harness_insights": harness_insights_raw,
        }
        all_items: list[str] = []
        for raw in all_raw.values():
            if raw:
                # Split markdown list items (each starts with "- ")
                items = [f"- {chunk}" for chunk in raw.split("\n- ") if chunk.strip()]
                if items and items[0].startswith("- - "):
                    items[0] = items[0][2:]  # fix double prefix on first
                all_items.extend(items)

        total_before = len(all_items)
        deduped_items = deduper.dedup_memories(all_items)
        dedup_items_removed = total_before - len(deduped_items)
        dedup_chars_saved = sum(len(i) for i in all_items) - sum(
            len(i) for i in deduped_items
        )

        # Rebuild per-bank raw strings from deduped items by re-splitting.
        # Each bank keeps only items that survived dedup.
        deduped_set = set(deduped_items)
        for key, raw in all_raw.items():
            if raw:
                items = [f"- {chunk}" for chunk in raw.split("\n- ") if chunk.strip()]
                if items and items[0].startswith("- - "):
                    items[0] = items[0][2:]
                kept = [item for item in items if item in deduped_set]
                new_raw = "\n".join(kept)
                if key == "memory":
                    memory_raw = new_raw
                elif key == "troubleshooting":
                    troubleshooting_raw = new_raw
                elif key == "retrospectives":
                    retrospectives_raw = new_raw
                elif key == "review_insights":
                    review_insights_raw = new_raw
                elif key == "harness_insights":
                    harness_insights_raw = new_raw

        # Assemble the memory section from all available banks.
        # Cap the combined section at max_memory_prompt_chars.
        combined_parts: list[str] = []

        if memory_raw:
            combined_parts.append(f"## Accumulated Learnings\n\n{memory_raw}")
        if troubleshooting_raw:
            combined_parts.append(
                f"## Known Troubleshooting Patterns\n\n{troubleshooting_raw}"
            )
        if retrospectives_raw:
            combined_parts.append(f"## Past Retrospectives\n\n{retrospectives_raw}")
        if review_insights_raw:
            combined_parts.append(f"## Common Review Patterns\n\n{review_insights_raw}")
        if harness_insights_raw:
            combined_parts.append(
                f"## Known Pipeline Patterns\n\n{harness_insights_raw}"
            )

        if combined_parts:
            combined = "\n\n".join(combined_parts)
            combined = combined[: self._config.max_memory_prompt_chars]
            memory_section = f"\n\n{combined}"

        self._last_context_stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "context_chars_before": (
                len(memory_raw)
                + len(troubleshooting_raw)
                + len(retrospectives_raw)
                + len(review_insights_raw)
                + len(harness_insights_raw)
            ),
            "context_chars_after": len(memory_section),
            "dedup_items_removed": dedup_items_removed,
            "dedup_chars_saved": dedup_chars_saved,
        }

        return memory_section

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

    async def _verify_quality(self, worktree_path: Path) -> LoopResult:
        """Run ``make quality`` and return a :class:`LoopResult`."""
        try:
            result = await self._runner.run_simple(
                ["make", "quality"],
                cwd=str(worktree_path),
                timeout=self._config.quality_timeout,
            )
        except FileNotFoundError:
            return LoopResult(
                passed=False, summary="make not found — cannot run quality checks"
            )
        except TimeoutError:
            return LoopResult(
                passed=False,
                summary=f"make quality timed out after {self._config.quality_timeout}s",
            )
        if result.returncode != 0:
            output = "\n".join(filter(None, [result.stdout, result.stderr]))
            return LoopResult(
                passed=False,
                summary=f"`make quality` failed:\n{output[-self._config.error_output_max_chars :]}",
            )
        return LoopResult(passed=True, summary="OK")
