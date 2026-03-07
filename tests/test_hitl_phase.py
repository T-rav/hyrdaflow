"""Tests for hitl_phase.py — HITLPhase."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

from events import EventType
from tests.conftest import TaskFactory
from tests.helpers import make_hitl_phase

if TYPE_CHECKING:
    from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# HITL phase — process_corrections & _process_one_hitl
# ---------------------------------------------------------------------------


class TestHITLPhaseProcessing:
    """Tests for HITLPhase correction processing."""

    @pytest.mark.asyncio
    async def test_process_corrections_skips_when_empty(
        self, config: HydraFlowConfig
    ) -> None:
        phase, _state, _fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)

        await phase.process_corrections()

        prs.remove_label.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_restores_origin_label(self, config: HydraFlowConfig) -> None:
        """On success, the origin label should be restored."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Test HITL", body="Fix it")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix the tests", semaphore)

        # Verify origin label was restored via swap
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-review")

        # Verify HITL state was cleaned up
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None

    @pytest.mark.asyncio
    async def test_success_clears_visual_evidence(
        self, config: HydraFlowConfig
    ) -> None:
        """On success, visual evidence should be cleared from state."""
        from models import HITLResult, VisualEvidence, VisualEvidenceItem

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Test HITL", body="Fix it")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "Visual validation failed")
        state.set_hitl_visual_evidence(
            42,
            VisualEvidence(
                items=[
                    VisualEvidenceItem(
                        screen_name="login", diff_percent=8.0, status="fail"
                    )
                ],
                summary="1 screen exceeded threshold",
            ),
        )

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix the visual regression", semaphore)

        assert state.get_hitl_visual_evidence(42) is None

    @pytest.mark.asyncio
    async def test_failure_keeps_hitl_label(self, config: HydraFlowConfig) -> None:
        """On failure, the hydraflow-hitl label should be re-applied."""
        from models import HITLResult, VisualEvidence, VisualEvidenceItem

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Test HITL", body="Fix it")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")
        state.set_hitl_visual_evidence(
            42,
            VisualEvidence(
                items=[
                    VisualEvidenceItem(
                        screen_name="login", diff_percent=5.0, status="fail"
                    )
                ],
                summary="1 screen exceeded threshold",
            ),
        )

        runner.run = AsyncMock(
            return_value=HITLResult(
                issue_number=42, success=False, error="quality failed"
            )
        )

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix the tests", semaphore)

        # Verify HITL label was re-applied via swap
        prs.swap_pipeline_labels.assert_any_call(42, config.hitl_label[0])

        # Verify HITL state is preserved (not cleaned up) — spec: requeue retains evidence
        assert state.get_hitl_origin(42) == "hydraflow-review"
        assert state.get_hitl_cause(42) == "CI failed"
        assert state.get_hitl_visual_evidence(42) is not None

    @pytest.mark.asyncio
    async def test_success_posts_comment(self, config: HydraFlowConfig) -> None:
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "HITL correction applied successfully" in comment

    @pytest.mark.asyncio
    async def test_failure_posts_comment(self, config: HydraFlowConfig) -> None:
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(
            return_value=HITLResult(
                issue_number=42, success=False, error="make quality failed"
            )
        )

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        prs.post_comment.assert_called_once()
        comment = prs.post_comment.call_args.args[1]
        assert "HITL correction failed" in comment
        assert "make quality failed" in comment

    @pytest.mark.asyncio
    async def test_skips_when_issue_not_found(self, config: HydraFlowConfig) -> None:
        phase, _state, fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)
        fetcher.fetch_issue_by_number = AsyncMock(return_value=None)

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        # No label changes or comments when issue not found
        prs.post_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_publishes_resolved_event_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        events = [
            e
            for e in bus.get_history()
            if e.type == EventType.HITL_UPDATE and e.data.get("action") == "resolved"
        ]
        assert len(events) == 1
        assert events[0].data["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_publishes_failed_event_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(
            return_value=HITLResult(issue_number=42, success=False, error="fail")
        )

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        events = [
            e
            for e in bus.get_history()
            if e.type == EventType.HITL_UPDATE and e.data.get("action") == "failed"
        ]
        assert len(events) == 1
        assert events[0].data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_stop_event_awaits_cancelled_tasks(
        self, config: HydraFlowConfig
    ) -> None:
        """After stop_event, cancelled tasks must be awaited for clean shutdown."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)

        # Allow two concurrent workers so task 43 is genuinely mid-execution
        # (blocked in runner.run) when it gets cancelled.  With max_hitl_workers=1
        # task 43 never starts before the outer loop cancels it, making the test
        # a false positive (it would pass even without the gather fix).
        config.max_hitl_workers = 2

        first_task_started = asyncio.Event()
        task_43_running = asyncio.Event()

        async def run_by_issue(issue, correction, cause, wt_path):  # noqa: ANN001, ANN202, ARG001
            if issue.id == 42:
                first_task_started.set()
                # Wait for task 43 to be truly blocked inside runner.run, then stop
                await task_43_running.wait()
                phase._stop_event.set()
                return HITLResult(issue_number=42, success=True)
            else:
                # Signal that task 43 is running, then block until cancelled
                task_43_running.set()
                await asyncio.sleep(3600)  # interrupted by CancelledError
                return HITLResult(issue_number=43, success=True)

        fetcher.fetch_issue_by_number = AsyncMock(
            side_effect=lambda n: TaskFactory.create(id=n)
        )
        runner.run = AsyncMock(side_effect=run_by_issue)

        # Submit two corrections — task 42 sets stop_event while task 43 is
        # mid-execution (sleeping in runner.run), so the outer loop must cancel
        # and properly await task 43 via gather.
        phase.submit_correction(42, "Fix A")
        phase.submit_correction(43, "Fix B")

        await phase.process_corrections()

        # Both tasks must have actually run (not completed trivially)
        assert first_task_started.is_set(), "Task 42 should have run"
        assert task_43_running.is_set(), "Task 43 should have been mid-execution"
        # The key assertion: no pending tasks remain after process_corrections returns.
        # Without `await asyncio.gather(...)`, the cancelled task 43 (blocked in
        # asyncio.sleep) would still be pending here.
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        assert not pending, f"Leaked tasks after process_corrections: {pending}"

    @pytest.mark.asyncio
    async def test_clears_active_issues(self, config: HydraFlowConfig) -> None:
        """Issue should be removed from active_hitl_issues after processing."""
        from models import HITLResult

        phase, _state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        assert 42 not in phase.active_hitl_issues

    @pytest.mark.asyncio
    async def test_swaps_to_active_label(self, config: HydraFlowConfig) -> None:
        """Processing should swap to hitl-active label before running agent."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        # Check that hitl_active_label was set via swap
        prs.swap_pipeline_labels.assert_any_call(42, config.hitl_active_label[0])

    @pytest.mark.asyncio
    async def test_success_destroys_worktree(self, config: HydraFlowConfig) -> None:
        """On success, the worktree should be destroyed."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        wt.destroy.assert_awaited_once_with(42)

    @pytest.mark.asyncio
    async def test_failure_does_not_destroy_worktree(
        self, config: HydraFlowConfig
    ) -> None:
        """On failure, the worktree should be kept for retry."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(
            return_value=HITLResult(issue_number=42, success=False, error="fail")
        )

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix it", semaphore)

        wt.destroy.assert_not_awaited()


