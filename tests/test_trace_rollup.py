"""Tests for trace_rollup — phase rollup writer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402

from models import (  # noqa: E402
    SkillResultRecord,
    SubprocessTrace,
    TraceTokenStats,
    TraceToolProfile,
)
from trace_rollup import write_phase_rollup  # noqa: E402


def _make_subprocess_trace(
    *,
    issue_number: int = 42,
    phase: str = "implement",
    run_id: int = 1,
    subprocess_idx: int = 0,
    success: bool = True,
    crashed: bool = False,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    tools: dict[str, int] | None = None,
    skills: list[SkillResultRecord] | None = None,
) -> SubprocessTrace:
    return SubprocessTrace(
        issue_number=issue_number,
        phase=phase,
        source="implementer",
        run_id=run_id,
        subprocess_idx=subprocess_idx,
        backend="claude",
        started_at="2026-04-06T12:00:00Z",
        ended_at="2026-04-06T12:01:00Z",
        success=success,
        crashed=crashed,
        tokens=TraceTokenStats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        ),
        tools=TraceToolProfile(
            tool_counts=tools or {},
            tool_errors={},
            total_invocations=sum((tools or {}).values()),
        ),
        tool_calls=[],
        skill_results=skills or [],
        turn_count=2,
        inference_count=2,
    )


def _write_subprocess_file(data_root: Path, trace: SubprocessTrace) -> None:
    out_dir = (
        data_root
        / "traces"
        / str(trace.issue_number)
        / trace.phase
        / f"run-{trace.run_id}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"subprocess-{trace.subprocess_idx}.json"
    out_path.write_text(trace.model_dump_json(indent=2))


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    return cfg


class TestWritePhaseRollup:
    def test_returns_none_when_no_subprocess_files(self, config: MagicMock):
        result = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )
        assert result is None

    def test_aggregates_token_sums(self, config: MagicMock, tmp_path: Path):
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(
                subprocess_idx=0, prompt_tokens=100, completion_tokens=50
            ),
        )
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(
                subprocess_idx=1, prompt_tokens=200, completion_tokens=80
            ),
        )

        result = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )

        assert result is not None
        assert result.tokens.prompt_tokens == 300
        assert result.tokens.completion_tokens == 130
        assert result.subprocess_count == 2
        assert result.run_id == 1

    def test_aggregates_tool_counts(self, config: MagicMock, tmp_path: Path):
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(subprocess_idx=0, tools={"Read": 5, "Bash": 2}),
        )
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(subprocess_idx=1, tools={"Read": 3, "Edit": 1}),
        )

        result = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )

        assert result is not None
        assert result.tools.tool_counts == {"Read": 8, "Bash": 2, "Edit": 1}

    def test_concatenates_skill_results(self, config: MagicMock, tmp_path: Path):
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(
                subprocess_idx=0,
                skills=[
                    SkillResultRecord(
                        skill_name="diff-sanity",
                        passed=True,
                        attempts=1,
                        duration_seconds=8.0,
                        blocking=True,
                    )
                ],
            ),
        )
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(
                subprocess_idx=1,
                skills=[
                    SkillResultRecord(
                        skill_name="test-adequacy",
                        passed=False,
                        attempts=2,
                        duration_seconds=12.0,
                        blocking=False,
                    )
                ],
            ),
        )

        result = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )

        assert result is not None
        assert result.skills.skill_counts == {"diff-sanity": 1, "test-adequacy": 1}
        assert result.skills.total_skills == 2

    def test_marks_crashed_if_any_subprocess_crashed(
        self, config: MagicMock, tmp_path: Path
    ):
        _write_subprocess_file(
            tmp_path, _make_subprocess_trace(subprocess_idx=0, success=True)
        )
        _write_subprocess_file(
            tmp_path,
            _make_subprocess_trace(subprocess_idx=1, success=False, crashed=True),
        )

        result = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )

        assert result is not None
        assert result.crashed is True

    def test_writes_summary_json(self, config: MagicMock, tmp_path: Path):
        _write_subprocess_file(tmp_path, _make_subprocess_trace())
        write_phase_rollup(config=config, issue_number=42, phase="implement", run_id=1)

        summary_path = (
            tmp_path / "traces" / "42" / "implement" / "run-1" / "summary.json"
        )
        assert summary_path.exists()
        loaded = json.loads(summary_path.read_text())
        assert loaded["run_id"] == 1
        assert loaded["issue_number"] == 42

    def test_writes_latest_pointer(self, config: MagicMock, tmp_path: Path):
        _write_subprocess_file(tmp_path, _make_subprocess_trace())
        write_phase_rollup(config=config, issue_number=42, phase="implement", run_id=1)

        latest_path = tmp_path / "traces" / "42" / "implement" / "latest"
        assert latest_path.exists()
        assert latest_path.read_text().strip() == "run-1"

    def test_idempotent(self, config: MagicMock, tmp_path: Path):
        _write_subprocess_file(tmp_path, _make_subprocess_trace())
        result_1 = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )
        result_2 = write_phase_rollup(
            config=config, issue_number=42, phase="implement", run_id=1
        )
        assert result_1 is not None
        assert result_2 is not None
        assert result_1.tokens.prompt_tokens == result_2.tokens.prompt_tokens
