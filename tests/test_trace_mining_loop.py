"""Tests for TraceMiningLoop background worker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from models import (
    TraceSkillProfile,
    TraceSpanStats,
    TraceSummary,
    TraceTokenStats,
    TraceToolProfile,
)
from trace_mining_loop import TraceMiningLoop


def _make_config(tmp_path: Path) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo="owner/repo",
        data_root=str(tmp_path / "data"),
    )


def _make_loop_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=MagicMock(is_set=MagicMock(return_value=False)),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=None),
    )


def _make_summary(issue: int = 42, phase: str = "implement") -> TraceSummary:
    return TraceSummary(
        issue_number=issue,
        phase=phase,
        harvested_at="2026-04-03T12:00:00Z",
        trace_ids=["0xabc"],
        spans=TraceSpanStats(
            total_spans=10,
            total_turns=3,
            total_inference_calls=5,
            duration_seconds=300.0,
        ),
        tokens=TraceTokenStats(
            prompt_tokens=1000,
            completion_tokens=500,
            cache_read_tokens=800,
            cache_creation_tokens=200,
            cache_hit_rate=0.44,
        ),
        tools=TraceToolProfile(
            tool_counts={"Read": 10, "Bash": 5},
            tool_errors={"Bash": 1},
            total_invocations=15,
        ),
        skills=TraceSkillProfile(
            skill_counts={"tdd": 1},
            subagent_counts={"Explore": 2},
            total_skills=1,
            total_subagents=2,
        ),
    )


def _setup_parsed_dir(
    data_path: Path,
    issue: int,
    phase: str,
    summary: TraceSummary | None = None,
) -> Path:
    """Create a trace directory with raw files and optionally a summary."""
    trace_dir = data_path / "traces" / str(issue) / phase
    raw_dir = trace_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "trace.json").write_text(
        json.dumps(
            [
                {
                    "name": "workflow",
                    "context": {
                        "trace_id": "0xabc",
                        "span_id": "0x001",
                        "trace_state": "[]",
                    },
                    "kind": "SpanKind.INTERNAL",
                    "parent_id": None,
                    "start_time": "2026-04-03T12:00:00Z",
                    "end_time": "2026-04-03T12:05:00Z",
                    "status": {"status_code": "OK"},
                    "attributes": {
                        "span.type": "workflow",
                        "workflow.name": "claude-cli",
                    },
                    "events": [],
                    "links": [],
                    "resource": {"attributes": {}, "schema_url": ""},
                }
            ]
        )
    )
    if summary:
        (trace_dir / "summary.json").write_text(summary.model_dump_json())
    return trace_dir


class TestTraceMiningLoopParseStage:
    @pytest.mark.asyncio
    async def test_parses_unharvested_traces(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        data_path = config.data_root
        _setup_parsed_dir(data_path, 42, "implement")
        loop = TraceMiningLoop(
            config=config, state=MagicMock(), hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        trace_dir = data_path / "traces" / "42" / "implement"
        assert (trace_dir / ".parsed").exists()
        assert (trace_dir / "summary.json").exists()
        assert result is not None
        assert result["parsed"] >= 1

    @pytest.mark.asyncio
    async def test_skips_already_parsed(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        data_path = config.data_root
        trace_dir = _setup_parsed_dir(
            data_path, 42, "implement", summary=_make_summary()
        )
        (trace_dir / ".parsed").touch()
        (trace_dir / ".aggregated").touch()
        (trace_dir / ".synced").touch()
        loop = TraceMiningLoop(
            config=config, state=MagicMock(), hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        assert result is not None
        assert result["parsed"] == 0


class TestTraceMiningLoopAggregateStage:
    @pytest.mark.asyncio
    async def test_aggregates_into_lifetime_stats(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        data_path = config.data_root
        summary = _make_summary()
        trace_dir = _setup_parsed_dir(data_path, 42, "implement", summary=summary)
        (trace_dir / ".parsed").touch()

        state = MagicMock()
        state.get_lifetime_stats.return_value = MagicMock(
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_cache_read_tokens=0,
            total_cache_creation_tokens=0,
            tool_invocation_counts={},
            tool_error_counts={},
            skill_invocation_counts={},
            subagent_invocation_counts={},
            total_traces_harvested=0,
            total_spans_processed=0,
            total_inference_calls=0,
            total_agent_turns=0,
        )
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        assert (trace_dir / ".aggregated").exists()
        assert result is not None
        assert result["aggregated"] >= 1
        state.update_lifetime_stats.assert_called()


class TestTraceMiningLoopInsightsStage:
    @pytest.mark.asyncio
    async def test_syncs_to_hindsight(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        data_path = config.data_root
        summary = _make_summary()
        trace_dir = _setup_parsed_dir(data_path, 42, "implement", summary=summary)
        (trace_dir / ".parsed").touch()
        (trace_dir / ".aggregated").touch()

        hindsight = MagicMock()
        hindsight.retain_safe = AsyncMock()
        loop = TraceMiningLoop(
            config=config,
            state=MagicMock(),
            hindsight=hindsight,
            deps=_make_loop_deps(),
        )

        result = await loop._do_work()

        assert (trace_dir / ".synced").exists()
        assert result is not None
        assert result["synced"] >= 1
        assert hindsight.retain_safe.call_count >= 1

    @pytest.mark.asyncio
    async def test_skips_hindsight_when_not_configured(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        data_path = config.data_root
        summary = _make_summary()
        trace_dir = _setup_parsed_dir(data_path, 42, "implement", summary=summary)
        (trace_dir / ".parsed").touch()
        (trace_dir / ".aggregated").touch()

        loop = TraceMiningLoop(
            config=config, state=MagicMock(), hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        assert (trace_dir / ".synced").exists()
        assert result is not None
        assert result["synced"] >= 1


class TestTraceMiningLoopRestartSafety:
    @pytest.mark.asyncio
    async def test_idempotent_across_cycles(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        data_path = config.data_root
        _setup_parsed_dir(data_path, 42, "implement")

        state = MagicMock()
        state.get_lifetime_stats.return_value = MagicMock(
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_cache_read_tokens=0,
            total_cache_creation_tokens=0,
            tool_invocation_counts={},
            tool_error_counts={},
            skill_invocation_counts={},
            subagent_invocation_counts={},
            total_traces_harvested=0,
            total_spans_processed=0,
            total_inference_calls=0,
            total_agent_turns=0,
        )
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        # Run multiple cycles
        await loop._do_work()
        await loop._do_work()
        result = await loop._do_work()

        # All markers present, nothing left to do
        assert result is not None
        assert result["parsed"] == 0
        assert result["aggregated"] == 0
        assert result["synced"] == 0


class TestTraceMiningLoopNoTracesDir:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_traces_dir(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        loop = TraceMiningLoop(
            config=config, state=MagicMock(), hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        assert result == {"parsed": 0, "aggregated": 0, "synced": 0}
