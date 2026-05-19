"""Tests for RCBudgetStateMixin (spec §4.8)."""

from __future__ import annotations

from pathlib import Path

from models import RcBudgetDurationEntry
from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_set_and_get_duration_history(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    history_dicts = [
        {
            "run_id": 1,
            "created_at": "2026-04-01T00:00:00Z",
            "duration_s": 300,
            "conclusion": "success",
        },
        {
            "run_id": 2,
            "created_at": "2026-04-02T00:00:00Z",
            "duration_s": 480,
            "conclusion": "success",
        },
    ]
    st.set_rc_budget_duration_history(history_dicts)
    result = st.get_rc_budget_duration_history()
    assert len(result) == 2
    assert all(isinstance(e, RcBudgetDurationEntry) for e in result)
    assert result[0].run_id == 1
    assert result[0].created_at == "2026-04-01T00:00:00Z"
    assert result[0].duration_s == 300
    assert result[0].conclusion == "success"
    assert result[1].run_id == 2


def test_duration_history_persists_round_trip(tmp_path: Path) -> None:
    """Old on-disk JSON (plain dicts) must deserialise to RcBudgetDurationEntry."""
    import json

    state_file = tmp_path / "state.json"
    # Simulate a state file written by an older version of the code (plain dicts).
    old_state = {
        "schema_version": 1,
        "rc_budget_duration_history": [
            {
                "run_id": 42,
                "created_at": "2026-01-15T10:00:00Z",
                "duration_s": 600,
                "conclusion": "failure",
            }
        ],
    }
    state_file.write_text(json.dumps(old_state))
    st = StateTracker(state_file=state_file)
    history = st.get_rc_budget_duration_history()
    assert len(history) == 1
    assert isinstance(history[0], RcBudgetDurationEntry)
    assert history[0].run_id == 42
    assert history[0].duration_s == 600
    assert history[0].conclusion == "failure"


def test_inc_rc_budget_attempts_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_rc_budget_attempts("median") == 0
    assert st.inc_rc_budget_attempts("median") == 1
    assert st.inc_rc_budget_attempts("median") == 2
    assert st.get_rc_budget_attempts("spike") == 0


def test_clear_rc_budget_attempts(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_rc_budget_attempts("median")
    st.clear_rc_budget_attempts("median")
    assert st.get_rc_budget_attempts("median") == 0
