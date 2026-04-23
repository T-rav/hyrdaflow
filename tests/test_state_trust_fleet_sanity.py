"""Tests for TrustFleetSanityStateMixin (spec §12.1)."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_get_returns_zero_when_unset(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_trust_fleet_sanity_attempts("issues_per_hour:ci_monitor") == 0


def test_inc_is_monotonic(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    key = "tick_error_ratio:rc_budget"
    assert st.inc_trust_fleet_sanity_attempts(key) == 1
    assert st.inc_trust_fleet_sanity_attempts(key) == 2
    assert st.get_trust_fleet_sanity_attempts("other:key") == 0


def test_clear_resets_single_key(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.inc_trust_fleet_sanity_attempts("a:one")
    st.inc_trust_fleet_sanity_attempts("b:two")
    st.clear_trust_fleet_sanity_attempts("a:one")
    assert st.get_trust_fleet_sanity_attempts("a:one") == 0
    assert st.get_trust_fleet_sanity_attempts("b:two") == 1


def test_last_run_roundtrips(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_trust_fleet_sanity_last_run() is None
    st.set_trust_fleet_sanity_last_run("2026-04-22T12:00:00+00:00")
    assert st.get_trust_fleet_sanity_last_run() == "2026-04-22T12:00:00+00:00"


def test_last_seen_counts_roundtrips(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.set_trust_fleet_sanity_last_seen_count(
        "ci_monitor",
        issues_filed_total=5,
        observed_at="2026-04-22T12:00:00+00:00",
    )
    snap = st.get_trust_fleet_sanity_last_seen_counts()
    assert snap["ci_monitor"]["issues_filed_total"] == 5
    assert snap["ci_monitor"]["observed_at"] == "2026-04-22T12:00:00+00:00"


def test_persists_across_instances(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.inc_trust_fleet_sanity_attempts("persist:key")
    st2 = _tracker(tmp_path)
    assert st2.get_trust_fleet_sanity_attempts("persist:key") == 1
