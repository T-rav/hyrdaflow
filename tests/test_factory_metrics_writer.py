"""Test that write_phase_rollup appends to factory_metrics.jsonl."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from models import (  # noqa: E402
    SubprocessTrace,
    TraceTokenStats,
    TraceToolProfile,
)
from trace_rollup import write_phase_rollup  # noqa: E402


def _write_subprocess(tmp_path: Path, *, issue: int, run_id: int) -> None:
    trace = SubprocessTrace(
        issue_number=issue,
        phase="implement",
        source="implementer",
        run_id=run_id,
        subprocess_idx=0,
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
    out_dir = tmp_path / "traces" / str(issue) / "implement" / f"run-{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "subprocess-0.json").write_text(trace.model_dump_json(indent=2))


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.diagnostics_dir = tmp_path / "diagnostics"
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    return cfg


class TestFactoryMetricsWriter:
    def test_appends_event_after_rollup(self, config: MagicMock, tmp_path: Path):
        _write_subprocess(tmp_path, issue=42, run_id=1)
        write_phase_rollup(config=config, issue_number=42, phase="implement", run_id=1)

        assert config.factory_metrics_path.exists()
        events = [
            json.loads(line)
            for line in config.factory_metrics_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(events) == 1
        assert events[0]["issue"] == 42
        assert events[0]["run_id"] == 1
        assert events[0]["phase"] == "implement"
        assert events[0]["tokens"]["input"] == 100

    def test_appends_two_events_for_two_runs(self, config: MagicMock, tmp_path: Path):
        _write_subprocess(tmp_path, issue=42, run_id=1)
        write_phase_rollup(config=config, issue_number=42, phase="implement", run_id=1)
        _write_subprocess(tmp_path, issue=42, run_id=2)
        write_phase_rollup(config=config, issue_number=42, phase="implement", run_id=2)

        events = [
            json.loads(line)
            for line in config.factory_metrics_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(events) == 2
