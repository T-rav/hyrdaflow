"""Tests for trace data models."""

from __future__ import annotations

from hindsight import Bank
from models import (
    LifetimeStats,
    TraceSkillProfile,
    TraceSpanStats,
    TraceSummary,
    TraceTokenStats,
    TraceToolProfile,
)


class TestTraceSpanStats:
    def test_defaults(self) -> None:
        stats = TraceSpanStats(
            total_spans=10,
            total_turns=3,
            total_inference_calls=5,
            duration_seconds=42.5,
        )
        assert stats.total_spans == 10
        assert stats.total_turns == 3
        assert stats.total_inference_calls == 5
        assert stats.duration_seconds == 42.5


class TestTraceTokenStats:
    def test_defaults(self) -> None:
        stats = TraceTokenStats(
            prompt_tokens=1000,
            completion_tokens=500,
            cache_read_tokens=800,
            cache_creation_tokens=200,
            cache_hit_rate=0.44,
        )
        assert stats.prompt_tokens == 1000
        assert stats.cache_hit_rate == 0.44

    def test_zero_cache_hit_rate(self) -> None:
        stats = TraceTokenStats(
            prompt_tokens=1000,
            completion_tokens=500,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        )
        assert stats.cache_hit_rate == 0.0


class TestTraceToolProfile:
    def test_defaults(self) -> None:
        profile = TraceToolProfile(
            tool_counts={"Read": 10, "Bash": 5},
            tool_errors={"Bash": 1},
            total_invocations=15,
        )
        assert profile.tool_counts["Read"] == 10
        assert profile.tool_errors["Bash"] == 1
        assert profile.total_invocations == 15

    def test_empty_errors(self) -> None:
        profile = TraceToolProfile(
            tool_counts={"Read": 10}, tool_errors={}, total_invocations=10
        )
        assert profile.tool_errors == {}


class TestTraceSkillProfile:
    def test_defaults(self) -> None:
        profile = TraceSkillProfile(
            skill_counts={"brainstorming": 1, "tdd": 2},
            subagent_counts={"Explore": 3, "code-reviewer": 1},
            total_skills=3,
            total_subagents=4,
        )
        assert profile.skill_counts["tdd"] == 2
        assert profile.subagent_counts["Explore"] == 3

    def test_empty_profiles(self) -> None:
        profile = TraceSkillProfile(
            skill_counts={}, subagent_counts={}, total_skills=0, total_subagents=0
        )
        assert profile.total_skills == 0


class TestTraceSummary:
    def test_full_construction(self) -> None:
        summary = TraceSummary(
            issue_number=123,
            phase="implement",
            harvested_at="2026-04-03T12:00:00Z",
            trace_ids=["0xabc"],
            spans=TraceSpanStats(
                total_spans=10,
                total_turns=3,
                total_inference_calls=5,
                duration_seconds=42.5,
            ),
            tokens=TraceTokenStats(
                prompt_tokens=1000,
                completion_tokens=500,
                cache_read_tokens=800,
                cache_creation_tokens=200,
                cache_hit_rate=0.44,
            ),
            tools=TraceToolProfile(
                tool_counts={"Read": 10}, tool_errors={}, total_invocations=10
            ),
            skills=TraceSkillProfile(
                skill_counts={}, subagent_counts={}, total_skills=0, total_subagents=0
            ),
        )
        assert summary.issue_number == 123
        assert summary.phase == "implement"
        assert summary.spans.total_turns == 3
        assert summary.tokens.cache_hit_rate == 0.44

    def test_roundtrip_serialization(self) -> None:
        summary = TraceSummary(
            issue_number=42,
            phase="review",
            harvested_at="2026-04-03T12:00:00Z",
            trace_ids=["0x123"],
            spans=TraceSpanStats(
                total_spans=5,
                total_turns=2,
                total_inference_calls=3,
                duration_seconds=10.0,
            ),
            tokens=TraceTokenStats(
                prompt_tokens=500,
                completion_tokens=250,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                cache_hit_rate=0.0,
            ),
            tools=TraceToolProfile(
                tool_counts={"Edit": 3}, tool_errors={}, total_invocations=3
            ),
            skills=TraceSkillProfile(
                skill_counts={}, subagent_counts={}, total_skills=0, total_subagents=0
            ),
        )
        data = summary.model_dump()
        restored = TraceSummary.model_validate(data)
        assert restored == summary


class TestLifetimeStatsTraceFields:
    def test_trace_fields_default_zero(self) -> None:
        stats = LifetimeStats()
        assert stats.total_prompt_tokens == 0
        assert stats.total_completion_tokens == 0
        assert stats.total_cache_read_tokens == 0
        assert stats.total_cache_creation_tokens == 0
        assert stats.tool_invocation_counts == {}
        assert stats.tool_error_counts == {}
        assert stats.skill_invocation_counts == {}
        assert stats.subagent_invocation_counts == {}
        assert stats.total_traces_harvested == 0
        assert stats.total_spans_processed == 0
        assert stats.total_inference_calls == 0
        assert stats.total_agent_turns == 0

    def test_trace_fields_roundtrip(self) -> None:
        stats = LifetimeStats(
            total_prompt_tokens=5000,
            total_completion_tokens=2000,
            tool_invocation_counts={"Read": 100, "Bash": 50},
            skill_invocation_counts={"tdd": 10},
            subagent_invocation_counts={"Explore": 20},
        )
        data = stats.model_dump()
        restored = LifetimeStats.model_validate(data)
        assert restored.total_prompt_tokens == 5000
        assert restored.tool_invocation_counts == {"Read": 100, "Bash": 50}
        assert restored.skill_invocation_counts == {"tdd": 10}
        assert restored.subagent_invocation_counts == {"Explore": 20}


class TestTracingInsightsBank:
    def test_tracing_insights_bank_exists(self) -> None:
        assert Bank.TRACING_INSIGHTS == "hydraflow-tracing-insights"

    def test_tracing_insights_is_valid_bank(self) -> None:
        assert Bank.TRACING_INSIGHTS in list(Bank)