# ---------------------------------------------------------------------------
# HITL correction resets issue attempts
# ---------------------------------------------------------------------------


class TestHITLGetStatus:
    """Tests for HITLPhase.get_status() display mapping."""

    def test_get_status_returns_approval_for_improve_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Memory suggestions with improve origin should show 'approval'."""
        phase, state, *_ = make_hitl_phase(config)
        state.set_hitl_origin(42, config.improve_label[0])
        assert phase.get_status(42) == "approval"

    def test_get_status_does_not_return_approval_for_non_improve_origin(
        self, config: HydraFlowConfig
    ) -> None:
        """Non-memory escalations should not show 'approval'."""
        phase, state, *_ = make_hitl_phase(config)
        state.set_hitl_origin(42, "hydraflow-review")
        assert phase.get_status(42) != "approval"


class TestHITLPhaseCorrections:
    """Direct unit tests for submit_correction() and skip_issue()."""

    def test_submit_correction_stores_value(self, config: HydraFlowConfig) -> None:
        phase, *_ = make_hitl_phase(config)
        phase.submit_correction(42, "Fix the test")
        assert phase.hitl_corrections == {42: "Fix the test"}

    def test_submit_correction_overwrites_existing(
        self, config: HydraFlowConfig
    ) -> None:
        phase, *_ = make_hitl_phase(config)
        phase.submit_correction(42, "First attempt")
        phase.submit_correction(42, "Second attempt")
        assert phase.hitl_corrections == {42: "Second attempt"}

    def test_skip_issue_removes_correction(self, config: HydraFlowConfig) -> None:
        phase, *_ = make_hitl_phase(config)
        phase.submit_correction(42, "Fix")
        phase.skip_issue(42)
        assert 42 not in phase.hitl_corrections

    def test_skip_issue_noop_for_unknown_issue(self, config: HydraFlowConfig) -> None:
        """Skipping an issue that was never submitted should not raise."""
        phase, *_ = make_hitl_phase(config)
        phase.skip_issue(99)  # should not raise
        assert phase.hitl_corrections == {}


class TestHITLResetsAttempts:
    """Tests that HITL correction resets issue_attempts."""

    @pytest.mark.asyncio
    async def test_hitl_correction_resets_issue_attempts(
        self, config: HydraFlowConfig
    ) -> None:
        """On successful HITL correction, issue_attempts should be reset."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)

        # Set up state with attempts
        state.increment_issue_attempts(42)
        state.increment_issue_attempts(42)
        assert state.get_issue_attempts(42) == 2

        # Mock HITL runner to succeed
        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        # Set HITL origin/cause
        state.set_hitl_origin(42, "hydraflow-ready")
        state.set_hitl_cause(42, "Cap exceeded")

        # Mock fetcher and PR manager
        fetcher.fetch_issue_by_number = AsyncMock(
            return_value=TaskFactory.create(id=42)
        )

        # Create worktree directory
        wt_path = config.worktree_path_for_issue(42)
        wt_path.mkdir(parents=True, exist_ok=True)
        wt.create = AsyncMock(return_value=wt_path)

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix the tests", semaphore)

        # Issue attempts should be reset
        assert state.get_issue_attempts(42) == 0


