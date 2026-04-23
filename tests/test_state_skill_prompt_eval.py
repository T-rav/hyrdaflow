"""Tests for SkillPromptEvalStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_last_green_roundtrip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    snap = {"case_diff_shrink_001": "PASS", "case_scope_creep_002": "PASS"}
    st.set_skill_prompt_last_green(snap)
    assert st.get_skill_prompt_last_green() == snap


def test_attempt_counter(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_skill_prompt_attempts("case_x") == 0
    assert st.inc_skill_prompt_attempts("case_x") == 1
    assert st.inc_skill_prompt_attempts("case_x") == 2
    st.clear_skill_prompt_attempts("case_x")
    assert st.get_skill_prompt_attempts("case_x") == 0
