"""Tests for TraceMiningLoop background worker (run-N layout)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from models import (
    SubprocessTrace,
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


def _make_mock_state() -> MagicMock:
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
    state.list_active_trace_runs.return_value = []
    return state


def _make_summary(
    issue: int = 42, phase: str = "implement", run_id: int = 1
) -> TraceSummary:
    return TraceSummary(
        issue_number=issue,
        phase=phase,
        harvested_at="2026-04-06T12:00:00Z",
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
        run_id=run_id,
        subprocess_count=1,
    )


def _make_subprocess_trace(
    issue: int = 42, phase: str = "implement", run_id: int = 1, subprocess_idx: int = 0
) -> SubprocessTrace:
    return SubprocessTrace(
        issue_number=issue,
        phase=phase,
        source="implementer",
        run_id=run_id,
        subprocess_idx=subprocess_idx,
        backend="claude",
        started_at="2026-04-06T12:00:00Z",
        ended_at="2026-04-06T12:01:00Z",
        success=True,
        tokens=TraceTokenStats(
            prompt_tokens=100,
            completion_tokens=50,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        ),
        tools=TraceToolProfile(
            tool_counts={"Read": 5}, tool_errors={}, total_invocations=5
        ),
        tool_calls=[],
        skill_results=[],
        turn_count=2,
        inference_count=2,
    )


def _write_run(
    data_path: Path,
    *,
    issue: int = 42,
    phase: str = "implement",
    run_id: int = 1,
    summary: TraceSummary | None = None,
    subprocess_trace: SubprocessTrace | None = None,
) -> Path:
    """Create a run-N/ directory with an optional summary.json and subprocess file."""
    run_dir = data_path / "traces" / str(issue) / phase / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if subprocess_trace is not None:
        (run_dir / "subprocess-0.json").write_text(
            subprocess_trace.model_dump_json(indent=2)
        )
    if summary is not None:
        (run_dir / "summary.json").write_text(summary.model_dump_json())
    return run_dir


class TestTraceMiningLoopAggregateStage:
    @pytest.mark.asyncio
    async def test_aggregates_into_lifetime_stats(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        summary = _make_summary()
        run_dir = _write_run(config.data_root, summary=summary)

        state = _make_mock_state()
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        assert (run_dir / ".aggregated").exists()
        assert result is not None
        assert result["aggregated"] >= 1
        state.update_lifetime_stats.assert_called()

    @pytest.mark.asyncio
    async def test_skips_already_aggregated(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        summary = _make_summary()
        run_dir = _write_run(config.data_root, summary=summary)
        (run_dir / ".aggregated").touch()
        (run_dir / ".synced").touch()

        state = _make_mock_state()
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()
        assert result is not None
        assert result["aggregated"] == 0


class TestTraceMiningLoopInsightsStage:
    @pytest.mark.asyncio
    async def test_syncs_to_hindsight(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        summary = _make_summary()
        run_dir = _write_run(config.data_root, summary=summary)
        (run_dir / ".aggregated").touch()

        hindsight = MagicMock()
        hindsight.retain_safe = AsyncMock()
        loop = TraceMiningLoop(
            config=config,
            state=_make_mock_state(),
            hindsight=hindsight,
            deps=_make_loop_deps(),
        )

        result = await loop._do_work()

        assert (run_dir / ".synced").exists()
        assert result is not None
        assert result["synced"] >= 1
        assert hindsight.retain_safe.call_count >= 1

    @pytest.mark.asyncio
    async def test_skips_hindsight_when_not_configured(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        summary = _make_summary()
        run_dir = _write_run(config.data_root, summary=summary)
        (run_dir / ".aggregated").touch()

        loop = TraceMiningLoop(
            config=config,
            state=_make_mock_state(),
            hindsight=None,
            deps=_make_loop_deps(),
        )

        result = await loop._do_work()

        assert (run_dir / ".synced").exists()
        assert result is not None
        assert result["synced"] >= 1


class TestTraceMiningLoopOrphanJanitor:
    @pytest.mark.asyncio
    async def test_finalizes_orphan_run(self, tmp_path: Path) -> None:
        """A run-N/ with subprocess files but no summary.json should be
        finalized with crashed=True if it's not in the active set."""
        config = _make_config(tmp_path)
        trace = _make_subprocess_trace()
        run_dir = _write_run(config.data_root, subprocess_trace=trace)

        state = _make_mock_state()
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        assert (run_dir / "summary.json").exists()
        assert (run_dir / ".finalized_orphan").exists()
        assert result is not None
        assert result["finalized"] == 1

    @pytest.mark.asyncio
    async def test_skips_active_runs(self, tmp_path: Path) -> None:
        """A run-N/ that's in the active set should NOT be finalized."""
        config = _make_config(tmp_path)
        trace = _make_subprocess_trace()
        run_dir = _write_run(config.data_root, subprocess_trace=trace)

        state = _make_mock_state()
        state.list_active_trace_runs.return_value = [(42, "implement", 1)]
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        result = await loop._do_work()

        # Still no summary.json and no finalized marker
        assert not (run_dir / "summary.json").exists()
        assert not (run_dir / ".finalized_orphan").exists()
        assert result is not None
        assert result["finalized"] == 0


class TestTraceMiningLoopRestartSafety:
    @pytest.mark.asyncio
    async def test_idempotent_across_cycles(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        summary = _make_summary()
        _write_run(config.data_root, summary=summary)

        state = _make_mock_state()
        loop = TraceMiningLoop(
            config=config, state=state, hindsight=None, deps=_make_loop_deps()
        )

        await loop._do_work()
        await loop._do_work()
        result = await loop._do_work()

        assert result is not None
        assert result["finalized"] == 0
        assert result["aggregated"] == 0
        assert result["synced"] == 0


class TestTraceMiningLoopNoTracesDir:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_traces_dir(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        loop = TraceMiningLoop(
            config=config,
            state=_make_mock_state(),
            hindsight=None,
            deps=_make_loop_deps(),
        )

        result = await loop._do_work()

        assert result == {"finalized": 0, "aggregated": 0, "synced": 0}