# ---------------------------------------------------------------------------
# HITL improve→triage transition on correction success
# ---------------------------------------------------------------------------


class TestHITLImproveTransition:
    """Tests that improve-origin HITL corrections transition to triage."""

    @pytest.mark.asyncio
    async def test_success_improve_origin_transitions_to_triage(
        self, config: HydraFlowConfig
    ) -> None:
        """On success with improve origin, should remove improve and add find label."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Improve: test", body="Details")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-improve")
        state.set_hitl_cause(42, "Memory suggestion")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Improve the prompt", semaphore)

        # Verify find/triage label was set via swap (not the improve label)
        prs.swap_pipeline_labels.assert_any_call(42, config.find_label[0])

        # Verify HITL state was cleaned up
        assert state.get_hitl_origin(42) is None
        assert state.get_hitl_cause(42) is None

    @pytest.mark.asyncio
    async def test_success_non_improve_origin_restores_label(
        self, config: HydraFlowConfig
    ) -> None:
        """Non-improve origins should still restore the original label."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Test", body="Details")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Fix the tests", semaphore)

        # Verify review label was restored via swap
        prs.swap_pipeline_labels.assert_any_call(42, "hydraflow-review")

        # Verify find label was NOT set
        swap_calls = [c.args for c in prs.swap_pipeline_labels.call_args_list]
        assert (42, config.find_label[0]) not in swap_calls

    @pytest.mark.asyncio
    async def test_failure_improve_origin_preserves_state(
        self, config: HydraFlowConfig
    ) -> None:
        """On failure, improve origin state should be preserved for retry."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Improve: test", body="Details")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-improve")
        state.set_hitl_cause(42, "Memory suggestion")

        runner.run = AsyncMock(
            return_value=HITLResult(
                issue_number=42, success=False, error="quality failed"
            )
        )

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Improve the prompt", semaphore)

        # Verify HITL label was re-applied via swap
        prs.swap_pipeline_labels.assert_any_call(42, config.hitl_label[0])

        # Verify improve origin state is preserved for retry
        assert state.get_hitl_origin(42) == "hydraflow-improve"
        assert state.get_hitl_cause(42) == "Memory suggestion"

    @pytest.mark.asyncio
    async def test_improve_success_comment_mentions_find_label(
        self, config: HydraFlowConfig
    ) -> None:
        """Success comment for improve origin should mention the find/triage stage."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42, title="Improve: test", body="Details")

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-improve")

        runner.run = AsyncMock(return_value=HITLResult(issue_number=42, success=True))

        semaphore = asyncio.Semaphore(1)
        await phase._process_one_hitl(42, "Improve it", semaphore)

        comment = prs.post_comment.call_args.args[1]
        assert config.find_label[0] in comment


