"""Tests for the factory_metrics read/filter module."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from factory_metrics import (  # noqa: E402
    aggregate_top_skills,
    aggregate_top_subagents,
    aggregate_top_tools,
    cost_by_phase,
    headline_metrics,
    issues_table,
    load_metrics,
)


def _write_metrics(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _now_minus(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()


def _event(**overrides) -> dict:
    base = {
        "timestamp": _now_minus(60),
        "issue": 1,
        "phase": "implement",
        "run_id": 1,
        "tokens": {"input": 100, "output": 50, "cache_read": 0, "cache_creation": 0},
        "tools": {"Read": 3},
        "skills": [],
        "subagents": 0,
        "duration_seconds": 30.0,
        "crashed": False,
    }
    base.update(overrides)
    return base


class TestLoadMetrics:
    def test_returns_empty_when_no_file(self, tmp_path: Path):
        result = load_metrics(tmp_path / "missing.jsonl")
        assert result == []

    def test_loads_all_events(self, tmp_path: Path):
        path = tmp_path / "factory_metrics.jsonl"
        _write_metrics(path, [_event(issue=1), _event(issue=2, phase="plan")])
        result = load_metrics(path)
        assert len(result) == 2

    def test_filters_by_time_range(self, tmp_path: Path):
        path = tmp_path / "factory_metrics.jsonl"
        _write_metrics(
            path,
            [
                _event(timestamp=_now_minus(60 * 24 * 10), issue=1),  # 10 days old
                _event(timestamp=_now_minus(60), issue=2),  # 1 hour old
            ],
        )
        result = load_metrics(path, time_range="7d")
        assert len(result) == 1
        assert result[0]["issue"] == 2

    def test_skips_malformed_lines(self, tmp_path: Path):
        path = tmp_path / "factory_metrics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_event(issue=1))
            + "\n"
            + "not valid json\n"
            + json.dumps(_event(issue=2))
            + "\n"
        )
        result = load_metrics(path)
        assert len(result) == 2


class TestHeadlineMetrics:
    def test_sums_tokens_runs_tools_subagents(self):
        events = [
            _event(
                tokens={
                    "input": 100,
                    "output": 50,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
                tools={"Read": 5},
                subagents=2,
            ),
            _event(
                tokens={
                    "input": 200,
                    "output": 80,
                    "cache_read": 50,
                    "cache_creation": 0,
                },
                tools={"Bash": 3},
                subagents=1,
            ),
        ]
        result = headline_metrics(events)
        assert result["total_tokens"] == 100 + 50 + 200 + 80 + 50
        assert result["total_runs"] == 2
        assert result["total_tool_invocations"] == 8
        assert result["total_subagents"] == 3
        # cache_hit_rate = cache_read / (input + cache_read) = 50 / 350
        assert result["cache_hit_rate"] == round(50 / (300 + 50), 4)

    def test_zero_runs_returns_zeros(self):
        result = headline_metrics([])
        assert result["total_tokens"] == 0
        assert result["total_runs"] == 0
        assert result["total_tool_invocations"] == 0
        assert result["total_subagents"] == 0
        assert result["cache_hit_rate"] == 0.0


class TestAggregateTopTools:
    def test_top_n_by_count(self):
        events = [
            _event(tools={"Read": 5, "Bash": 2}),
            _event(tools={"Read": 3, "Edit": 4}),
        ]
        result = aggregate_top_tools(events, top_n=2)
        assert result == [("Read", 8), ("Edit", 4)]


class TestAggregateTopSkills:
    def test_returns_first_try_pass_rate(self):
        events = [
            _event(
                skills=[
                    {"name": "diff-sanity", "passed": True, "attempts": 1},
                    {"name": "diff-sanity", "passed": False, "attempts": 2},
                ]
            ),
            _event(
                skills=[
                    {"name": "diff-sanity", "passed": True, "attempts": 1},
                ]
            ),
        ]
        result = aggregate_top_skills(events, top_n=5)
        assert len(result) == 1
        assert result[0]["name"] == "diff-sanity"
        assert result[0]["count"] == 3
        # 2 out of 3 passed on first try
        assert result[0]["first_try_pass_rate"] == round(2 / 3, 4)


class TestAggregateTopSubagents:
    def test_returns_empty_list_until_named_subagents_supported(self):
        """The factory_metrics event records subagents as an integer count
        only — no per-subagent name attribution. This function returns []
        until/unless the upstream collector starts recording subagent names.
        """
        events = [_event(subagents=3), _event(subagents=2)]
        assert aggregate_top_subagents(events, top_n=5) == []


class TestCostByPhase:
    def test_groups_tokens_by_phase(self):
        events = [
            _event(
                phase="implement",
                tokens={
                    "input": 100,
                    "output": 50,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
            ),
            _event(
                phase="implement",
                tokens={
                    "input": 50,
                    "output": 20,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
            ),
            _event(
                phase="plan",
                tokens={
                    "input": 30,
                    "output": 10,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
            ),
        ]
        result = cost_by_phase(events)
        assert result["implement"] == 100 + 50 + 50 + 20
        assert result["plan"] == 30 + 10


class TestIssuesTable:
    def test_returns_per_event_rows(self):
        events = [
            _event(
                issue=42,
                phase="implement",
                run_id=1,
                tokens={
                    "input": 100,
                    "output": 50,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
                tools={"Read": 5, "Bash": 2},
                skills=[
                    {"name": "diff-sanity", "passed": True, "attempts": 1},
                    {"name": "test-adequacy", "passed": False, "attempts": 2},
                ],
                duration_seconds=42.5,
                crashed=False,
            ),
        ]
        rows = issues_table(events)
        assert len(rows) == 1
        row = rows[0]
        assert row["issue"] == 42
        assert row["phase"] == "implement"
        assert row["run_id"] == 1
        assert row["tokens"] == 150
        assert row["tool_count"] == 7
        assert row["skill_pass_count"] == 1
        assert row["skill_total"] == 2
        assert row["duration_seconds"] == 42.5
        assert row["crashed"] is False
