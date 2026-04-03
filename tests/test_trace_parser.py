"""Tests for Monocle trace file parser."""

from __future__ import annotations

import json
from pathlib import Path

from trace_parser import parse_traces


def _make_workflow_span(
    trace_id: str = "0xabc",
    start: str = "2026-04-03T12:00:00Z",
    end: str = "2026-04-03T12:05:00Z",
) -> dict:
    return {
        "name": "workflow",
        "context": {"trace_id": trace_id, "span_id": "0x001", "trace_state": "[]"},
        "kind": "SpanKind.INTERNAL",
        "parent_id": None,
        "start_time": start,
        "end_time": end,
        "status": {"status_code": "OK"},
        "attributes": {"span.type": "workflow", "workflow.name": "claude-cli"},
        "events": [],
        "links": [],
        "resource": {"attributes": {}, "schema_url": ""},
    }


def _make_inference_span(
    prompt: int = 100,
    completion: int = 50,
    cache_read: int = 80,
    cache_creation: int = 20,
) -> dict:
    return {
        "name": "Claude Inference",
        "context": {"trace_id": "0xabc", "span_id": "0x010", "trace_state": "[]"},
        "kind": "SpanKind.INTERNAL",
        "parent_id": "0x002",
        "start_time": "2026-04-03T12:01:00Z",
        "end_time": "2026-04-03T12:01:01Z",
        "status": {"status_code": "OK"},
        "attributes": {
            "span.type": "inference",
            "gen_ai.request.model": "claude-opus-4-6",
        },
        "events": [
            {
                "name": "data.input",
                "timestamp": "2026-04-03T12:01:00Z",
                "attributes": {"input": "hello"},
            },
            {
                "name": "data.output",
                "timestamp": "2026-04-03T12:01:01Z",
                "attributes": {"response": "hi"},
            },
            {
                "name": "metadata",
                "timestamp": "2026-04-03T12:01:01Z",
                "attributes": {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "cache_read_tokens": cache_read,
                    "cache_creation_tokens": cache_creation,
                },
            },
        ],
        "links": [],
        "resource": {"attributes": {}, "schema_url": ""},
    }


def _make_turn_span(turn_number: int = 1) -> dict:
    return {
        "name": f"Claude Code - Turn {turn_number}",
        "context": {"trace_id": "0xabc", "span_id": "0x002", "trace_state": "[]"},
        "kind": "SpanKind.INTERNAL",
        "parent_id": "0x001",
        "start_time": "2026-04-03T12:01:00Z",
        "end_time": "2026-04-03T12:02:00Z",
        "status": {"status_code": "OK"},
        "attributes": {"span.type": "agentic.turn", "turn.number": turn_number},
        "events": [],
        "links": [],
        "resource": {"attributes": {}, "schema_url": ""},
    }


def _make_tool_span(
    tool_name: str = "Read", status: str = "OK", input_data: str = "{}"
) -> dict:
    return {
        "name": f"Tool: {tool_name}",
        "context": {"trace_id": "0xabc", "span_id": "0x020", "trace_state": "[]"},
        "kind": "SpanKind.INTERNAL",
        "parent_id": "0x002",
        "start_time": "2026-04-03T12:01:00Z",
        "end_time": "2026-04-03T12:01:00Z",
        "status": {"status_code": status},
        "attributes": {
            "span.type": "agentic.tool.invocation",
            "entity.1.name": tool_name,
        },
        "events": [
            {
                "name": "data.input",
                "timestamp": "2026-04-03T12:01:00Z",
                "attributes": {"input": input_data},
            },
            {
                "name": "data.output",
                "timestamp": "2026-04-03T12:01:00Z",
                "attributes": {"response": "ok"},
            },
        ],
        "links": [],
        "resource": {"attributes": {}, "schema_url": ""},
    }


def _write_trace_file(
    raw_dir: Path, spans: list[dict], name: str = "trace_01.json"
) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / name).write_text(json.dumps(spans))


