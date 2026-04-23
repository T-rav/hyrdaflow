"""Tests for WikiRotDetectorStateMixin (spec §4.9)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_get_returns_zero_when_unset(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_wiki_rot_attempts("hydra/hydraflow:src/foo.py:bar") == 0


def test_inc_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    key = "hydra/hydraflow:src/foo.py:bar"
    assert st.inc_wiki_rot_attempts(key) == 1
    assert st.inc_wiki_rot_attempts(key) == 2
    assert st.inc_wiki_rot_attempts(key) == 3
    assert st.get_wiki_rot_attempts("other:key") == 0


def test_clear_resets_single_key(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_wiki_rot_attempts("a")
    st.inc_wiki_rot_attempts("b")
    st.clear_wiki_rot_attempts("a")
    assert st.get_wiki_rot_attempts("a") == 0
    assert st.get_wiki_rot_attempts("b") == 1


def test_persists_across_instances(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.inc_wiki_rot_attempts("persist")
    st2 = _tracker(tmp_path)
    assert st2.get_wiki_rot_attempts("persist") == 1