# ---------------------------------------------------------------------------
# HITL memory suggestion filing
# ---------------------------------------------------------------------------

MEMORY_TRANSCRIPT = (
    "Some output\n"
    "MEMORY_SUGGESTION_START\n"
    "title: Test suggestion\n"
    "learning: Learned something useful\n"
    "context: During testing\n"
    "MEMORY_SUGGESTION_END\n"
)


class TestHITLMemorySuggestionFiling:
    """Memory suggestions from HITL transcripts are filed."""

    @pytest.mark.asyncio
    async def test_hitl_files_memory_suggestion_on_success(
        self, config: HydraFlowConfig
    ) -> None:
        """On success with transcript, file_memory_suggestion should be called."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(
            return_value=HITLResult(
                issue_number=42, success=True, transcript=MEMORY_TRANSCRIPT
            )
        )

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            semaphore = asyncio.Semaphore(1)
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

            mock_mem.assert_awaited_once()
            args = mock_mem.call_args[0]
            assert args[0] == MEMORY_TRANSCRIPT
            assert args[1] == "hitl"
            assert args[2] == "issue #42"

    @pytest.mark.asyncio
    async def test_hitl_files_memory_suggestion_on_failure(
        self, config: HydraFlowConfig
    ) -> None:
        """On failure with transcript, file_memory_suggestion should still be called."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(
            return_value=HITLResult(
                issue_number=42,
                success=False,
                error="quality failed",
                transcript=MEMORY_TRANSCRIPT,
            )
        )

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            semaphore = asyncio.Semaphore(1)
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

            mock_mem.assert_awaited_once()
            args = mock_mem.call_args[0]
            assert args[0] == MEMORY_TRANSCRIPT
            assert args[1] == "hitl"
            assert args[2] == "issue #42"

    @pytest.mark.asyncio
    async def test_hitl_skips_memory_suggestion_for_empty_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Empty transcript should not trigger file_memory_suggestion."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")

        runner.run = AsyncMock(
            return_value=HITLResult(issue_number=42, success=True, transcript="")
        )

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            semaphore = asyncio.Semaphore(1)
            await phase._process_one_hitl(42, "Fix it", semaphore)

            mock_mem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_hitl_memory_suggestion_error_does_not_break_processing(
        self, config: HydraFlowConfig
    ) -> None:
        """file_memory_suggestion errors should be logged but not interrupt processing."""
        from models import HITLResult

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(
            return_value=HITLResult(
                issue_number=42, success=True, transcript=MEMORY_TRANSCRIPT
            )
        )

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("GitHub API error"),
        ) as mock_mem:
            semaphore = asyncio.Semaphore(1)
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

            # The suggestion call must have been attempted (exception was swallowed)
            mock_mem.assert_awaited_once()
            # Processing should complete normally — comment posted, labels swapped
            prs.post_comment.assert_called_once()
            comment = prs.post_comment.call_args.args[1]
            assert "HITL correction applied successfully" in comment


# ---------------------------------------------------------------------------
# Critical exception propagation through process_correction
# ---------------------------------------------------------------------------


