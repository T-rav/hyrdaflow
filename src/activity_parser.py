"""Pluggable parsers that extract structured activity events from agent CLI output.

Each parser handles one CLI backend (Claude, Codex, Pi) and converts raw
JSON stream lines into :class:`~models.AgentActivityPayload` dicts.
The streaming function in ``runner_utils.py`` publishes these as
``AGENT_ACTIVITY`` events alongside the existing ``TRANSCRIPT_LINE`` events.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from models import AgentActivityPayload

# Minimum text length to emit a TEXT activity (filters partial deltas)
_MIN_TEXT_LEN = 20
# Max chars for the detail field
_MAX_DETAIL_LEN = 200


class ActivityParser(Protocol):
    """Protocol for CLI-specific activity parsers."""

    def parse(self, raw_line: str) -> AgentActivityPayload | None:
        """Parse a JSON stream line into a structured activity event.

        Returns ``None`` if the line is not interesting (session meta, etc.).
        The caller fills in ``issue`` and ``source`` from runner context.
        """
        ...


_FILE_PATH_VERBS: dict[str, str] = {
    "read": "Reading",
    "edit": "Editing",
    "write": "Writing",
}


def _summarize_tool(name: str, tool_input: dict[str, Any]) -> str:
    """Generate a human-readable summary for a tool call."""
    normalized = name.lower()
    verb = _FILE_PATH_VERBS.get(normalized)
    if verb:
        return f"{verb} {tool_input.get('file_path', '?')}"
    if normalized in ("bash", "run_shell_command"):
        cmd = tool_input.get("command", "")
        return f"Running: {cmd[:60]}" if cmd else "Running command"
    if normalized == "glob":
        return f"Searching for {tool_input.get('pattern', '?')}"
    if normalized == "grep":
        return f"Searching for '{tool_input.get('pattern', '?')}'"
    return name


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


class ClaudeActivityParser:
    """Parses Claude ``--output-format stream-json`` lines into activity events."""

    def __init__(self) -> None:
        self._seen_tool_ids: set[str] = set()
        self._prev_text_len: int = 0
        self._prev_msg_id: str = ""

    def parse(self, raw_line: str) -> AgentActivityPayload | None:
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return None

        event_type = event.get("type", "")

        if event_type == "assistant":
            return self._parse_assistant(event)
        if event_type == "user":
            return self._parse_tool_result(event)
        if event_type == "error":
            msg = event.get("message", "Unknown error")
            return {
                "activity_type": "error",
                "tool_name": None,
                "summary": _truncate(str(msg), 80),
                "detail": _truncate(str(msg), _MAX_DETAIL_LEN),
            }
        return None

    def _parse_assistant(self, event: dict[str, Any]) -> AgentActivityPayload | None:
        message = event.get("message", {})
        msg_id = message.get("id", "")
        content = message.get("content", [])

        if msg_id != self._prev_msg_id:
            self._prev_text_len = 0
            self._prev_msg_id = msg_id

        # Check for new tool_use blocks first (higher priority than text)
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                if tool_id and tool_id in self._seen_tool_ids:
                    continue
                if tool_id:
                    self._seen_tool_ids.add(tool_id)
                name = block.get("name", "?")
                tool_input = block.get("input", {})
                return {
                    "activity_type": "tool_call",
                    "tool_name": name,
                    "summary": _summarize_tool(name, tool_input),
                    "detail": _truncate(str(tool_input), _MAX_DETAIL_LEN),
                }

        # Fall back to text delta
        full_text = ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                full_text += block.get("text", "")

        if len(full_text) > self._prev_text_len:
            delta = full_text[self._prev_text_len :]
            self._prev_text_len = len(full_text)
            if len(delta.strip()) >= _MIN_TEXT_LEN:
                return {
                    "activity_type": "text",
                    "tool_name": None,
                    "summary": _truncate(delta.strip(), 80),
                    "detail": _truncate(delta.strip(), _MAX_DETAIL_LEN),
                }

        return None

    def _parse_tool_result(self, event: dict[str, Any]) -> AgentActivityPayload | None:
        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                result_content = block.get("content", "")
                preview = (
                    str(result_content)[:80].replace("\n", " ")
                    if result_content
                    else "(empty)"
                )
                return {
                    "activity_type": "tool_result",
                    "tool_name": None,
                    "summary": f"Result: {preview}",
                    "detail": _truncate(str(result_content), _MAX_DETAIL_LEN),
                }
        return None


class CodexActivityParser:
    """Parses Codex ``--json`` stream lines into activity events."""

    def __init__(self) -> None:
        self._seen_item_ids: set[str] = set()

    def parse(self, raw_line: str) -> AgentActivityPayload | None:
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return None

        event_type = event.get("type", "")
        if event_type != "item.completed":
            return None

        item = event.get("item", {})
        item_id = item.get("id", "")
        if item_id and item_id in self._seen_item_ids:
            return None
        if item_id:
            self._seen_item_ids.add(item_id)

        item_type = item.get("type", "")

        if item_type == "function_call":
            name = item.get("name", "?")
            try:
                args = json.loads(item.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {}
            return {
                "activity_type": "tool_call",
                "tool_name": name,
                "summary": _summarize_tool(name, args),
                "detail": _truncate(str(args), _MAX_DETAIL_LEN),
            }

        if item_type == "agent_message":
            text = str(item.get("text", "")).strip()
            if len(text) >= _MIN_TEXT_LEN:
                return {
                    "activity_type": "text",
                    "tool_name": None,
                    "summary": _truncate(text, 80),
                    "detail": _truncate(text, _MAX_DETAIL_LEN),
                }

        return None


class GeminiActivityParser:
    """Parses Gemini ``--output-format stream-json`` lines into activity events."""

    def __init__(self) -> None:
        self._seen_tool_ids: set[str] = set()

    def parse(self, raw_line: str) -> AgentActivityPayload | None:
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return None

        event_type = event.get("type", "")

        if event_type == "tool_use":
            return self._parse_tool_use(event)
        if event_type == "tool_result":
            return self._parse_tool_result(event)
        if event_type == "message":
            return self._parse_message(event)
        if event_type == "error":
            return self._parse_error(event)
        return None

    def _parse_tool_use(self, event: dict[str, Any]) -> AgentActivityPayload | None:
        tool_id = event.get("tool_id", "")
        if tool_id and tool_id in self._seen_tool_ids:
            return None
        if tool_id:
            self._seen_tool_ids.add(tool_id)
        name = str(event.get("tool_name", "?"))
        params = event.get("parameters", {})
        if not isinstance(params, dict):
            params = {}
        return {
            "activity_type": "tool_call",
            "tool_name": name,
            "summary": _summarize_tool(name, params),
            "detail": _truncate(str(params), _MAX_DETAIL_LEN),
        }

    def _parse_tool_result(self, event: dict[str, Any]) -> AgentActivityPayload | None:
        output = event.get("output", "")
        status = str(event.get("status", ""))
        preview_source = str(output) if output else status
        preview = preview_source[:80].replace("\n", " ") if preview_source else "(done)"
        return {
            "activity_type": "tool_result",
            "tool_name": None,
            "summary": f"Result: {preview}",
            "detail": _truncate(str(output or status), _MAX_DETAIL_LEN),
        }

    def _parse_message(self, event: dict[str, Any]) -> AgentActivityPayload | None:
        if event.get("role") != "assistant":
            return None
        text = str(event.get("content", "")).strip()
        if len(text) >= _MIN_TEXT_LEN:
            return {
                "activity_type": "text",
                "tool_name": None,
                "summary": _truncate(text, 80),
                "detail": _truncate(text, _MAX_DETAIL_LEN),
            }
        return None

    def _parse_error(self, event: dict[str, Any]) -> AgentActivityPayload | None:
        msg = event.get("message", "Unknown error")
        return {
            "activity_type": "error",
            "tool_name": None,
            "summary": _truncate(str(msg), 80),
            "detail": _truncate(str(msg), _MAX_DETAIL_LEN),
        }


class PiActivityParser:
    """No-op stub for Pi CLI — returns None for all lines."""

    def parse(self, raw_line: str) -> AgentActivityPayload | None:
        del raw_line  # no-op stub
        return None


def get_activity_parser(backend: str) -> ActivityParser:
    """Return the activity parser for the given CLI backend."""
    parsers: dict[str, ActivityParser] = {
        "claude": ClaudeActivityParser(),
        "codex": CodexActivityParser(),
        "gemini": GeminiActivityParser(),
        "pi": PiActivityParser(),
    }
    return parsers.get(backend, PiActivityParser())
