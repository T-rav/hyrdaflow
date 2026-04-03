"""Tests for activity_parser — structured agent activity extraction."""

import json

from activity_parser import (
    ClaudeActivityParser,
    CodexActivityParser,
    PiActivityParser,
    get_activity_parser,
)


class TestClaudeActivityParserToolCall:
    """ClaudeActivityParser extracts TOOL_CALL from assistant events with tool_use blocks."""

    def test_read_tool_call(self):
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Read",
                            "input": {"file_path": "src/config.py"},
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"
        assert result["tool_name"] == "Read"
        assert "src/config.py" in result["summary"]

    def test_edit_tool_call(self):
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_2",
                            "name": "Edit",
                            "input": {
                                "file_path": "src/models.py",
                                "old_string": "foo",
                                "new_string": "bar",
                            },
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"
        assert result["tool_name"] == "Edit"
        assert "src/models.py" in result["summary"]

    def test_bash_tool_call(self):
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_3",
                            "name": "Bash",
                            "input": {
                                "command": "python -m pytest tests/ -v --tb=short"
                            },
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"
        assert result["tool_name"] == "Bash"
        assert "pytest" in result["summary"]

    def test_duplicate_tool_id_ignored(self):
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Read",
                            "input": {"file_path": "a.py"},
                        },
                    ],
                },
            }
        )
        result1 = parser.parse(line)
        result2 = parser.parse(line)
        assert result1 is not None
        assert result2 is None  # same tool_id, already seen


class TestClaudeActivityParserToolResult:
    """ClaudeActivityParser extracts TOOL_RESULT from user events."""

    def test_tool_result(self):
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "user",
                "message": {
                    "id": "msg_2",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool_1",
                            "content": "file contents here...",
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_result"
        assert result["detail"] is not None


class TestClaudeActivityParserText:
    """ClaudeActivityParser extracts TEXT from assistant text deltas."""

    def test_text_delta(self):
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_3",
                    "content": [
                        {
                            "type": "text",
                            "text": "I'll start by reading the configuration file to understand the current setup.",
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "text"
        assert "reading the configuration" in result["summary"]

    def test_short_text_ignored(self):
        """Text under 20 chars is noise (partial deltas) — skip it."""
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_4",
                    "content": [{"type": "text", "text": "OK"}],
                },
            }
        )
        result = parser.parse(line)
        assert result is None


class TestClaudeActivityParserError:
    """ClaudeActivityParser extracts ERROR from error events."""

    def test_error_event(self):
        parser = ClaudeActivityParser()
        line = json.dumps({"type": "error", "message": "Rate limit exceeded"})
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "error"
        assert "Rate limit" in result["summary"]


class TestClaudeActivityParserIgnored:
    """ClaudeActivityParser returns None for non-interesting events."""

    def test_session_event_ignored(self):
        parser = ClaudeActivityParser()
        line = json.dumps({"type": "session", "session_id": "abc"})
        assert parser.parse(line) is None

    def test_result_event_ignored(self):
        parser = ClaudeActivityParser()
        line = json.dumps({"type": "result", "result": "final output"})
        assert parser.parse(line) is None

    def test_invalid_json_ignored(self):
        parser = ClaudeActivityParser()
        assert parser.parse("not json") is None


class TestCodexActivityParserToolCall:
    """CodexActivityParser extracts activity from Codex item.completed events."""

    def test_function_call_item(self):
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "function_call",
                    "name": "Read",
                    "arguments": json.dumps({"file_path": "src/main.py"}),
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"
        assert result["tool_name"] == "Read"
        assert "src/main.py" in result["summary"]

    def test_agent_message_item(self):
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_2",
                    "type": "agent_message",
                    "text": "I will now implement the feature by modifying the config file.",
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "text"
        assert "implement" in result["summary"]

    def test_duplicate_item_id_ignored(self):
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_1",
                    "type": "function_call",
                    "name": "Read",
                    "arguments": json.dumps({"file_path": "a.py"}),
                },
            }
        )
        result1 = parser.parse(line)
        result2 = parser.parse(line)
        assert result1 is not None
        assert result2 is None

    def test_short_message_ignored(self):
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_3", "type": "agent_message", "text": "OK"},
            }
        )
        assert parser.parse(line) is None

    def test_turn_completed_ignored(self):
        parser = CodexActivityParser()
        line = json.dumps({"type": "turn.completed"})
        assert parser.parse(line) is None

    def test_invalid_json_ignored(self):
        parser = CodexActivityParser()
        assert parser.parse("not valid json") is None


class TestPiActivityParser:
    """PiActivityParser is a no-op stub."""

    def test_returns_none(self):
        parser = PiActivityParser()
        line = json.dumps(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "hello"},
            }
        )
        assert parser.parse(line) is None


class TestGetActivityParser:
    """get_activity_parser returns the correct parser for each backend."""

    def test_claude(self):
        assert isinstance(get_activity_parser("claude"), ClaudeActivityParser)

    def test_codex(self):
        assert isinstance(get_activity_parser("codex"), CodexActivityParser)

    def test_pi(self):
        assert isinstance(get_activity_parser("pi"), PiActivityParser)

    def test_unknown_returns_pi_stub(self):
        assert isinstance(get_activity_parser("unknown"), PiActivityParser)
