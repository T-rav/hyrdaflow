"""Tests for activity_parser — structured agent activity extraction."""

import json

from activity_parser import ClaudeActivityParser


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