class TestParseTraces:
    def test_basic_parse(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        spans = [
            _make_workflow_span(),
            _make_turn_span(1),
            _make_inference_span(),
            _make_tool_span("Read"),
        ]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=42, phase="implement")

        assert summary.issue_number == 42
        assert summary.phase == "implement"
        assert summary.spans.total_spans == 4
        assert summary.spans.total_turns == 1
        assert summary.spans.total_inference_calls == 1
        assert summary.spans.duration_seconds == 300.0  # 5 minutes
        assert summary.tokens.prompt_tokens == 100
        assert summary.tokens.completion_tokens == 50
        assert summary.tokens.cache_read_tokens == 80
        assert summary.tokens.cache_creation_tokens == 20
        assert summary.tools.tool_counts == {"Read": 1}
        assert summary.tools.total_invocations == 1
        assert summary.trace_ids == ["0xabc"]

    def test_multiple_inference_spans_aggregate(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        spans = [
            _make_workflow_span(),
            _make_inference_span(
                prompt=100, completion=50, cache_read=80, cache_creation=20
            ),
            _make_inference_span(
                prompt=200, completion=100, cache_read=160, cache_creation=40
            ),
        ]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=1, phase="plan")

        assert summary.tokens.prompt_tokens == 300
        assert summary.tokens.completion_tokens == 150
        assert summary.tokens.cache_read_tokens == 240
        assert summary.tokens.cache_creation_tokens == 60

    def test_cache_hit_rate_calculation(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        spans = [
            _make_workflow_span(),
            _make_inference_span(
                prompt=100, completion=50, cache_read=100, cache_creation=0
            ),
        ]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=1, phase="plan")

        # cache_hit_rate = 100 / (100 + 100) = 0.5
        assert summary.tokens.cache_hit_rate == 0.5

    def test_zero_tokens_gives_zero_cache_rate(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        spans = [
            _make_workflow_span(),
            _make_inference_span(
                prompt=0, completion=0, cache_read=0, cache_creation=0
            ),
        ]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=1, phase="plan")

        assert summary.tokens.cache_hit_rate == 0.0

    def test_tool_error_counted(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        spans = [_make_workflow_span(), _make_tool_span("Bash", status="ERROR")]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=1, phase="implement")

        assert summary.tools.tool_errors == {"Bash": 1}
        assert summary.tools.tool_counts == {"Bash": 1}

    def test_skill_invocation_detected(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        input_data = json.dumps({"skill": "brainstorming"})
        spans = [_make_workflow_span(), _make_tool_span("Skill", input_data=input_data)]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=1, phase="implement")

        assert summary.skills.skill_counts == {"brainstorming": 1}
        assert summary.skills.total_skills == 1

    def test_subagent_invocation_detected(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        input_data = json.dumps({"subagent_type": "Explore", "prompt": "find files"})
        spans = [_make_workflow_span(), _make_tool_span("Agent", input_data=input_data)]
        _write_trace_file(raw_dir, spans)

        summary = parse_traces(tmp_path, issue_number=1, phase="implement")

        assert summary.skills.subagent_counts == {"Explore": 1}
        assert summary.skills.total_subagents == 1

    def test_multiple_trace_files_merged(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        _write_trace_file(
            raw_dir,
            [_make_workflow_span(trace_id="0x111"), _make_tool_span("Read")],
            "trace_01.json",
        )
        _write_trace_file(
            raw_dir,
            [_make_workflow_span(trace_id="0x222"), _make_tool_span("Edit")],
            "trace_02.json",
        )

        summary = parse_traces(tmp_path, issue_number=1, phase="implement")

        assert set(summary.trace_ids) == {"0x111", "0x222"}
        assert summary.tools.tool_counts == {"Read": 1, "Edit": 1}
        assert summary.tools.total_invocations == 2

    def test_no_raw_dir_returns_empty_summary(self, tmp_path: Path) -> None:
        summary = parse_traces(tmp_path, issue_number=1, phase="plan")

        assert summary.spans.total_spans == 0
        assert summary.tokens.prompt_tokens == 0
        assert summary.tools.total_invocations == 0

    def test_malformed_json_skipped(self, tmp_path: Path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "bad.json").write_text("not json{{{")
        _write_trace_file(
            raw_dir, [_make_workflow_span(), _make_tool_span("Read")], "good.json"
        )

        summary = parse_traces(tmp_path, issue_number=1, phase="implement")

        assert summary.tools.tool_counts == {"Read": 1}
