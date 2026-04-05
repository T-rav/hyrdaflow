"""Tests for DiagnosticStateMixin."""

from __future__ import annotations

import pytest

from models import AttemptRecord, EscalationContext, Severity
from state import StateTracker


@pytest.fixture
def state(tmp_path):
    return StateTracker(tmp_path / "state.json")


class TestDiagnosticState:
    def test_escalation_context_round_trip(self, state) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        state.set_escalation_context(42, ctx)
        restored = state.get_escalation_context(42)
        assert restored is not None
        assert restored.cause == "CI failed"

    def test_escalation_context_missing_returns_none(self, state) -> None:
        assert state.get_escalation_context(999) is None

    def test_diagnostic_attempts(self, state) -> None:
        record = AttemptRecord(
            attempt_number=1,
            changes_made=True,
            error_summary="still fails",
            timestamp="2026-04-05T12:00:00Z",
        )
        state.add_diagnostic_attempt(42, record)
        attempts = state.get_diagnostic_attempts(42)
        assert len(attempts) == 1
        assert attempts[0].changes_made is True

    def test_diagnostic_attempts_append(self, state) -> None:
        for i in range(3):
            state.add_diagnostic_attempt(
                42,
                AttemptRecord(
                    attempt_number=i + 1,
                    changes_made=i % 2 == 0,
                    error_summary=f"attempt {i + 1}",
                    timestamp="2026-04-05T12:00:00Z",
                ),
            )
        assert len(state.get_diagnostic_attempts(42)) == 3

    def test_diagnostic_attempts_empty(self, state) -> None:
        assert state.get_diagnostic_attempts(999) == []

    def test_diagnosis_severity(self, state) -> None:
        state.set_diagnosis_severity(42, Severity.P2_FUNCTIONAL)
        assert state.get_diagnosis_severity(42) == Severity.P2_FUNCTIONAL

    def test_diagnosis_severity_missing_returns_none(self, state) -> None:
        assert state.get_diagnosis_severity(999) is None

    def test_clear_diagnostic_state(self, state) -> None:
        ctx = EscalationContext(cause="test", origin_phase="review")
        state.set_escalation_context(42, ctx)
        state.set_diagnosis_severity(42, Severity.P1_BLOCKING)
        state.add_diagnostic_attempt(
            42,
            AttemptRecord(
                attempt_number=1,
                changes_made=False,
                error_summary="fail",
                timestamp="2026-04-05T12:00:00Z",
            ),
        )
        state.clear_diagnostic_state(42)
        assert state.get_escalation_context(42) is None
        assert state.get_diagnosis_severity(42) is None
        assert state.get_diagnostic_attempts(42) == []
