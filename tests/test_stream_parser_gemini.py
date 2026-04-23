"""Tests for gemini event parsing and usage extraction in stream_parser."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from stream_parser import StreamParser


def _parse_lines(parser: StreamParser, events: list[dict]) -> tuple[list[str], str]:
    displays: list[str] = []
    final = ""
    for event in events:
        display, result = parser.parse(json.dumps(event))
        if display:
            displays.append(display)
        if result is not None:
            final = result
    return displays, final


def test_gemini_init_event_locks_backend() -> None:
    parser = StreamParser()
    parser.parse(
        json.dumps(
            {
                "type": "init",
                "session_id": "abc",
                "model": "gemini-3.1-pro-preview",
            }
        )
    )
    snapshot = parser.usage_snapshot
    assert snapshot["usage_backend"] == "gemini"


def test_gemini_result_event_captures_stats() -> None:
    parser = StreamParser()
    parser.parse(
        json.dumps(
            {"type": "init", "session_id": "x", "model": "gemini-3.1-pro-preview"}
        )
    )
    parser.parse(
        json.dumps(
            {
                "type": "result",
                "status": "success",
                "stats": {
                    "total_tokens": 1000,
                    "input_tokens": 800,
                    "output_tokens": 200,
                    "cached": 400,
                    "duration_ms": 1200,
                    "tool_calls": 2,
                },
            }
        )
    )
    totals = parser.usage_totals
    assert totals["input_tokens"] == 800
    assert totals["output_tokens"] == 200
    assert totals["total_tokens"] == 1000
    assert totals["cache_read_input_tokens"] == 400  # "cached" maps to cache_read


def test_gemini_tool_use_emits_display_line() -> None:
    parser = StreamParser()
    displays, _ = _parse_lines(
        parser,
        [
            {"type": "init", "session_id": "x", "model": "gemini-3.1-pro-preview"},
            {
                "type": "tool_use",
                "tool_name": "run_shell_command",
                "tool_id": "t1",
                "parameters": {"command": "ls -la"},
            },
        ],
    )
    assert any("run_shell_command" in d for d in displays)
    assert any("ls -la" in d for d in displays)


def test_gemini_assistant_message_deltas_accumulate() -> None:
    displays, final = _parse_lines(
        StreamParser(),
        [
            {"type": "init", "session_id": "y", "model": "gemini-3.1-pro-preview"},
            {
                "type": "message",
                "role": "assistant",
                "content": "Hello ",
                "delta": True,
            },
            {
                "type": "message",
                "role": "assistant",
                "content": "world.",
                "delta": True,
            },
            {
                "type": "result",
                "status": "success",
                "stats": {"total_tokens": 5, "input_tokens": 3, "output_tokens": 2},
            },
        ],
    )
    assert final == "Hello world."


def test_gemini_result_does_not_collide_with_claude_result() -> None:
    """Claude's 'result' event carries `result` string; gemini's carries `stats`.
    Dispatcher must pick the correct extractor based on payload shape."""
    # Claude-style result (no prior init event)
    parser_claude = StreamParser()
    parser_claude.parse(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "content": [],
                },
            }
        )
    )
    parser_claude.parse(json.dumps({"type": "result", "result": "done", "usage": {}}))
    assert parser_claude.usage_snapshot["usage_backend"] == "claude"

    # Gemini-style result (after init)
    parser_gemini = StreamParser()
    parser_gemini.parse(
        json.dumps(
            {"type": "init", "session_id": "x", "model": "gemini-3.1-pro-preview"}
        )
    )
    parser_gemini.parse(
        json.dumps(
            {
                "type": "result",
                "status": "success",
                "stats": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            }
        )
    )
    assert parser_gemini.usage_snapshot["usage_backend"] == "gemini"
