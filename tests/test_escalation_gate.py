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
    assert decision.reasons == ["low_confidence"]


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
    assert decision.reasons == ["precheck_parse_failed"]


def test_no_escalation_when_gate_disabled() -> None:
    decision = should_escalate_debug(
        enabled=False,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is False
    assert decision.reasons == ["disabled"]


def test_disabled_gate_ignores_triggering_signals() -> None:
    decision = should_escalate_debug(
        enabled=False,
        confidence=0.2,
        confidence_threshold=0.7,
        parse_failed=True,
        retry_count=5,
        max_subskill_attempts=3,
        risk="critical",
        high_risk_files_touched=True,
    )
    assert decision.escalate is False
    assert decision.reasons == ["disabled"]


def test_escalation_on_high_risk() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="high",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert decision.reasons == ["risk_high"]


def test_escalation_on_critical_risk() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="critical",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert decision.reasons == ["risk_critical"]


def test_escalation_on_high_risk_files_touched() -> None:
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
    assert decision.reasons == ["high_risk_files"]


def test_escalation_on_retries_exhausted_at_max() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=3,
        max_subskill_attempts=3,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert decision.reasons == ["subskill_retries_exhausted"]


def test_escalation_on_retries_exhausted_above_max() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=5,
        max_subskill_attempts=3,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert decision.reasons == ["subskill_retries_exhausted"]


def test_no_escalation_when_retries_below_max() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=2,
        max_subskill_attempts=3,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is False
    assert decision.reasons == []


def test_all_signals_active_simultaneously_escalates_with_all_five_reasons() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.3,
        confidence_threshold=0.7,
        parse_failed=True,
        retry_count=5,
        max_subskill_attempts=3,
        risk="critical",
        high_risk_files_touched=True,
    )
    assert decision.escalate is True
    assert len(decision.reasons) == 5
    assert set(decision.reasons) == {
        "precheck_parse_failed",
        "low_confidence",
        "risk_critical",
        "high_risk_files",
        "subskill_retries_exhausted",
    }


def test_risk_field_normalized_ignoring_whitespace_and_case() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk=" High ",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert decision.reasons == ["risk_high"]


def test_no_escalation_on_medium_risk() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="medium",
        high_risk_files_touched=False,
    )
    assert decision.escalate is False
    assert decision.reasons == []


def test_escalation_when_max_attempts_is_zero() -> None:
    # max_subskill_attempts=0 is the config default, but all production callers
    # guard with `if max_subskill_attempts <= 0: return` before reaching this
    # function.  This test exercises the gate's own boundary arithmetic directly:
    # retry_count=0 >= max_subskill_attempts=0 is True, so the signal fires.
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=0,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is True
    assert decision.reasons == ["subskill_retries_exhausted"]


def test_no_escalation_when_optional_risk_and_files_omitted() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.9,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
    )
    assert decision.escalate is False
    assert decision.reasons == []


def test_no_escalation_at_exact_confidence_threshold() -> None:
    decision = should_escalate_debug(
        enabled=True,
        confidence=0.7,
        confidence_threshold=0.7,
        parse_failed=False,
        retry_count=0,
        max_subskill_attempts=1,
        risk="low",
        high_risk_files_touched=False,
    )
    assert decision.escalate is False
    assert decision.reasons == []


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
