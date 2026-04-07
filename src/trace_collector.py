"""In-process trace collector for stream_claude_process subprocesses.

Owned by the runner that calls stream_claude_process(). One instance
per `claude -p` subprocess. Accumulates spans in memory and writes a
SubprocessTrace JSON file on finalize().

Failure semantics: every public method is wrapped in try/except +
warning log. Trace collection MUST NOT crash the agent run.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from models import (
    SkillResultRecord,
    SubprocessTrace,
    ToolCallSpan,
    TraceTokenStats,
    TraceToolProfile,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

logger = logging.getLogger("hydraflow.trace_collector")


class TraceCollector:
    """Accumulate spans for one `claude -p` subprocess and write the trace."""

    def __init__(
        self,
        *,
        issue_number: int | None,
        phase: str,
        source: str,
        subprocess_idx: int,
        run_id: int,
        config: HydraFlowConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        self._issue_number = issue_number or 0
        self._phase = phase
        self._source = source
        self._subprocess_idx = subprocess_idx
        self._run_id = run_id
        self._config = config
        self._event_bus = event_bus

        self._started_at = datetime.now(UTC).isoformat()
        self._ended_at: str | None = None

        self.backend: str = "unknown"
        self.tokens = TraceTokenStats(
            prompt_tokens=0,
            completion_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        )
        self.tool_counts: dict[str, int] = {}
        self.tool_errors: dict[str, int] = {}
        self.tool_calls: list[ToolCallSpan] = []
        self.skill_results: list[SkillResultRecord] = []
        self.inference_count: int = 0
        self.turn_count: int = 0

        # Track open tool_use → tool_result by id, value is monotonic start time
        self._open_tool_starts: dict[str, float] = {}
        # Idempotency guard for finalize() — protects against double-finalize
        # on auth-retry exhaustion + outer except, or any other accidental
        # double-call from the runner lifecycle.
        self._finalized: bool = False

    def record(self, raw_line: str) -> None:
        """Record one parsed JSON line. Never raises."""
        try:
            self._record_inner(raw_line)
        except Exception:
            logger.warning("trace_collector.record failed", exc_info=True)

    def _record_inner(self, raw_line: str) -> None:
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return

        event_type = str(event.get("type", ""))
        self._detect_backend(event_type)

        if event_type == "assistant":
            self._handle_assistant(event)
        elif event_type == "user":
            self._handle_user_tool_result(event)
        elif event_type == "result":
            self._handle_result(event)
        elif event_type == "item.completed":
            self._handle_codex_item(event)
        elif event_type in ("message_update", "message_end"):
            self._handle_pi_message(event)
        elif event_type == "tool_execution_start":
            self._handle_pi_tool_start(event)
        elif event_type == "tool_execution_end":
            self._handle_pi_tool_end(event)
        elif event_type == "error":
            self._handle_error(event)

    def _detect_backend(self, event_type: str) -> None:
        if self.backend != "unknown":
            return
        if event_type in ("assistant", "user", "result"):
            self.backend = "claude"
        elif event_type in ("item.completed", "turn.completed"):
            self.backend = "codex"
        elif event_type in (
            "message_update",
            "message_end",
            "tool_execution_start",
            "tool_execution_end",
        ):
            self.backend = "pi"

    def _handle_assistant(self, event: dict[str, Any]) -> None:
        self.inference_count += 1
        self._extract_tokens(
            event.get("usage") or event.get("message", {}).get("usage")
        )

        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                self._add_tool_call(block)

    def _handle_user_tool_result(self, event: dict[str, Any]) -> None:
        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                if tool_use_id and tool_use_id in self._open_tool_starts:
                    started = self._open_tool_starts.pop(tool_use_id)
                    duration_ms = max(0, int((time.monotonic() - started) * 1000))
                    # Match by tool_use_id so out-of-order results from
                    # concurrent tool calls are attributed to the correct
                    # span instead of the most-recent pending one.
                    for idx in range(len(self.tool_calls) - 1, -1, -1):
                        span = self.tool_calls[idx]
                        if span.tool_use_id == tool_use_id and not span.succeeded:
                            self.tool_calls[idx] = span.model_copy(
                                update={"duration_ms": duration_ms, "succeeded": True}
                            )
                            break

    def _handle_result(self, event: dict[str, Any]) -> None:
        self._extract_tokens(event.get("usage"))
        self._ended_at = datetime.now(UTC).isoformat()

    def _handle_codex_item(self, event: dict[str, Any]) -> None:
        item = event.get("item", {})
        item_type = item.get("type", "")
        if item_type == "agent_message":
            self.inference_count += 1
        elif item_type == "function_call":
            try:
                args = (
                    json.loads(item.get("arguments", "{}"))
                    if item.get("arguments")
                    else {}
                )
            except (json.JSONDecodeError, TypeError):
                args = {}
            self._add_tool_call(
                {
                    "name": item.get("name", "?"),
                    "input": args,
                    "id": item.get("id", ""),
                }
            )

    def _handle_pi_message(self, event: dict[str, Any]) -> None:
        if event.get("type") == "message_end":
            self.inference_count += 1

    def _handle_pi_tool_start(self, event: dict[str, Any]) -> None:
        self._add_tool_call(
            {
                "name": event.get("toolName", "?"),
                "input": event.get("args", {}),
                "id": event.get("invocationId", ""),
            }
        )

    def _handle_pi_tool_end(self, event: dict[str, Any]) -> None:
        invocation_id = event.get("invocationId", "")
        if invocation_id in self._open_tool_starts:
            started = self._open_tool_starts.pop(invocation_id)
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            for idx in range(len(self.tool_calls) - 1, -1, -1):
                span = self.tool_calls[idx]
                if span.tool_use_id == invocation_id and not span.succeeded:
                    self.tool_calls[idx] = span.model_copy(
                        update={"duration_ms": duration_ms, "succeeded": True}
                    )
                    break

    def _handle_error(self, event: dict[str, Any]) -> None:
        msg = event.get("message", "unknown error")
        self.tool_errors["__stream__"] = self.tool_errors.get("__stream__", 0) + 1
        logger.debug("Stream error event recorded: %s", msg)

    def _add_tool_call(self, block: dict[str, Any]) -> None:
        name = str(block.get("name", "?"))
        tool_input = block.get("input") or {}
        tool_id = str(block.get("id", ""))
        summary = self._summarize_tool_input(name, tool_input)

        span = ToolCallSpan(
            tool_name=name,
            started_at=datetime.now(UTC).isoformat(),
            duration_ms=0,
            input_summary=summary,
            succeeded=False,
            tool_use_id=tool_id or None,
        )
        self.tool_calls.append(span)
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1
        if tool_id:
            self._open_tool_starts[tool_id] = time.monotonic()

    @staticmethod
    def _summarize_tool_input(name: str, tool_input: dict[str, Any]) -> str:
        """Reuse activity_parser._summarize_tool when available; fall back otherwise."""
        try:
            from activity_parser import _summarize_tool  # noqa: PLC0415

            return _summarize_tool(name, tool_input)
        except Exception:
            return str(tool_input)[:200]

    def _extract_tokens(self, usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        prompt = max(self.tokens.prompt_tokens, int(usage.get("input_tokens", 0) or 0))
        completion = max(
            self.tokens.completion_tokens, int(usage.get("output_tokens", 0) or 0)
        )
        cache_read = max(
            self.tokens.cache_read_tokens,
            int(usage.get("cache_read_input_tokens", 0) or 0),
        )
        cache_create = max(
            self.tokens.cache_creation_tokens,
            int(usage.get("cache_creation_input_tokens", 0) or 0),
        )
        total_input = prompt + cache_read
        cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0
        self.tokens = TraceTokenStats(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            cache_hit_rate=round(cache_hit_rate, 4),
        )

    def record_skill_result(
        self,
        skill_name: str,
        *,
        passed: bool,
        attempts: int,
        duration_seconds: float,
        blocking: bool,
    ) -> None:
        """Append a skill loop result. Source of truth for skill effectiveness."""
        try:
            self.skill_results.append(
                SkillResultRecord(
                    skill_name=skill_name,
                    passed=passed,
                    attempts=attempts,
                    duration_seconds=duration_seconds,
                    blocking=blocking,
                )
            )
        except Exception:
            logger.warning("trace_collector.record_skill_result failed", exc_info=True)

    def finalize(self, *, success: bool) -> SubprocessTrace | None:
        """Write the subprocess trace file. Returns the trace or None on failure.

        Idempotent: subsequent calls after the first are no-ops. This guards
        against double-finalize when, e.g., an auth-retry path and an outer
        ``except`` both attempt to finalize the same collector.

        Never raises.
        """
        if self._finalized:
            return None
        self._finalized = True
        try:
            return self._finalize_inner(success=success)
        except Exception:
            logger.warning("trace_collector.finalize failed", exc_info=True)
            return None

    def _finalize_inner(self, *, success: bool) -> SubprocessTrace | None:
        if self.inference_count == 0 and not self.tool_calls and not self.skill_results:
            return None

        if self._ended_at is None:
            self._ended_at = datetime.now(UTC).isoformat()

        trace = SubprocessTrace(
            issue_number=self._issue_number,
            phase=self._phase,
            source=self._source,
            run_id=self._run_id,
            subprocess_idx=self._subprocess_idx,
            backend=self.backend,
            started_at=self._started_at,
            ended_at=self._ended_at,
            success=success,
            crashed=not success,
            error=None,
            tokens=self.tokens,
            tools=TraceToolProfile(
                tool_counts=dict(self.tool_counts),
                tool_errors=dict(self.tool_errors),
                total_invocations=sum(self.tool_counts.values()),
            ),
            tool_calls=list(self.tool_calls),
            skill_results=list(self.skill_results),
            turn_count=self.turn_count,
            inference_count=self.inference_count,
        )

        out_dir = (
            self._config.data_root
            / "traces"
            / str(self._issue_number)
            / self._phase
            / f"run-{self._run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"subprocess-{self._subprocess_idx}.json"
        out_path.write_text(trace.model_dump_json(indent=2))

        return trace
