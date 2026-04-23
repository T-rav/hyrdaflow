"""Tests for PrinciplesAuditStateMixin fields + accessors."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def test_state_data_has_principles_audit_fields(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    data = tracker._data  # type: ignore[attr-defined]
    assert data.managed_repos_onboarding_status == {}
    assert data.last_green_audit == {}
    assert data.principles_drift_attempts == {}


def test_onboarding_status_setter_roundtrip(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.set_onboarding_status("acme/widget", "pending")
    assert tracker.get_onboarding_status("acme/widget") == "pending"
    assert tracker.get_onboarding_status("nope/nope") is None
    tracker.set_onboarding_status("acme/widget", "ready")
    assert tracker.get_onboarding_status("acme/widget") == "ready"


def test_last_green_audit_roundtrip(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.set_last_green_audit("hydraflow-self", {"P1.1": "PASS", "P2.4": "PASS"})
    assert tracker.get_last_green_audit("hydraflow-self") == {
        "P1.1": "PASS",
        "P2.4": "PASS",
    }
    assert tracker.get_last_green_audit("missing") == {}


def test_drift_attempts_increment_and_reset(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    assert tracker.get_drift_attempts("acme/widget", "P1.1") == 0
    assert tracker.increment_drift_attempts("acme/widget", "P1.1") == 1
    assert tracker.increment_drift_attempts("acme/widget", "P1.1") == 2
    tracker.reset_drift_attempts("acme/widget", "P1.1")
    assert tracker.get_drift_attempts("acme/widget", "P1.1") == 0
