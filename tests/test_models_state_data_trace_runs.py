"""Test that StateData has the trace_runs field."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import StateData  # noqa: E402


class TestStateDataTraceRuns:
    def test_trace_runs_default_empty(self):
        data = StateData()
        assert data.trace_runs == {"active": {}, "next_run_id": {}}

    def test_trace_runs_round_trip(self):
        data = StateData()
        data.trace_runs["active"]["42:implement"] = {
            "run_id": 2,
            "started_at": "2026-04-06T12:00:00Z",
        }
        data.trace_runs["next_run_id"]["42:implement"] = 3

        as_json = data.model_dump_json()
        rebuilt = StateData.model_validate_json(as_json)
        assert rebuilt.trace_runs["active"]["42:implement"]["run_id"] == 2
        assert rebuilt.trace_runs["next_run_id"]["42:implement"] == 3
