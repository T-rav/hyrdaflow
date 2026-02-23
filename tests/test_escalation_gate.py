"""Tests for escalation_gate.py."""

from __future__ import annotations

from escalation_gate import high_risk_diff_touched, should_escalate_debug


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


def test_escalation_on_high_risk_files() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="low",
        high_risk_files_touched=True,
    )
    assert decision.escalate is True
    assert "high_risk_files" in decision.reasons


# ---------------------------------------------------------------------------
# high_risk_diff_touched
# ---------------------------------------------------------------------------


def test_high_risk_diff_touched_auth_path() -> None:
    diff = "diff --git a/src/auth/login.py b/src/auth/login.py\n+pass"
    assert high_risk_diff_touched(diff) is True


def test_high_risk_diff_touched_security_path() -> None:
    diff = "diff --git a/src/security/tokens.py b/src/security/tokens.py\n+pass"
    assert high_risk_diff_touched(diff) is True


def test_high_risk_diff_touched_payment_path() -> None:
    diff = "diff --git a/src/payment/checkout.py b/src/payment/checkout.py\n+pass"
    assert high_risk_diff_touched(diff) is True


def test_high_risk_diff_touched_migration() -> None:
    diff = "diff --git a/db/migration_001.sql b/db/migration_001.sql\n+CREATE TABLE;"
    assert high_risk_diff_touched(diff) is True


def test_high_risk_diff_touched_infra_path() -> None:
    diff = "diff --git a/infra/deploy.yml b/infra/deploy.yml\n+step: deploy"
    assert high_risk_diff_touched(diff) is True


def test_high_risk_diff_touched_safe_diff() -> None:
    diff = "diff --git a/src/utils.py b/src/utils.py\n+def helper(): pass"
    assert high_risk_diff_touched(diff) is False


def test_high_risk_diff_touched_case_insensitive() -> None:
    diff = "diff --git a/src/Auth/Login.py b/src/Auth/Login.py\n+pass"
    assert high_risk_diff_touched(diff) is True
