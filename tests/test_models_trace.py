"""Tests for the new in-process tracing models."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import (  # noqa: E402
    SkillResultRecord,
    SubprocessTrace,
    ToolCallSpan,
    TraceSkillProfile,
    TraceSpanStats,
    TraceSummary,
    TraceTokenStats,
    TraceToolProfile,
)


class TestToolCallSpan:
    def test_minimal_construction(self):
        span = ToolCallSpan(
            tool_name="Read",
            started_at="2026-04-06T12:00:00Z",
            duration_ms=42,
            input_summary="Reading src/config.py",
            succeeded=True,
        )
        assert span.tool_name == "Read"
        assert span.error is None

    def test_failure_with_error(self):
        span = ToolCallSpan(
            tool_name="Bash",
            started_at="2026-04-06T12:00:00Z",
            duration_ms=100,
            input_summary="Running: pytest",
            succeeded=False,
            error="exit code 1",
        )
        assert span.succeeded is False
        assert span.error == "exit code 1"


class TestSkillResultRecord:
    def test_construction(self):
        rec = SkillResultRecord(
            skill_name="diff-sanity",
            passed=True,
            attempts=1,
            duration_seconds=8.3,
            blocking=True,
        )
        assert rec.skill_name == "diff-sanity"
        assert rec.passed is True


class TestSubprocessTrace:
    def test_round_trip_json(self):
        trace = SubprocessTrace(
            issue_number=42,
            phase="implement",
            source="implementer",
            run_id=1,
            subprocess_idx=0,
            backend="claude",
            started_at="2026-04-06T12:00:00Z",
            ended_at="2026-04-06T12:05:00Z",
            success=True,
            tokens=TraceTokenStats(
                prompt_tokens=1000,
                completion_tokens=500,
                cache_read_tokens=200,
                cache_creation_tokens=100,
                cache_hit_rate=0.16,
            ),
            tools=TraceToolProfile(
                tool_counts={"Read": 5, "Bash": 2},
                tool_errors={},
                total_invocations=7,
            ),
            tool_calls=[
                ToolCallSpan(
                    tool_name="Read",
                    started_at="2026-04-06T12:00:01Z",
                    duration_ms=15,
                    input_summary="Reading src/foo.py",
                    succeeded=True,
                ),
            ],
            skill_results=[],
            turn_count=4,
            inference_count=4,
        )
        as_json = trace.model_dump_json()
        rebuilt = SubprocessTrace.model_validate_json(as_json)
        assert rebuilt.tokens.prompt_tokens == 1000
        assert len(rebuilt.tool_calls) == 1


class TestTraceSummaryNewFields:
    def test_defaults_for_legacy_summaries(self):
        legacy_json = """
        {
            "issue_number": 42,
            "phase": "implement",
            "harvested_at": "2026-04-06T12:00:00Z",
            "trace_ids": [],
            "spans": {
                "total_spans": 0,
                "total_turns": 0,
                "total_inference_calls": 0,
                "duration_seconds": 0.0
            },
            "tokens": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_hit_rate": 0.0
            },
            "tools": {
                "tool_counts": {},
                "tool_errors": {},
                "total_invocations": 0
            },
            "skills": {
                "skill_counts": {},
                "subagent_counts": {},
                "total_skills": 0,
                "total_subagents": 0
            }
        }
        """
        summary = TraceSummary.model_validate_json(legacy_json)
        assert summary.run_id == 0
        assert summary.subprocess_count == 0
        assert summary.crashed is False

    def test_new_fields_round_trip(self):
        summary = TraceSummary(
            issue_number=42,
            phase="implement",
            harvested_at="2026-04-06T12:00:00Z",
            trace_ids=[],
            spans=TraceSpanStats(
                total_spans=10,
                total_turns=4,
                total_inference_calls=4,
                duration_seconds=120.0,
            ),
            tokens=TraceTokenStats(
                prompt_tokens=1000,
                completion_tokens=500,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                cache_hit_rate=0.0,
            ),
            tools=TraceToolProfile(tool_counts={}, tool_errors={}, total_invocations=0),
            skills=TraceSkillProfile(
                skill_counts={}, subagent_counts={}, total_skills=0, total_subagents=0
            ),
            run_id=2,
            subprocess_count=5,
            crashed=False,
            phase_run_started_at="2026-04-06T12:00:00Z",
            phase_run_ended_at="2026-04-06T12:02:00Z",
        )
        rebuilt = TraceSummary.model_validate_json(summary.model_dump_json())
        assert rebuilt.run_id == 2
        assert rebuilt.subprocess_count == 5
