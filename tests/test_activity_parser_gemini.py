"""Tests for the Gemini activity parser."""

from __future__ import annotations

import json

from activity_parser import GeminiActivityParser, get_activity_parser


def test_gemini_parser_registered_in_dispatch() -> None:
    parser = get_activity_parser("gemini")
    assert isinstance(parser, GeminiActivityParser)


def test_gemini_tool_use_emits_tool_call_activity() -> None:
    parser = GeminiActivityParser()
    raw = json.dumps(
        {
            "type": "tool_use",
            "tool_name": "run_shell_command",
            "tool_id": "t1",
            "parameters": {"command": "ls"},
        }
    )
    activity = parser.parse(raw)
    assert activity is not None
    assert activity["activity_type"] == "tool_call"
    assert activity["tool_name"] == "run_shell_command"


def test_gemini_tool_result_emits_tool_result_activity() -> None:
    parser = GeminiActivityParser()
    raw = json.dumps(
        {
            "type": "tool_result",
            "tool_id": "t1",
            "status": "success",
            "output": "file1.txt\nfile2.txt",
        }
    )
    activity = parser.parse(raw)
    assert activity is not None
    assert activity["activity_type"] == "tool_result"


def test_gemini_assistant_delta_emits_text_when_long_enough() -> None:
    parser = GeminiActivityParser()
    raw = json.dumps(
        {
            "type": "message",
            "role": "assistant",
            "content": "This is a long enough delta to pass the threshold.",
            "delta": True,
        }
    )
    activity = parser.parse(raw)
    assert activity is not None
    assert activity["activity_type"] == "text"


def test_gemini_short_delta_returns_none() -> None:
    parser = GeminiActivityParser()
    raw = json.dumps(
        {
            "type": "message",
            "role": "assistant",
            "content": "hi",
            "delta": True,
        }
    )
    assert parser.parse(raw) is None


def test_gemini_init_event_returns_none() -> None:
    parser = GeminiActivityParser()
    raw = json.dumps({"type": "init", "session_id": "x", "model": "gemini-3-pro"})
    assert parser.parse(raw) is None


def test_gemini_dedups_tool_use_by_id() -> None:
    parser = GeminiActivityParser()
    raw = json.dumps(
        {
            "type": "tool_use",
            "tool_name": "Read",
            "tool_id": "t1",
            "parameters": {"file_path": "/x"},
        }
    )
    assert parser.parse(raw) is not None
    assert parser.parse(raw) is None  # dedup
