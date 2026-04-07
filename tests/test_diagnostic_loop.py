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
    with_workspaces: bool = False,
) -> tuple[DiagnosticLoop, MagicMock, MagicMock, MagicMock, MagicMock | None]:
    """Build a DiagnosticLoop with test-friendly defaults.

    Returns (loop, runner_mock, prs_mock, state_mock, workspaces_mock).
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

    workspaces: MagicMock | None = None
    if with_workspaces:
        workspaces = MagicMock()
        wt_path = deps.config.workspace_path_for_issue(42)
        workspaces.create = AsyncMock(return_value=wt_path)
        workspaces.destroy = AsyncMock()

    loop = DiagnosticLoop(
        config=deps.config,
        runner=runner,
        prs=prs,
        state=state,
        deps=deps.loop_deps,
        workspaces=workspaces,
    )
    return loop, runner, prs, state, workspaces


class TestDiagnosticLoopInterval:
    """Tests for _get_default_interval."""

    def test_returns_config_value(self, tmp_path: Path) -> None:
        """_get_default_interval returns the configured diagnostic_interval."""
        loop, _, _, _, _ = _make_loop(tmp_path)
        assert loop._get_default_interval() == loop._config.diagnostic_interval


class TestDiagnosticLoopDoWork:
    """Tests for _do_work."""

    @pytest.mark.asyncio
    async def test_empty_issue_list_returns_zero_counts(self, tmp_path: Path) -> None:
        """When no issues are labeled, _do_work returns zeroed stats."""
        loop, _, prs, _, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = []

        result = await loop._do_work()

        assert result == {"processed": 0, "fixed": 0, "escalated": 0}

    @pytest.mark.asyncio
    async def test_returns_zero_counts_on_fetch_error(self, tmp_path: Path) -> None:
        """When list_issues_by_label raises, _do_work returns zeroed stats."""
        loop, _, prs, _, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.side_effect = RuntimeError("auth failed")

        result = await loop._do_work()

        assert result == {"processed": 0, "fixed": 0, "escalated": 0}

    @pytest.mark.asyncio
    async def test_fetches_issues_using_diagnose_label(self, tmp_path: Path) -> None:
        """_do_work fetches issues using the first element of diagnose_label."""
        loop, _, prs, _, _ = _make_loop(tmp_path)
        prs.list_issues_by_label.return_value = []

        await loop._do_work()

        prs.list_issues_by_label.assert_awaited_once_with(
            loop._config.diagnose_label[0]
        )

    @pytest.mark.asyncio
    async def test_fixed_issue_counts_as_fixed(self, tmp_path: Path) -> None:
        """When fix succeeds, the fixed counter increments."""
        loop, runner, prs, state, _ = _make_loop(tmp_path)
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
        loop, runner, prs, _, _ = _make_loop(tmp_path)
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
        loop, runner, prs, _, _ = _make_loop(tmp_path)
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
        loop, runner, prs, state, _ = _make_loop(tmp_path)
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
        loop, _, _, state, _ = _make_loop(tmp_path)
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
        loop, runner, prs, state, _ = _make_loop(tmp_path)
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
        loop, runner, _, state, _ = _make_loop(tmp_path)
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
        loop, runner, prs, _, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "fixed"
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.review_label[0]
        )

    @pytest.mark.asyncio
    async def test_posts_success_comment_on_fix(self, tmp_path: Path) -> None:
        """A success comment is posted when fix succeeds."""
        loop, runner, prs, _, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")

        await loop._process_issue(42, "Title", "Body")

        prs.post_comment.assert_awaited_once()
        comment_body = prs.post_comment.call_args[0][1]
        assert "Diagnostic Fix Applied" in comment_body
        assert "Diagnostic Analysis" in comment_body

    @pytest.mark.asyncio
    async def test_records_attempt_on_success(self, tmp_path: Path) -> None:
        """An AttemptRecord is written to state on successful fix."""
        loop, runner, _, state, _ = _make_loop(tmp_path)
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
        loop, runner, _, _, _ = _make_loop(tmp_path)
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
        loop, runner, prs, state, _ = _make_loop(tmp_path)
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
        loop, runner, prs, state, _ = _make_loop(tmp_path)
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
        loop, runner, _, state, _ = _make_loop(tmp_path)
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


class TestWorkspaceCreation:
    """Diagnostic loop creates and cleans up workspaces for fix attempts."""

    @pytest.mark.asyncio
    async def test_creates_workspace_before_fix(self, tmp_path: Path) -> None:
        """When workspaces manager is provided, workspace is created before fix."""
        loop, runner, _, _, ws = _make_loop(tmp_path, with_workspaces=True)
        runner.fix.return_value = (True, "Fixed!")
        assert ws is not None

        await loop._process_issue(42, "Title", "Body")

        ws.create.assert_awaited_once_with(42, "agent/diag-42")
        runner.fix.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_destroys_workspace_after_success(self, tmp_path: Path) -> None:
        """Workspace is cleaned up after a successful fix."""
        loop, runner, _, _, ws = _make_loop(tmp_path, with_workspaces=True)
        runner.fix.return_value = (True, "Fixed!")
        assert ws is not None

        await loop._process_issue(42, "Title", "Body")

        ws.destroy.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_destroys_workspace_after_failure(self, tmp_path: Path) -> None:
        """Workspace is cleaned up even when fix fails."""
        loop, runner, _, _, ws = _make_loop(tmp_path, with_workspaces=True)
        runner.fix.return_value = (False, "Could not fix")
        assert ws is not None

        await loop._process_issue(42, "Title", "Body")

        ws.destroy.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_destroys_workspace_on_runner_exception(self, tmp_path: Path) -> None:
        """Workspace is cleaned up even when runner.fix() raises."""
        loop, runner, _, _, ws = _make_loop(tmp_path, with_workspaces=True)
        runner.fix.side_effect = RuntimeError("boom")
        assert ws is not None

        with pytest.raises(RuntimeError, match="boom"):
            await loop._process_issue(42, "Title", "Body")

        ws.destroy.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_escalates_when_workspace_creation_fails(
        self, tmp_path: Path
    ) -> None:
        """If workspace creation fails, issue is escalated to HITL."""
        loop, runner, prs, _, ws = _make_loop(tmp_path, with_workspaces=True)
        assert ws is not None
        ws.create.side_effect = RuntimeError("clone failed")

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "escalated"
        runner.fix.assert_not_awaited()
        prs.swap_pipeline_labels.assert_awaited_once_with(
            42, loop._config.hitl_label[0]
        )

    @pytest.mark.asyncio
    async def test_destroys_preexisting_workspace_on_retry(
        self, tmp_path: Path
    ) -> None:
        """On retry, workspace exists from prior attempt — still destroyed after fix."""
        loop, runner, _, _, ws = _make_loop(tmp_path, with_workspaces=True)
        assert ws is not None
        runner.fix.return_value = (False, "Could not fix")

        # Simulate workspace already existing from a prior attempt
        wt_path = loop._config.workspace_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)

        await loop._process_issue(42, "Title", "Body")

        # create should NOT be called (workspace already existed)
        ws.create.assert_not_awaited()
        # destroy MUST still be called to clean up
        ws.destroy.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_no_workspace_manager_still_works(self, tmp_path: Path) -> None:
        """Without a workspace manager, loop uses config path directly."""
        loop, runner, _, _, ws = _make_loop(tmp_path, with_workspaces=False)
        assert ws is None
        runner.fix.return_value = (True, "Fixed!")

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "fixed"


class TestRetryWithPreviousAttempts:
    """Diagnostic loop enriches context with previous attempts on retry."""

    @pytest.mark.asyncio
    async def test_context_includes_previous_attempts(self, tmp_path: Path) -> None:
        """When prior attempts exist, they are passed to diagnose() via context."""
        loop, runner, _, state, _ = _make_loop(tmp_path)
        prior = [
            AttemptRecord(
                attempt_number=1,
                changes_made=False,
                error_summary="first try failed",
                timestamp="2026-01-01T00:00:00+00:00",
            )
        ]
        # First call (enrich context) returns prior attempts;
        # second call (check limit) returns the same
        state.get_diagnostic_attempts.return_value = prior
        runner.fix.return_value = (True, "Fixed!")

        await loop._process_issue(42, "Title", "Body")

        # Verify diagnose() received context with previous_attempts populated
        ctx_arg = runner.diagnose.call_args[0][3]
        assert len(ctx_arg.previous_attempts) == 1
        assert ctx_arg.previous_attempts[0].error_summary == "first try failed"

    @pytest.mark.asyncio
    async def test_empty_attempts_leaves_context_unchanged(
        self, tmp_path: Path
    ) -> None:
        """When no prior attempts, context.previous_attempts stays empty."""
        loop, runner, _, state, _ = _make_loop(tmp_path)
        state.get_diagnostic_attempts.return_value = []
        runner.fix.return_value = (True, "Fixed!")

        await loop._process_issue(42, "Title", "Body")

        ctx_arg = runner.diagnose.call_args[0][3]
        assert ctx_arg.previous_attempts == []


class TestLabelSwapFailure:
    """Label swap failure after successful fix is handled gracefully."""

    @pytest.mark.asyncio
    async def test_label_swap_error_returns_fixed(self, tmp_path: Path) -> None:
        """If swap_pipeline_labels raises after fix, outcome is still 'fixed'."""
        loop, runner, prs, _, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")
        prs.swap_pipeline_labels.side_effect = RuntimeError("API error")

        outcome = await loop._process_issue(42, "Title", "Body")

        assert outcome == "fixed"

    @pytest.mark.asyncio
    async def test_label_swap_error_still_publishes_fixed_event(
        self, tmp_path: Path
    ) -> None:
        """Even if label swap fails, the fixed event is published."""
        loop, runner, prs, _, _ = _make_loop(tmp_path)
        runner.fix.return_value = (True, "Fixed!")
        prs.swap_pipeline_labels.side_effect = RuntimeError("API error")

        await loop._process_issue(42, "Title", "Body")

        events = [
            e for e in loop._bus.get_history() if e.type == EventType.DIAGNOSTIC_UPDATE
        ]
        assert any(e.data.get("status") == "fixed" for e in events)


class TestRetryEventPublishing:
    """Verify the retry event is published when fix fails but retries remain."""

    @pytest.mark.asyncio
    async def test_publishes_retry_event_on_failed_fix_with_retries(
        self, tmp_path: Path
    ) -> None:
        """A DIAGNOSTIC_UPDATE 'retry' event is published when fix fails but retries remain."""
        loop, runner, _, state, _ = _make_loop(tmp_path)
        runner.fix.return_value = (False, "Could not fix")
        # No prior attempts, max is 2, so after recording 1 attempt there's still 1 left
        state.get_diagnostic_attempts.side_effect = [
            [],  # enrich context call
            [],  # check limit call
            [  # post-recording call
                AttemptRecord(
                    attempt_number=1,
                    changes_made=False,
                    error_summary="failed",
                    timestamp="2026-01-01T00:00:00+00:00",
                )
            ],
        ]

        await loop._process_issue(42, "Title", "Body")

        events = [
            e for e in loop._bus.get_history() if e.type == EventType.DIAGNOSTIC_UPDATE
        ]
        statuses = [e.data.get("status") for e in events]
        assert "retry" in statuses
