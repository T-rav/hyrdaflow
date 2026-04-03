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


# --- Bead ops-audit-fixes-0sg: _summarize_tool gaps ---


class TestSummarizeTool:
    """Direct tests for _summarize_tool helper."""

    def test_write_tool(self):
        from activity_parser import _summarize_tool

        assert (
            _summarize_tool("Write", {"file_path": "src/new.py"})
            == "Writing src/new.py"
        )

    def test_glob_no_quotes(self):
        from activity_parser import _summarize_tool

        result = _summarize_tool("Glob", {"pattern": "**/*.py"})
        assert result == "Searching for **/*.py"
        assert "'" not in result  # Glob must NOT have quotes

    def test_grep_has_quotes(self):
        from activity_parser import _summarize_tool

        result = _summarize_tool("Grep", {"pattern": "def main"})
        assert result == "Searching for 'def main'"

    def test_bash_empty_command(self):
        from activity_parser import _summarize_tool

        assert _summarize_tool("Bash", {"command": ""}) == "Running command"
        assert _summarize_tool("Bash", {}) == "Running command"

    def test_unknown_tool_returns_name(self):
        from activity_parser import _summarize_tool

        assert _summarize_tool("CustomTool", {"foo": "bar"}) == "CustomTool"

    def test_case_insensitive(self):
        from activity_parser import _summarize_tool

        assert _summarize_tool("read", {"file_path": "x.py"}) == "Reading x.py"
        assert _summarize_tool("EDIT", {"file_path": "y.py"}) == "Editing y.py"


# --- Bead ops-audit-fixes-1f8: _truncate gaps ---


class TestTruncate:
    """Direct tests for _truncate helper."""

    def test_within_limit(self):
        from activity_parser import _truncate

        assert _truncate("hello", 10) == "hello"

    def test_exactly_at_limit(self):
        from activity_parser import _truncate

        assert _truncate("12345", 5) == "12345"

    def test_over_limit_adds_ellipsis(self):
        from activity_parser import _truncate

        result = _truncate("123456", 5)
        assert len(result) == 5
        assert result.endswith("\u2026")
        assert result == "1234\u2026"

    def test_empty_string(self):
        from activity_parser import _truncate

        assert _truncate("", 10) == ""


# --- Bead ops-audit-fixes-pgc: Claude edge cases ---


class TestClaudeActivityParserEdgeCases:
    """Edge cases for ClaudeActivityParser."""

    def test_mixed_content_tool_use_takes_priority(self):
        """When an event has both text and tool_use, tool_use wins."""
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_mix",
                    "content": [
                        {"type": "text", "text": "I'll read the file now."},
                        {
                            "type": "tool_use",
                            "id": "tool_mix",
                            "name": "Read",
                            "input": {"file_path": "a.py"},
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"
        assert result["tool_name"] == "Read"

    def test_empty_tool_id_still_emits(self):
        """Tool use with empty id should still emit (no dedup possible)."""
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_no_id",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"

    def test_non_dict_content_blocks_skipped(self):
        """Non-dict items in content array should not crash the parser."""
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_bad",
                    "content": [
                        "string_block",
                        None,
                        42,
                        {
                            "type": "text",
                            "text": "This is long enough to pass the threshold.",
                        },
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "text"

    def test_empty_tool_result_content(self):
        """tool_result with empty content should show '(empty)'."""
        parser = ClaudeActivityParser()
        line = json.dumps(
            {
                "type": "user",
                "message": {
                    "id": "msg_empty_result",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": ""},
                    ],
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert "(empty)" in result["summary"]

    def test_new_msg_id_resets_text_tracking(self):
        """A new message ID should reset text delta tracking."""
        parser = ClaudeActivityParser()
        text = "This is a sufficiently long text block for testing purposes here."
        line1 = json.dumps(
            {
                "type": "assistant",
                "message": {"id": "msg_a", "content": [{"type": "text", "text": text}]},
            }
        )
        line2 = json.dumps(
            {
                "type": "assistant",
                "message": {"id": "msg_b", "content": [{"type": "text", "text": text}]},
            }
        )
        result1 = parser.parse(line1)
        result2 = parser.parse(line2)
        # Both should emit because msg_id changed resets _prev_text_len
        assert result1 is not None
        assert result2 is not None

    def test_same_msg_id_deduplicates_text(self):
        """Same message ID with same text should not re-emit."""
        parser = ClaudeActivityParser()
        text = "This is a sufficiently long text block for testing purposes here."
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_same",
                    "content": [{"type": "text", "text": text}],
                },
            }
        )
        result1 = parser.parse(line)
        result2 = parser.parse(line)
        assert result1 is not None
        assert result2 is None  # no new delta


# --- Bead ops-audit-fixes-bvl: Codex edge cases ---


class TestCodexActivityParserEdgeCases:
    """Edge cases for CodexActivityParser."""

    def test_invalid_arguments_json(self):
        """function_call with unparseable arguments should not crash."""
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "item_bad_args",
                    "type": "function_call",
                    "name": "Bash",
                    "arguments": "not valid json {{{",
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["activity_type"] == "tool_call"
        assert result["tool_name"] == "Bash"

    def test_item_with_no_id(self):
        """Items without an id field should still be processed."""
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call",
                    "name": "Read",
                    "arguments": json.dumps({"file_path": "x.py"}),
                },
            }
        )
        result = parser.parse(line)
        assert result is not None
        assert result["tool_name"] == "Read"

    def test_item_with_no_id_no_dedup(self):
        """Two items without ids should both be processed (no dedup key)."""
        parser = CodexActivityParser()
        line = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "This message is long enough to pass the minimum text threshold.",
                },
            }
        )
        result1 = parser.parse(line)
        result2 = parser.parse(line)
        assert result1 is not None
        assert result2 is not None  # no id means no dedup