class TestHITLExceptionPropagation:
    """Tests that critical exceptions propagate through _process_one_hitl."""

    @pytest.mark.asyncio
    async def test_auth_error_propagates_through_process_correction(
        self, config: HydraFlowConfig
    ) -> None:
        """AuthenticationError should propagate, not be caught by except Exception."""
        from subprocess_util import AuthenticationError

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(side_effect=AuthenticationError("401 Unauthorized"))

        semaphore = asyncio.Semaphore(1)
        with pytest.raises(AuthenticationError, match="401"):
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

    @pytest.mark.asyncio
    async def test_credit_error_propagates_through_process_correction(
        self, config: HydraFlowConfig
    ) -> None:
        """CreditExhaustedError should propagate, not be caught by except Exception."""
        from subprocess_util import CreditExhaustedError

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(side_effect=CreditExhaustedError("limit reached"))

        semaphore = asyncio.Semaphore(1)
        with pytest.raises(CreditExhaustedError, match="limit reached"):
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

    @pytest.mark.asyncio
    async def test_memory_error_propagates_through_process_correction(
        self, config: HydraFlowConfig
    ) -> None:
        """MemoryError should propagate, not be caught by except Exception."""
        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(side_effect=MemoryError("out of memory"))

        semaphore = asyncio.Semaphore(1)
        with pytest.raises(MemoryError, match="out of memory"):
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

    @pytest.mark.asyncio
    async def test_active_issues_cleaned_on_critical_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Active HITL issues should be cleaned up even when critical errors propagate."""
        from subprocess_util import AuthenticationError

        phase, state, fetcher, prs, wt, runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        fetcher.fetch_issue_by_number = AsyncMock(return_value=issue)
        state.set_hitl_origin(42, "hydraflow-review")
        state.set_hitl_cause(42, "CI failed")

        runner.run = AsyncMock(side_effect=AuthenticationError("401 Unauthorized"))

        semaphore = asyncio.Semaphore(1)
        with pytest.raises(AuthenticationError):
            await phase._process_one_hitl(42, "Fix the tests", semaphore)

        # finally block should still clean up active issues
        assert 42 not in phase._active_hitl_issues


# ---------------------------------------------------------------------------
# HITL auto-fix attempt
# ---------------------------------------------------------------------------


class TestHITLAutoFix:
    """Tests for HITLPhase.attempt_auto_fixes."""

    @pytest.mark.asyncio
    async def test_auto_fix_queues_correction_for_new_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """New HITL issues should get an auto-fix correction queued."""
        phase, state, _fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)
        state.set_hitl_cause(42, "CI failed")

        await phase.attempt_auto_fixes([issue])

        assert 42 in phase._hitl_corrections
        assert "AUTOMATIC FIX ATTEMPT" in phase._hitl_corrections[42]
        assert "CI failed" in phase._hitl_corrections[42]
        prs.post_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_fix_skips_already_attempted(
        self, config: HydraFlowConfig
    ) -> None:
        """Issues already auto-attempted should not be retried."""
        phase, state, _fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)
        state.set_hitl_cause(42, "CI failed")
        phase._auto_fix_attempted.add(42)

        await phase.attempt_auto_fixes([issue])

        assert 42 not in phase._hitl_corrections
        prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_fix_skips_issue_with_pending_correction(
        self, config: HydraFlowConfig
    ) -> None:
        """Issues with human corrections already pending should not be auto-fixed."""
        phase, state, _fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)
        state.set_hitl_cause(42, "CI failed")
        phase._hitl_corrections[42] = "Human fix"

        await phase.attempt_auto_fixes([issue])

        # Should keep the human correction, not overwrite it
        assert phase._hitl_corrections[42] == "Human fix"

    @pytest.mark.asyncio
    async def test_auto_fix_skips_issue_without_cause(
        self, config: HydraFlowConfig
    ) -> None:
        """Issues without a stored cause should not be auto-fixed."""
        phase, _state, _fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)
        issue = TaskFactory.create(id=42)

        await phase.attempt_auto_fixes([issue])

        assert 42 not in phase._hitl_corrections

    @pytest.mark.asyncio
    async def test_auto_fix_stops_on_stop_event(self, config: HydraFlowConfig) -> None:
        """Should respect the stop event and bail out early."""
        phase, state, _fetcher, prs, _wt, _runner, _bus = make_hitl_phase(config)
        issue1 = TaskFactory.create(id=42)
        issue2 = TaskFactory.create(id=43)
        state.set_hitl_cause(42, "CI failed")
        state.set_hitl_cause(43, "Test failed")
        phase._stop_event.set()

        await phase.attempt_auto_fixes([issue1, issue2])

        assert 42 not in phase._hitl_corrections
        assert 43 not in phase._hitl_corrections
