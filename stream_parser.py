"""Parse Claude/Codex JSON stream output into human-readable transcript lines."""

from __future__ import annotations

import json
from typing import Any


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
        elif event_type == "error":
            display = event.get("message", "")
        else:
            display = raw_line

        return (display, result)

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
