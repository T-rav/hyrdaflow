"""Tests for the DiagnosticLoop background worker."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from diagnostic_loop import DiagnosticLoop, _format_diagnosis_comment, _format_severity
from events import EventType
from models import AttemptRecord, DiagnosisResult, EscalationContext, Severity
from tests.helpers import make_bg_loop_deps


def _make_diagnosis(
    *,
    fixable: bool = True,
    severity: Severity = Severity.P2_FUNCTIONAL,
    root_cause: str = "Test root cause",
    fix_plan: str = "Apply the fix",
    human_guidance: str = "Check the logs",
    affected_files: list[str] | None = None,
) -> DiagnosisResult:
    """Build a DiagnosisResult with test-friendly defaults."""
    return DiagnosisResult(
        root_cause=root_cause,
        severity=severity,
        fixable=fixable,
        fix_plan=fix_plan,
        human_guidance=human_guidance,
        affected_files=["src/foo.py"] if affected_files is None else affected_files,
    )


def _make_context(
    *,
    cause: str = "ci_failure",
    origin_phase: str = "review",
) -> EscalationContext:
    """Build an EscalationContext with test-friendly defaults."""
    return EscalationContext(cause=cause, origin_phase=origin_phase)


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
) -> tuple[DiagnosticLoop, MagicMock, MagicMock, MagicMock]:
    """Build a DiagnosticLoop with test-friendly defaults.

    Returns (loop, runner_mock, prs_mock, state_mock).
    """
    deps = make_bg_loop_deps(tmp_path, enabled=enabled)

    runner = MagicMock()
    runner.diagnose = AsyncMock(return_value=_make_diagnosis())
    runner.fix = AsyncMock(return_value=(True, "fixed successfully"))

    prs = MagicMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    prs.post_comment = AsyncMock()
    prs.swap_pipeline_labels = AsyncMock()

    state = MagicMock()
    state.get_escalation_context = MagicMock(return_value=_make_context())
    state.get_diagnostic_attempts = MagicMock(return_value=[])
    state.add_diagnostic_attempt = MagicMock()
    state.set_diagnosis_severity = MagicMock()

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
    )
    return loop, runner, prs, state


class TestDiagnosticLoopInterval:
    """Tests for _get_default_interval."""

    def test_returns_config_value(self, tmp_path: Path) -> None:
        """_get_default_interval returns the configured diagnostic_interval."""
        loop, _, _, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == loop._config.diagnostic_interval


class TestDiagnosticLoopDoWork:
    """Tests for _do_work."""

    @pytest.mark.asyncio
    async def test_empty_issue_list_returns_zero_counts(self, tmp_path: Path) -> None:
        """When no issues are labeled, _do_work returns zeroed stats."""
        loop, _, prs, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = []

        result = await loop._do_work()

        assert result == {"processed": 0, "fixed": 0, "escalated": 0}

    @pytest.mark.asyncio
    async def test_fetches_issues_using_diagnose_label(self, tmp_path: Path) -> None:
        """_do_work fetches issues using the first element of diagnose_label."""
        loop, _, prs, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = []

        await loop._do_work()

        prs.list_issues_by_label.assert_awaited_once_with(
            loop._config.diagnose_label[0]
        )

    @pytest.mark.asyncio
    async def test_fixed_issue_counts_as_fixed(self, tmp_path: Path) -> None:
        """When fix succeeds, the fixed counter increments."""
        loop, runner, prs, state = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = [
            {"number": 42, "title": "Bug", "body": "It's broken"}
        ]
        runner.fix.return_value = (True, "ok")

        result = await loop._do_work()

        assert result is not None
        assert result["fixed"] == 1
        assert result["escalated"] == 0
        assert result["processed"] == 1

    @pytest.mark.asyncio
    async def test_unfixable_issue_counts_as_escalated(self, tmp_path: Path) -> None:
        """When diagnosis says not fixable, the escalated counter increments."""
        loop, runner, prs, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = [
            {"number": 42, "title": "Bug", "body": "It's broken"}
        ]
        runner.diagnose.return_value = _make_diagnosis(fixable=False)

        result = await loop._do_work()

        assert result is not None
        assert result["escalated"] == 1
        assert result["fixed"] == 0

    @pytest.mark.asyncio
    async def test_stops_processing_when_stop_event_set(self, tmp_path: Path) -> None:
        """When stop_event is set, no further issues are processed."""
        loop, runner, prs, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = [
            {"number": 1, "title": "A", "body": ""},
            {"number": 2, "title": "B", "body": ""},
        ]
        loop._stop_event.set()

        result = await loop._do_work()

        assert result is not None
        assert result["processed"] == 0
        runner.diagnose.assert_not_awaited()


class TestProcessIssueNoContext:
    """_process_issue escalates when no escalation context is found."""

    @pytest.mark.asyncio
    async def test_escalates_to_hitl_when_context_missing(self, tmp_path: Path) -> None:
        """When no escalation context exists, issue goes straight to HITL."""
        loop, runner, prs, state = _make_loop(tmp_path)
        state.get_escalation_context.return_value = None

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "escalated"
        prs.post_comment.assert_awaited_once()
        comment_body = prs.post_comment.call_args[0][1]
        assert "Diagnostic Analysis" in comment_body
        assert "No escalation context" in comment_body
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.hitl_label[0]
        )
        runner.diagnose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publishes_escalated_event_on_missing_context(
        self, tmp_path: Path
    ) -> None:
        """A DIAGNOSTIC_UPDATE event is published when escalating for missing context."""
        loop, _, _, state = _make_loop(tmp_path)
        state.get_escalation_context.return_value = None

        await loop._process_issue(42, "Title", "Body")

        events = [
            e for e in loop._bus.get_history() if e.type == EventType.DIAGNOSTIC_UPDATE
        ]
        assert any(e.data.get("status") == "escalated" for e in events)


class TestProcessIssueNotFixable:
    """_process_issue escalates when diagnosis says not fixable."""

    @pytest.mark.asyncio
    async def test_escalates_to_hitl_when_not_fixable(self, tmp_path: Path) -> None:
        """When diagnosis.fixable is False, issue is escalated to HITL."""
        loop, runner, prs, state = _make_loop(tmp_path)
        runner.diagnose.return_value = _make_diagnosis(fixable=False)

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "escalated"
        prs.post_comment.assert_awaited_once()
        comment_body = prs.post_comment.call_args[0][1]
        assert "Diagnostic Analysis" in comment_body
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.hitl_label[0]
        )
        # Fix should NOT be attempted
        runner.fix.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_severity_stored_even_when_not_fixable(self, tmp_path: Path) -> None:
        """Severity is persisted to state even when the issue cannot be fixed."""
        loop, runner, _, state = _make_loop(tmp_path)
        runner.diagnose.return_value = _make_diagnosis(
            fixable=False, severity=Severity.P0_SECURITY
        )

        await loop._process_issue(42, "Title", "Body")

        state.set_diagnosis_severity.assert_called_once_with(42, Severity.P0_SECURITY)


class TestProcessIssueSuccessfulFix:
    """_process_issue transitions to review on successful fix."""

    @pytest.mark.asyncio
    async def test_transitions_to_review_on_success(self, tmp_path: Path) -> None:
        """Successful fix transitions the issue label to review."""
        loop, runner, prs, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "fixed"
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.review_label[0]
        )

    @pytest.mark.asyncio
    async def test_posts_success_comment_on_fix(self, tmp_path: Path) -> None:
        """A success comment is posted when fix succeeds."""
        loop, runner, prs, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")

        await loop._process_issue(42, "Title", "Body")

        prs.post_comment.assert_awaited_once()
        comment_body = prs.post_comment.call_args[0][1]
        assert "Diagnostic Fix Applied" in comment_body
        assert "Diagnostic Analysis" in comment_body

    @pytest.mark.asyncio
    async def test_records_attempt_on_success(self, tmp_path: Path) -> None:
        """An AttemptRecord is written to state on successful fix."""
        loop, runner, _, state = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")

        await loop._process_issue(42, "Title", "Body")

        state.add_diagnostic_attempt.assert_called_once()
        record: AttemptRecord = state.add_diagnostic_attempt.call_args[0][1]
        assert record.attempt_number == 1
        assert record.changes_made is True
        assert record.error_summary == ""

    @pytest.mark.asyncio
    async def test_publishes_fixed_event(self, tmp_path: Path) -> None:
        """A DIAGNOSTIC_UPDATE 'fixed' event is published on successful fix."""
        loop, runner, _, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")

        await loop._process_issue(42, "Title", "Body")

        events = [
            e for e in loop._bus.get_history() if e.type == EventType.DIAGNOSTIC_UPDATE
        ]
        assert any(e.data.get("status") == "fixed" for e in events)


class TestProcessIssueMaxAttemptsExhausted:
    """_process_issue escalates to HITL after max attempts."""

    @pytest.mark.asyncio
    async def test_escalates_when_attempts_at_max(self, tmp_path: Path) -> None:
        """When attempts already equal max_diagnostic_attempts, escalate without fixing."""
        loop, runner, prs, state = _make_loop(tmp_path)
        # Simulate max attempts already recorded
        max_attempts = loop._config.max_diagnostic_attempts
        state.get_diagnostic_attempts.return_value = [
            AttemptRecord(
                attempt_number=i + 1,
                changes_made=False,
                error_summary="failed",
                timestamp="2026-01-01T00:00:00+00:00",
            )
            for i in range(max_attempts)
        ]

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "escalated"
        runner.fix.assert_not_awaited()
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.hitl_label[0]
        )

    @pytest.mark.asyncio
    async def test_escalates_after_final_failing_attempt(self, tmp_path: Path) -> None:
        """When fix fails and no attempts remain, escalate to HITL."""
        loop, runner, prs, state = _make_loop(tmp_path)
        # max_diagnostic_attempts defaults to 2; simulate 0 previous attempts
        # so this will be attempt 1; then after recording, 1 < 2 so it retries
        # To test exhaustion: set max to 1 via state side effect
        max_attempts = loop._config.max_diagnostic_attempts

        # After recording attempt, return max_attempts worth of records
        def get_attempts_side_effect(issue_number: int) -> list[AttemptRecord]:
            return [
                AttemptRecord(
                    attempt_number=i + 1,
                    changes_made=False,
                    error_summary="failed",
                    timestamp="2026-01-01T00:00:00+00:00",
                )
                for i in range(max_attempts)
            ]

        state.get_diagnostic_attempts.side_effect = [
            [],  # First call: before fix — 0 attempts
            get_attempts_side_effect(42),  # Second call: after recording
        ]
        runner.fix.return_value = (False, "Could not fix")

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "escalated"
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.hitl_label[0]
        )

    @pytest.mark.asyncio
    async def test_records_failed_attempt(self, tmp_path: Path) -> None:
        """A failed fix attempt is recorded in state."""
        loop, runner, _, state = _make_loop(tmp_path)
        runner.fix.return_value = (False, "error: test failed")

        await loop._process_issue(42, "Title", "Body")

        state.add_diagnostic_attempt.assert_called_once()
        record: AttemptRecord = state.add_diagnostic_attempt.call_args[0][1]
        assert record.changes_made is False
        assert "error" in record.error_summary or record.error_summary != ""


class TestFormatHelpers:
    """Unit tests for formatting helper functions."""

    def test_format_severity_known_value(self) -> None:
        """Known severity values return human-readable labels."""
        assert "P2" in _format_severity(Severity.P2_FUNCTIONAL)
        assert "Functional" in _format_severity(Severity.P2_FUNCTIONAL)

    def test_format_severity_all_known_values(self) -> None:
        """All severity values produce a non-empty label."""
        for sev in Severity:
            label = _format_severity(sev)
            assert label
            assert sev.value in label

    def test_format_diagnosis_comment_structure(self) -> None:
        """Diagnosis comment includes all required sections."""
        diagnosis = _make_diagnosis(
            root_cause="Import error in foo.py",
            severity=Severity.P1_BLOCKING,
            fix_plan="Fix the import",
            human_guidance="Review module structure",
            affected_files=["src/foo.py", "src/bar.py"],
        )
        comment = _format_diagnosis_comment(diagnosis)

        assert "## Diagnostic Analysis" in comment
        assert "**Severity:**" in comment
        assert "P1" in comment
        assert "**Root Cause:** Import error in foo.py" in comment
        assert "**Affected Files:**" in comment
        assert "`src/foo.py`" in comment
        assert "### Fix Plan" in comment
        assert "Fix the import" in comment
        assert "### Human Guidance" in comment
        assert "Review module structure" in comment
        assert "*Generated by HydraFlow Diagnostic Agent*" in comment

    def test_format_diagnosis_comment_no_affected_files(self) -> None:
        """When no affected_files, shows _unknown_."""
        diagnosis = _make_diagnosis(affected_files=[])
        comment = _format_diagnosis_comment(diagnosis)
        assert "_unknown_" in comment

    def test_format_diagnosis_comment_empty_fix_plan(self) -> None:
        """Empty fix_plan shows fallback text."""
        diagnosis = _make_diagnosis(fix_plan="")
        comment = _format_diagnosis_comment(diagnosis)
        assert "_No fix plan generated._" in comment
