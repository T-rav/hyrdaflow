"""Tests for escalation_gate.py."""

from __future__ import annotations

from escalation_gate import should_escalate_debug


def test_no_escalation_when_confident_and_low_risk() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is False
    assert decision.reasons == []


def test_escalation_on_low_confidence() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.2,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert "low_confidence" in decision.reasons


def test_escalation_on_parse_failure() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.8,
        confidence_threshold=0.7,
        parse_failed=True,
        retry_count=0,
        max_subskill_attempts=1,
        risk="medium",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert "precheck_parse_failed" in decision.reasons
