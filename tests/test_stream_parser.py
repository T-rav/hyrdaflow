"""Tests for dx/hydraflow/stream_parser.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from stream_parser import StreamParser, _summarize_input

# ===========================================================================
# _summarize_input — direct unit tests
# ===========================================================================


def test_summarize_input_bash_truncation():
    """Bash command longer than 120 chars is truncated to 120."""
    long_cmd = "x" * 200
    result = _summarize_input("Bash", {"command": long_cmd})
    assert len(result) == 120
    assert result == long_cmd[:120]


def test_summarize_input_generic_fallback_truncation():
    """Generic fallback with input > 120 chars adds '...' suffix."""
    long_val = "a" * 200
    result = _summarize_input("UnknownTool", {"data": long_val})
    assert result.endswith("...")
    assert len(result) == 123  # 120 + "..."


def test_summarize_input_generic_fallback_no_truncation():
    """Generic fallback with short input does not add '...' suffix."""
    result = _summarize_input("UnknownTool", {"x": 1})
    assert not result.endswith("...")


def test_summarize_input_task_truncation():
    """Task description longer than 120 chars is truncated."""
    long_desc = "d" * 200
    result = _summarize_input("Task", {"description": long_desc})
    assert len(result) == 120


def test_summarize_input_task_with_agent_truncation():
    """Task with agent and long description is truncated to 120 total."""
    long_desc = "d" * 200
    result = _summarize_input(
        "Task", {"description": long_desc, "subagent_type": "Explore"}
    )
    assert len(result) == 120
    assert result.startswith("Explore: ")


def test_summarize_input_edit_shows_only_file_path():
    """Edit summary shows only file_path, not old/new text."""
    result = _summarize_input(
        "Edit",
        {
            "file_path": "/src/foo.py",
            "old_text": "old stuff",
            "new_text": "new stuff",
        },
    )
    assert result == "/src/foo.py"


def test_summarize_input_write_shows_only_file_path():
    """Write summary shows only file_path, not content."""
    result = _summarize_input(
        "Write",
        {
            "file_path": "/src/bar.py",
            "content": "lots of code",
        },
    )
    assert result == "/src/bar.py"


def test_summarize_input_glob_shows_pattern():
    """Glob summary shows the pattern."""
    result = _summarize_input("Glob", {"pattern": "**/*.ts"})
    assert result == "**/*.ts"


# ===========================================================================
# StreamParser (stateful) — delta tracking
# ===========================================================================


class TestStreamParserDelta:
    """StreamParser deduplicates cumulative assistant message events."""

    def test_first_message_returns_text(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello"}],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert display == "Hello"

    def test_cumulative_message_returns_only_delta(self):
        parser = StreamParser()
        e1 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello"}],
            },
        }
        e2 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello world"}],
            },
        }
        parser.parse(json.dumps(e1))
        display, _ = parser.parse(json.dumps(e2))
        assert display == "world"

    def test_same_text_returns_empty(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Hello"}],
            },
        }
        parser.parse(json.dumps(event))
        display, _ = parser.parse(json.dumps(event))
        assert display == ""

    def test_new_turn_resets_text_tracking(self):
        parser = StreamParser()
        e1 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Turn 1 text"}],
            },
        }
        e2 = {
            "type": "assistant",
            "message": {
                "id": "msg_2",
                "content": [{"type": "text", "text": "Turn 2 text"}],
            },
        }
        parser.parse(json.dumps(e1))
        display, _ = parser.parse(json.dumps(e2))
        assert display == "Turn 2 text"

    def test_tool_use_shown_once(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Read",
                        "input": {"file_path": "/a.py"},
                    },
                ],
            },
        }
        d1, _ = parser.parse(json.dumps(event))
        d2, _ = parser.parse(json.dumps(event))
        assert "Read" in d1
        assert d2 == ""  # already seen this tool_id

    def test_cumulative_message_with_new_tool(self):
        """Second snapshot adds a tool_use — only the tool is new."""
        parser = StreamParser()
        e1 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": "Let me look"}],
            },
        }
        e2 = {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {"type": "text", "text": "Let me look"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Glob",
                        "input": {"pattern": "**/*.py"},
                    },
                ],
            },
        }
        parser.parse(json.dumps(e1))
        display, _ = parser.parse(json.dumps(e2))
        assert "Glob" in display
        assert "Let me look" not in display  # text unchanged

    def test_result_event_still_captured(self):
        parser = StreamParser()
        event = {"type": "result", "result": "Final output"}
        display, result = parser.parse(json.dumps(event))
        assert display == ""
        assert result == "Final output"

    def test_plain_text_passes_through(self):
        parser = StreamParser()
        display, result = parser.parse("not json")
        assert display == "not json"
        assert result is None

    def test_user_tool_result_shown(self):
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "File contents here...",
                    },
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert "File contents here" in display

    def test_user_message_multiple_tool_results(self):
        """Only the first tool_result's preview appears (early return)."""
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "First result",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
                        "content": "Second result",
                    },
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert "First result" in display
        assert "Second result" not in display

    def test_codex_item_completed_agent_message(self):
        parser = StreamParser()
        event = {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": "hello"},
        }
        display, result = parser.parse(json.dumps(event))
        assert display == "hello"
        assert result is None

    def test_codex_turn_completed_uses_last_agent_message(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_1", "type": "agent_message", "text": "done"},
                }
            )
        )
        display, result = parser.parse(json.dumps({"type": "turn.completed"}))
        assert display == ""
        assert result == "done"

    def test_user_message_non_tool_result_content(self):
        """User event with only text content (no tool_result) returns empty."""
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "Some user text"},
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert display == ""

    def test_user_message_empty_content(self):
        """User event with empty content list returns empty."""
        parser = StreamParser()
        event = {
            "type": "user",
            "message": {"content": []},
        }
        display, _ = parser.parse(json.dumps(event))
        assert display == ""

    def test_user_tool_result_long_content_truncated(self):
        """User tool_result content > 80 chars is truncated with ellipsis."""
        parser = StreamParser()
        long_content = "x" * 100
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": long_content,
                    },
                ],
            },
        }
        display, _ = parser.parse(json.dumps(event))
        assert "…" in display
        # The preview part (after "    ← ") should be 80 chars + ellipsis
        preview = display.replace("    ← ", "")
        assert len(preview) == 81  # 80 chars + "…"

    def test_captures_usage_from_result_event(self):
        parser = StreamParser()
        event = {
            "type": "result",
            "result": "done",
            "usage": {
                "input_tokens": 120,
                "output_tokens": 45,
                "cache_creation_input_tokens": 30,
                "cache_read_input_tokens": 10,
                "total_tokens": 165,
            },
        }
        parser.parse(json.dumps(event))
        usage = parser.usage_totals
        assert usage["input_tokens"] == 120
        assert usage["output_tokens"] == 45
        assert usage["cache_creation_input_tokens"] == 30
        assert usage["cache_read_input_tokens"] == 10
        assert usage["total_tokens"] == 165

    def test_usage_tracks_max_for_cumulative_events(self):
        parser = StreamParser()
        parser.parse(
            json.dumps(
                {
                    "type": "assistant",
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                    "message": {"id": "m1", "content": [{"type": "text", "text": "a"}]},
                }
            )
        )
        parser.parse(
            json.dumps(
                {
                    "type": "assistant",
                    "usage": {"input_tokens": 90, "output_tokens": 15},
                    "message": {
                        "id": "m1",
                        "content": [{"type": "text", "text": "ab"}],
                    },
                }
            )
        )
        usage = parser.usage_totals
        assert usage["input_tokens"] == 100
        assert usage["output_tokens"] == 20

    def test_usage_ignores_token_like_keys_in_tool_payloads(self):
        parser = StreamParser()
        event = {
            "type": "assistant",
            "message": {
                "id": "m2",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "Read",
                        "input": {"input_tokens": 9999, "total_tokens": 9999},
                    }
                ],
            },
        }
        parser.parse(json.dumps(event))
        usage = parser.usage_totals
        assert usage["input_tokens"] == 0
        assert usage["total_tokens"] == 0
