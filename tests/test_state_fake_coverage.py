"""Tests for FakeCoverageStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_last_known_roundtrip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    known = {"FakeGitHub": ["create_issue", "close_issue"]}
    st.set_fake_coverage_last_known(known)
    assert st.get_fake_coverage_last_known() == known


def test_attempt_counter(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    key = "FakeGitHub.create_issue:adapter-surface"
    assert st.get_fake_coverage_attempts(key) == 0
    assert st.inc_fake_coverage_attempts(key) == 1
    st.clear_fake_coverage_attempts(key)
    assert st.get_fake_coverage_attempts(key) == 0
