"""Tests for diagnostic self-healing models."""

from __future__ import annotations

from models import AttemptRecord, DiagnosisResult, EscalationContext, Severity


class TestSeverity:
    def test_severity_values(self) -> None:
        assert Severity.P0_SECURITY == "P0"
        assert Severity.P1_BLOCKING == "P1"
        assert Severity.P2_FUNCTIONAL == "P2"
        assert Severity.P3_WIRING == "P3"
        assert Severity.P4_HOUSEKEEPING == "P4"

    def test_severity_ordering(self) -> None:
        ordered = sorted(Severity, key=lambda s: s.value)
        assert [s.value for s in ordered] == ["P0", "P1", "P2", "P3", "P4"]


class TestAttemptRecord:
    def test_round_trip(self) -> None:
        record = AttemptRecord(
            attempt_number=1,
            changes_made=True,
            error_summary="TypeError in line 42",
            timestamp="2026-04-05T12:00:00Z",
        )
        data = record.model_dump()
        restored = AttemptRecord.model_validate(data)
        assert restored.attempt_number == 1
        assert restored.changes_made is True
        assert restored.error_summary == "TypeError in line 42"


class TestEscalationContext:
    def test_minimal_context(self) -> None:
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        assert ctx.cause == "CI failed"
        assert ctx.ci_logs is None
        assert ctx.previous_attempts == []

    def test_full_context_round_trip(self) -> None:
        ctx = EscalationContext(
            cause="CI failed after 2 attempts",
            origin_phase="review",
            ci_logs="FAIL test_foo.py::test_bar",
            review_comments=["Fix the import"],
            pr_diff="diff --git a/x b/x",
            pr_number=42,
            code_scanning_alerts=["sql-injection in query.py"],
            previous_attempts=[
                AttemptRecord(
                    attempt_number=1,
                    changes_made=True,
                    error_summary="Still fails",
                    timestamp="2026-04-05T12:00:00Z",
                )
            ],
            agent_transcript="I tried changing the import...",
        )
        data = ctx.model_dump()
        restored = EscalationContext.model_validate(data)
        assert restored.pr_number == 42
        assert len(restored.previous_attempts) == 1
        assert restored.previous_attempts[0].changes_made is True


class TestDiagnosisResult:
    def test_round_trip(self) -> None:
        result = DiagnosisResult(
            root_cause="Method name mismatch: queue_depths vs get_queue_stats",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="Rename call on line 1226",
            human_guidance="Straightforward rename",
            affected_files=["src/dashboard_routes/_routes.py"],
        )
        data = result.model_dump()
        restored = DiagnosisResult.model_validate(data)
        assert restored.severity == Severity.P2_FUNCTIONAL
        assert restored.fixable is True
        assert len(restored.affected_files) == 1
