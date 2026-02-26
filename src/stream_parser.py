"""Parse Claude/Codex/Pi JSON stream output into human-readable transcript lines."""

from __future__ import annotations

import json
from typing import Any

_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "total_tokens",
)


class _UsageExtractor:
    """Backend-specific usage extractor contract."""

    backend = "unknown"

    def extract(
        self, event: dict[str, Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        return {}, []

    def is_final_event(self, event: dict[str, Any]) -> bool:
        return False


class _ClaudeUsageExtractor(_UsageExtractor):
    backend = "claude"
    _EVENT_TYPES = {"assistant", "result", "user"}

    def extract(
        self, event: dict[str, Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        if str(event.get("type", "")) not in self._EVENT_TYPES:
            return {}, []
        totals: dict[str, int] = {}
        raw: list[dict[str, Any]] = []
        for usage_key in ("usage", "token_usage", "usage_metadata"):
            usage_obj = event.get(usage_key)
            mapped = _map_usage_payload(usage_obj)
            if mapped:
                totals.update(mapped)
            if isinstance(usage_obj, dict):
                raw.append(
                    {
                        "backend": self.backend,
                        "event_type": str(event.get("type", "")),
                        "path": usage_key,
                        "payload": usage_obj,
                    }
                )
        message = event.get("message", {})
        if isinstance(message, dict):
            for usage_key in ("usage", "token_usage", "usage_metadata"):
                usage_obj = message.get(usage_key)
                mapped = _map_usage_payload(usage_obj)
                if mapped:
                    totals.update(mapped)
                if isinstance(usage_obj, dict):
                    raw.append(
                        {
                            "backend": self.backend,
                            "event_type": str(event.get("type", "")),
                            "path": f"message.{usage_key}",
                            "payload": usage_obj,
                        }
                    )
        # Claude also sometimes emits token fields top-level.
        totals.update(_map_top_level_usage_scalars(event))
        return totals, raw

    def is_final_event(self, event: dict[str, Any]) -> bool:
        return str(event.get("type", "")) == "result"


class _CodexUsageExtractor(_UsageExtractor):
    backend = "codex"
    _EVENT_TYPES = {"item.completed", "turn.completed", "result"}

    def extract(
        self, event: dict[str, Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        if str(event.get("type", "")) not in self._EVENT_TYPES:
            return {}, []
        totals: dict[str, int] = {}
        raw: list[dict[str, Any]] = []

        for usage_key in ("usage", "token_usage", "usage_metadata"):
            usage_obj = event.get(usage_key)
            mapped = _map_usage_payload(usage_obj)
            if mapped:
                totals.update(mapped)
            if isinstance(usage_obj, dict):
                raw.append(
                    {
                        "backend": self.backend,
                        "event_type": str(event.get("type", "")),
                        "path": usage_key,
                        "payload": usage_obj,
                    }
                )

        item = event.get("item", {})
        if isinstance(item, dict):
            for usage_key in ("usage", "token_usage", "usage_metadata"):
                usage_obj = item.get(usage_key)
                mapped = _map_usage_payload(usage_obj)
                if mapped:
                    totals.update(mapped)
                if isinstance(usage_obj, dict):
                    raw.append(
                        {
                            "backend": self.backend,
                            "event_type": str(event.get("type", "")),
                            "path": f"item.{usage_key}",
                            "payload": usage_obj,
                        }
                    )

        return totals, raw

    def is_final_event(self, event: dict[str, Any]) -> bool:
        return str(event.get("type", "")) in {"turn.completed", "result"}


class _PiUsageExtractor(_UsageExtractor):
    backend = "pi"
    _EVENT_TYPES = {
        "message_update",
        "message_end",
        "agent_end",
        "turn_end",
        "tool_execution_end",
    }

    def extract(
        self, event: dict[str, Any]
    ) -> tuple[dict[str, int], list[dict[str, Any]]]:
        if str(event.get("type", "")) not in self._EVENT_TYPES:
            return {}, []
        totals: dict[str, int] = {}
        raw: list[dict[str, Any]] = []

        for usage_key in ("usage", "token_usage", "usage_metadata"):
            usage_obj = event.get(usage_key)
            mapped = _map_usage_payload(usage_obj)
            if mapped:
                totals.update(mapped)
            if isinstance(usage_obj, dict):
                raw.append(
                    {
                        "backend": self.backend,
                        "event_type": str(event.get("type", "")),
                        "path": usage_key,
                        "payload": usage_obj,
                    }
                )

        for parent_key in ("message", "assistantMessageEvent"):
            parent = event.get(parent_key)
            if not isinstance(parent, dict):
                continue
            for usage_key in ("usage", "token_usage", "usage_metadata"):
                usage_obj = parent.get(usage_key)
                mapped = _map_usage_payload(usage_obj)
                if mapped:
                    totals.update(mapped)
                if isinstance(usage_obj, dict):
                    raw.append(
                        {
                            "backend": self.backend,
                            "event_type": str(event.get("type", "")),
                            "path": f"{parent_key}.{usage_key}",
                            "payload": usage_obj,
                        }
                    )

        return totals, raw

    def is_final_event(self, event: dict[str, Any]) -> bool:
        return str(event.get("type", "")) in {"message_end", "agent_end", "turn_end"}


class StreamParser:
    """Stateful parser for ``claude -p --output-format stream-json``.

    The stream-json format emits one JSON object per line:
    - ``assistant`` events contain a ``message.content`` array with
      ``text`` and ``tool_use`` blocks.  Each event is a *cumulative*
      snapshot — the same content repeats as the turn grows.
    - ``user`` events carry tool results (we show a summary).
    - ``result`` events carry the final output.

    This parser tracks what it has already shown so each call to
    :meth:`parse` returns only *new* display content.
    """

    def __init__(self) -> None:
        self._seen_tool_ids: set[str] = set()
        self._seen_item_ids: set[str] = set()
        self._prev_text_len: int = 0
        self._prev_msg_id: str = ""
        self._last_result_text: str = ""
        self._usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "total_tokens": 0,
        }
        self._raw_usage_events: list[dict[str, Any]] = []
        self._extractor: _UsageExtractor = _ClaudeUsageExtractor()
        self._final_usage: dict[str, int] = {}

    def parse(self, raw_line: str) -> tuple[str, str | None]:
        """Parse a single stream-json line.

        Returns ``(display_text, result_text)``:
        - *display_text* is human-readable text for the live transcript.
        - *result_text* is non-None only for the final ``result`` event.
        """
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return (raw_line, None)

        self._capture_usage(event)
        event_type = event.get("type", "")

        display = ""
        result: str | None = None

        if event_type == "assistant":
            display = self._parse_assistant(event)
        elif event_type == "result":
            result = event.get("result", "")
        elif event_type == "user":
            display = self._parse_user(event)
        elif event_type == "item.completed":
            display = self._parse_codex_item(event)
        elif event_type == "turn.completed":
            result = self._last_result_text
        elif event_type == "message_update":
            display = self._parse_pi_message_update(event)
        elif event_type == "message_end":
            self._capture_pi_message_end(event)
        elif event_type == "tool_execution_start":
            display = self._parse_pi_tool_start(event)
        elif event_type == "tool_execution_end":
            display = self._parse_pi_tool_end(event)
        elif event_type in {
            "session",
            "agent_start",
            "agent_end",
            "turn_start",
            "turn_end",
            "message_start",
            "tool_execution_update",
            "auto_compaction_start",
            "auto_compaction_end",
            "auto_retry_start",
            "auto_retry_end",
        }:
            if event_type in {"agent_end", "turn_end"}:
                result = self._last_result_text
            display = ""
        elif event_type == "error":
            display = event.get("message", "")
        else:
            display = raw_line

        return (display, result)

    @property
    def usage_totals(self) -> dict[str, int]:
        """Return cumulative usage totals captured from stream events."""
        if self._final_usage:
            return self._final_usage_snapshot()
        return dict(self._usage)

    @property
    def usage_snapshot(self) -> dict[str, object]:
        """Return normalized usage totals plus availability/source metadata."""
        totals = self.usage_totals
        usage_available = any(v > 0 for v in totals.values())
        status = "available" if usage_available else "unavailable"
        return {
            **totals,
            "usage_available": usage_available,
            "usage_status": status,
            "usage_backend": self._extractor.backend,
            "raw_usage": [*self._raw_usage_events],
        }

    def _parse_assistant(self, event: dict[str, Any]) -> str:
        """Extract new content from an assistant message event."""
        message = event.get("message", {})
        msg_id = message.get("id", "")
        content = message.get("content", [])

        # Reset text tracking when a new turn starts
        if msg_id != self._prev_msg_id:
            self._prev_text_len = 0
            self._prev_msg_id = msg_id

        parts: list[str] = []

        # Collect text delta and new tool_use blocks
        full_text = ""
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                full_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                if tool_id and tool_id not in self._seen_tool_ids:
                    self._seen_tool_ids.add(tool_id)
                    name = block.get("name", "?")
                    tool_input = block.get("input", {})
                    parts.append(f"  → {name}: {_summarize_input(name, tool_input)}")

        # Emit text delta
        if len(full_text) > self._prev_text_len:
            delta = full_text[self._prev_text_len :].strip()
            self._prev_text_len = len(full_text)
            if delta:
                parts.insert(0, delta)

        return "\n".join(parts)

    def _parse_user(self, event: dict[str, Any]) -> str:
        """Extract a brief summary from a user (tool result) event."""
        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                # Show a brief indicator that a tool returned
                content_val = block.get("content", "")
                if isinstance(content_val, str) and content_val:
                    preview = content_val[:80].replace("\n", " ")
                    return f"    ← {preview}{'…' if len(content_val) > 80 else ''}"
        return ""

    def _parse_codex_item(self, event: dict[str, Any]) -> str:
        """Extract display text from a Codex item completion event."""
        item = event.get("item", {})
        item_id = item.get("id", "")
        if item_id and item_id in self._seen_item_ids:
            return ""
        if item_id:
            self._seen_item_ids.add(item_id)

        item_type = item.get("type", "")
        if item_type == "agent_message":
            text = str(item.get("text", "")).strip()
            if text:
                self._last_result_text = text
            return text

        if item_type == "reasoning":
            return str(item.get("text", "")).strip()

        if item_type:
            return f"  → {item_type}"
        return ""

    def _parse_pi_message_update(self, event: dict[str, Any]) -> str:
        """Extract text deltas from Pi JSON `message_update` events."""
        update = event.get("assistantMessageEvent", {})
        if not isinstance(update, dict):
            return ""
        if update.get("type") == "text_delta":
            delta = str(update.get("delta", ""))
            if delta:
                self._last_result_text += delta
            return delta
        return ""

    def _capture_pi_message_end(self, event: dict[str, Any]) -> None:
        """Capture final assistant text from Pi `message_end` events."""
        message = event.get("message", {})
        if not isinstance(message, dict):
            return
        if message.get("role") != "assistant":
            return
        content = message.get("content", [])
        if not isinstance(content, list):
            return
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    text_parts.append(text)
        if text_parts:
            self._last_result_text = "\n".join(text_parts)

    def _parse_pi_tool_start(self, event: dict[str, Any]) -> str:
        """Summarize Pi tool start events in transcript format."""
        name = str(event.get("toolName", "")).strip()
        args = event.get("args", {})
        if not name:
            return ""
        return f"  → {name}: {_summarize_input(name, args if isinstance(args, dict) else {})}"

    def _parse_pi_tool_end(self, event: dict[str, Any]) -> str:
        """Summarize Pi tool completion events."""
        name = str(event.get("toolName", "")).strip()
        if not name:
            return ""
        result = event.get("result", "")
        if isinstance(result, str) and result.strip():
            preview = result.strip().replace("\n", " ")[:80]
            return f"    ← {preview}{'…' if len(result.strip()) > 80 else ''}"
        return "    ← (done)"

    def _capture_usage(self, event: dict[str, Any]) -> None:
        """Extract token usage fields from backend-specific stream payloads."""
        self._extractor = _pick_usage_extractor(self._extractor, event)
        totals, raw = self._extractor.extract(event)
        if raw:
            self._raw_usage_events.extend(raw)
            if len(self._raw_usage_events) > 20:
                self._raw_usage_events = self._raw_usage_events[-20:]
        if totals:
            for key, value in totals.items():
                if key not in self._usage:
                    continue
                self._usage[key] = max(self._usage[key], value)
            if self._extractor.is_final_event(event):
                self._final_usage = self._usage.copy()

    def _final_usage_snapshot(self) -> dict[str, int]:
        out = dict(self._usage)
        for key in _USAGE_KEYS:
            out[key] = max(out.get(key, 0), self._final_usage.get(key, 0))
        return out


def _pick_usage_extractor(
    current: _UsageExtractor, event: dict[str, Any]
) -> _UsageExtractor:
    event_type = str(event.get("type", ""))
    if event_type in {
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_end",
        "agent_end",
        "turn_end",
    }:
        return _PiUsageExtractor()
    if event_type in {"item.completed", "turn.completed"}:
        return _CodexUsageExtractor()
    if event_type in {"assistant", "result", "user"}:
        return _ClaudeUsageExtractor()
    return current


def _map_usage_payload(obj: Any) -> dict[str, int]:
    """Return canonical usage totals from arbitrary payload object."""
    totals: dict[str, int] = {}
    for key, value in _iter_numeric_fields(obj):
        canonical = _canonical_usage_key(key)
        if not canonical:
            continue
        if value > totals.get(canonical, 0):
            totals[canonical] = value
    return totals


def _map_top_level_usage_scalars(event: dict[str, Any]) -> dict[str, int]:
    """Map only top-level scalar usage keys (avoid nested tool payload false positives)."""
    totals: dict[str, int] = {}
    for key, value in event.items():
        if not isinstance(value, (int, float)):
            continue
        canonical = _canonical_usage_key(str(key))
        if not canonical:
            continue
        totals[canonical] = max(totals.get(canonical, 0), int(value))
    return totals


def _iter_numeric_fields(obj: Any) -> list[tuple[str, int]]:
    """Return nested ``(key, int_value)`` numeric fields for a usage payload."""
    out: list[tuple[str, int]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (int, float)):
                out.append((str(k), int(v)))
            else:
                out.extend(_iter_numeric_fields(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_iter_numeric_fields(item))
    return out


def _canonical_usage_key(raw_key: str) -> str:
    """Map backend-specific usage keys to canonical names."""
    key = raw_key.lower()
    if key in {"input_tokens", "prompt_tokens", "inputtokencount", "input"}:
        return "input_tokens"
    if key in {"output_tokens", "completion_tokens", "outputtokencount", "output"}:
        return "output_tokens"
    if key in {
        "cache_creation_input_tokens",
        "cache_creation_tokens",
        "cachewriteinputtokens",
        "cachewrite",
    }:
        return "cache_creation_input_tokens"
    if key in {
        "cache_read_input_tokens",
        "cache_read_tokens",
        "cached_tokens",
        "cached_input_tokens",
        "cachereadinputtokens",
        "cacheread",
    }:
        return "cache_read_input_tokens"
    if key in {"total_tokens", "totaltokencount", "totaltokens"}:
        return "total_tokens"
    return ""


def _summarize_input(name: str, tool_input: dict[str, Any]) -> str:  # noqa: PLR0911
    """One-line summary of a tool call's input."""
    if name in ("Read", "read"):
        return tool_input.get("file_path", str(tool_input))[:120]
    if name in ("Edit", "edit"):
        return tool_input.get("file_path", "?")[:120]
    if name in ("Write", "write"):
        return tool_input.get("file_path", str(tool_input))[:120]
    if name in ("Glob", "glob"):
        return tool_input.get("pattern", str(tool_input))[:120]
    if name in ("Grep", "grep"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", ".")
        return f"/{pattern}/ in {path}"[:120]
    if name in ("Bash", "bash"):
        return tool_input.get("command", str(tool_input))[:120]
    if name in ("Task", "task"):
        desc = tool_input.get("description", "")
        agent = tool_input.get("subagent_type", "")
        return f"{agent}: {desc}"[:120] if agent else desc[:120]
    # Generic fallback
    summary = str(tool_input)
    return summary[:120] + ("..." if len(summary) > 120 else "")
