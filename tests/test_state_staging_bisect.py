"""Tests for the StagingBisectStateMixin fields and accessors."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def test_state_data_has_six_new_staging_bisect_fields(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    data = tracker._data  # type: ignore[attr-defined]
    assert data.last_green_rc_sha == ""
    assert data.last_rc_red_sha == ""
    assert data.rc_cycle_id == 0
    assert data.auto_reverts_in_cycle == 0
    assert data.auto_reverts_successful == 0
    assert data.flake_reruns_total == 0
