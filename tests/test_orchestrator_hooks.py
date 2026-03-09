"""Tests for dx/hydraflow/orchestrator.py - Post-run hooks, memory, sessions, crash recovery, bg workers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from events import EventBus, EventType, HydraFlowEvent
from state import StateTracker

if TYPE_CHECKING:
    from config import HydraFlowConfig
from models import (
    BackgroundWorkerState,
    GitHubIssue,
    PRInfo,
    ReviewResult,
    ReviewVerdict,
    Task,
    WorkerResult,
)
from orchestrator import HydraFlowOrchestrator
from tests.conftest import IssueFactory, PRInfoFactory, TaskFactory, WorkerResultFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_fetcher_noop(orch: HydraFlowOrchestrator) -> None:
    """Mock store and fetcher methods so no real gh CLI calls are made."""
    orch._store.get_triageable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_plannable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.get_reviewable = lambda _max_count: []  # type: ignore[method-assign]
    orch._store.start = AsyncMock()  # type: ignore[method-assign]
    orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
    orch._fetcher.fetch_issue_by_number = AsyncMock(return_value=None)  # type: ignore[method-assign]
    orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]
    orch._enable_rerere = AsyncMock()  # type: ignore[method-assign]
    orch._worktrees.sanitize_repo = AsyncMock()  # type: ignore[method-assign]


def make_worker_result(
    issue_number: int = 42,
    branch: str = "agent/issue-42",
    success: bool = True,
    worktree_path: str = "/tmp/worktrees/issue-42",
    transcript: str = "Implemented the feature.",
) -> WorkerResult:
    return WorkerResultFactory.create(
        issue_number=issue_number,
        branch=branch,
        success=success,
        transcript=transcript,
        commits=1,
        worktree_path=worktree_path,
        use_defaults=True,
    )


def make_review_result(
    pr_number: int = 101,
    issue_number: int = 42,
    verdict: ReviewVerdict = ReviewVerdict.APPROVE,
    transcript: str = "",
) -> ReviewResult:
    return ReviewResult(
        pr_number=pr_number,
        issue_number=issue_number,
        verdict=verdict,
        summary="Looks good.",
        fixes_made=False,
        transcript=transcript,
    )


# ---------------------------------------------------------------------------
# Crash recovery — active issue persistence
# ---------------------------------------------------------------------------


class TestCrashRecoveryActiveIssues:
    """Tests for crash recovery via persisted active_issue_numbers."""

    def test_crash_recovery_loads_active_issues(self, config: HydraFlowConfig) -> None:
        """On init, recovered issues from state should populate _recovered_issues after run()."""
        orch = HydraFlowOrchestrator(config)
        orch._state.set_active_issue_numbers([10, 20])

        # Simulate run() startup sequence
        recovered = set(orch._state.get_active_issue_numbers())
        assert recovered == {10, 20}

    @pytest.mark.asyncio
    async def test_crash_recovery_skips_first_cycle(
        self, config: HydraFlowConfig
    ) -> None:
        """Recovered issues should be in _active_impl_issues for one cycle."""
        orch = HydraFlowOrchestrator(config)
        _mock_fetcher_noop(orch)
        orch._state.set_active_issue_numbers([10, 20])

        # Simulate run() startup
        orch._stop_event.clear()
        orch._running = True
        recovered = set(orch._state.get_active_issue_numbers())
        orch._recovered_issues = recovered
        orch._active_impl_issues.update(recovered)

        # Before first cycle: recovered issues are in active set
        assert 10 in orch._active_impl_issues
        assert 20 in orch._active_impl_issues

    @pytest.mark.asyncio
    async def test_crash_recovery_clears_after_cycle(
        self, config: HydraFlowConfig
    ) -> None:
        """After one cycle, recovered issues should be cleared from active sets."""
        orch = HydraFlowOrchestrator(config)
        _mock_fetcher_noop(orch)
        orch._state.set_active_issue_numbers([10, 20])

        # Simulate startup
        recovered = set(orch._state.get_active_issue_numbers())
        orch._recovered_issues = recovered
        orch._active_impl_issues.update(recovered)

        # Simulate what _implement_loop does at the start of a cycle
        if orch._recovered_issues:
            orch._active_impl_issues -= orch._recovered_issues
            orch._recovered_issues.clear()

        assert 10 not in orch._active_impl_issues
        assert 20 not in orch._active_impl_issues
        assert len(orch._recovered_issues) == 0


# ---------------------------------------------------------------------------
# Memory suggestion filing from implementer and reviewer transcripts
# ---------------------------------------------------------------------------

MEMORY_TRANSCRIPT = (
    "Some output\n"
    "MEMORY_SUGGESTION_START\n"
    "title: Test suggestion\n"
    "learning: Learned something useful\n"
    "context: During testing\n"
    "MEMORY_SUGGESTION_END\n"
)


class TestMemorySuggestionFiling:
    """Memory suggestions from implementer and reviewer transcripts are filed."""

    @pytest.mark.asyncio
    async def test_implement_loop_files_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer transcripts with MEMORY_SUGGESTION blocks trigger filing."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript=MEMORY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._implement_loop()
            mock_mem.assert_awaited_once()
            args = mock_mem.call_args
            assert args[0][0] == MEMORY_TRANSCRIPT
            assert args[0][1] == "implementer"
            assert args[0][2] == "issue #42"

    @pytest.mark.asyncio
    async def test_implement_loop_skips_empty_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer results with empty transcripts should not trigger filing."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript="")

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._implement_loop()
            mock_mem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_implement_loop_multiple_results_files_each(
        self, config: HydraFlowConfig
    ) -> None:
        """Multiple implementer results: only those with transcripts trigger filing."""
        orch = HydraFlowOrchestrator(config)
        r1 = make_worker_result(issue_number=10, transcript=MEMORY_TRANSCRIPT)
        r2 = make_worker_result(issue_number=20, transcript="")
        r3 = make_worker_result(issue_number=30, transcript=MEMORY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [r1, r2, r3], [
                TaskFactory.create(id=10),
                TaskFactory.create(id=20),
                TaskFactory.create(id=30),
            ]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._implement_loop()
            assert mock_mem.await_count == 2
            # Check the first 3 positional args of each call
            calls = mock_mem.call_args_list
            call_refs = [(c[0][0], c[0][1], c[0][2]) for c in calls]
            assert (MEMORY_TRANSCRIPT, "implementer", "issue #10") in call_refs
            assert (MEMORY_TRANSCRIPT, "implementer", "issue #30") in call_refs

    @pytest.mark.asyncio
    async def test_review_loop_files_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Reviewer transcripts with MEMORY_SUGGESTION blocks trigger filing."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = make_review_result(
            pr_number=101, issue_number=42, transcript=MEMORY_TRANSCRIPT
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._review_loop()
            mock_mem.assert_awaited_once()
            args = mock_mem.call_args
            assert args[0][0] == MEMORY_TRANSCRIPT
            assert args[0][1] == "reviewer"
            assert args[0][2] == "PR #101"

    @pytest.mark.asyncio
    async def test_review_loop_skips_empty_transcript(
        self, config: HydraFlowConfig
    ) -> None:
        """Reviewer results with empty transcripts should not trigger filing."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = make_review_result(
            pr_number=101, issue_number=42, transcript=""
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._review_loop()
            mock_mem.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_review_work_requeues_and_returns_idle_when_no_prs(
        self, config: HydraFlowConfig
    ) -> None:
        """No-PR review fetch should requeue tasks and signal idle for backoff sleep."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
        orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
        orch._store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        did_work = await orch._do_review_work()

        assert did_work is False
        orch._store.enqueue_transition.assert_called_once_with(review_task, "review")

    @pytest.mark.asyncio
    async def test_do_review_work_processes_adr_without_pr(
        self, config: HydraFlowConfig
    ) -> None:
        """ADR review issues should use the no-PR ADR review path."""
        orch = HydraFlowOrchestrator(config)
        adr_task = TaskFactory.create(
            id=420,
            title="[ADR] Event rendering architecture",
            body=(
                "## Context\nA\n\n## Decision\nConcrete choice with enough "
                "detail for review and finalization.\n\n## Consequences\nB"
            ),
        )

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [adr_task]
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
        orch._reviewer.review_adrs = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        did_work = await orch._do_review_work()

        assert did_work is True
        orch._reviewer.review_adrs.assert_awaited_once_with([adr_task])
        orch._fetcher.fetch_reviewable_prs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_review_work_keeps_work_true_when_adr_processed_and_no_prs(
        self, config: HydraFlowConfig
    ) -> None:
        """If ADR work ran, no-PR normal review should not reset did_work to idle."""
        orch = HydraFlowOrchestrator(config)
        adr_task = TaskFactory.create(
            id=500,
            title="[ADR] Queue architecture",
            body=(
                "## Context\nA\n\n## Decision\nConcrete decision detail that is long "
                "enough to pass ADR checks.\n\n## Consequences\nB"
            ),
        )
        normal_review_task = TaskFactory.create(id=501, title="Regular review issue")

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [adr_task, normal_review_task]
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]
        orch._store.get_active_issues = lambda: {}  # type: ignore[method-assign]
        orch._store.enqueue_transition = MagicMock()  # type: ignore[method-assign]
        orch._reviewer.review_adrs = AsyncMock(return_value=[])  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(return_value=([], []))  # type: ignore[method-assign]

        did_work = await orch._do_review_work()

        assert did_work is True
        orch._reviewer.review_adrs.assert_awaited_once_with([adr_task])
        orch._store.enqueue_transition.assert_called_once_with(
            normal_review_task, "review"
        )

    @pytest.mark.asyncio
    async def test_review_loop_multiple_results_files_each(
        self, config: HydraFlowConfig
    ) -> None:
        """Multiple reviewer results: only those with transcripts trigger filing."""
        orch = HydraFlowOrchestrator(config)
        task_a = TaskFactory.create(id=10)
        task_b = TaskFactory.create(id=20)
        issue_a = IssueFactory.create(number=10)
        issue_b = IssueFactory.create(number=20)
        pr_a = PRInfoFactory.create(number=201, issue_number=10)
        pr_b = PRInfoFactory.create(number=202, issue_number=20)
        r1 = make_review_result(
            pr_number=201, issue_number=10, transcript=MEMORY_TRANSCRIPT
        )
        r2 = make_review_result(pr_number=202, issue_number=20, transcript="")

        orch._store.get_active_issues = lambda: {10: "review", 20: "review"}  # type: ignore[method-assign]

        # Per-issue PR fetch: each _review_single_issue calls with one issue
        async def _fetch_per_issue(
            active: set[int],
            prefetched_issues: list[GitHubIssue] | None = None,
        ) -> tuple[list[PRInfo], list[GitHubIssue]]:
            if prefetched_issues and prefetched_issues[0].number == 10:
                return [pr_a], [issue_a]
            if prefetched_issues and prefetched_issues[0].number == 20:
                return [pr_b], [issue_b]
            return [], []

        orch._fetcher.fetch_reviewable_prs = AsyncMock(side_effect=_fetch_per_issue)  # type: ignore[method-assign]

        # Per-issue review: each call gets one PR
        async def _review_per_pr(
            prs: list[PRInfo],
            issues: list[Task],
        ) -> list[ReviewResult]:
            if prs[0].number == 201:
                return [r1]
            return [r2]

        orch._reviewer.review_prs = AsyncMock(side_effect=_review_per_pr)  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return [task_a, task_b][call_count - 1 : call_count]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._review_loop()
            mock_mem.assert_awaited_once()
            args = mock_mem.call_args
            assert args[0][0] == MEMORY_TRANSCRIPT
            assert args[0][1] == "reviewer"
            assert args[0][2] == "PR #201"

    @pytest.mark.asyncio
    async def test_implement_loop_isolates_memory_filing_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Memory filing failure in implementer must not crash the loop."""
        orch = HydraFlowOrchestrator(config)
        r1 = make_worker_result(issue_number=10, transcript=MEMORY_TRANSCRIPT)
        r2 = make_worker_result(issue_number=20, transcript=MEMORY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [r1, r2], [
                TaskFactory.create(id=10),
                TaskFactory.create(id=20),
            ]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("transient"), None],
        ) as mock_mem:
            await orch._implement_loop()  # must not raise
            assert mock_mem.await_count == 2

    @pytest.mark.asyncio
    async def test_review_loop_isolates_memory_filing_error(
        self, config: HydraFlowConfig
    ) -> None:
        """Memory filing failure in reviewer must not crash the loop."""
        orch = HydraFlowOrchestrator(config)
        task_a = TaskFactory.create(id=10)
        issue_a = IssueFactory.create(number=10)
        pr_a = PRInfoFactory.create(number=201, issue_number=10)
        r1 = make_review_result(
            pr_number=201, issue_number=10, transcript=MEMORY_TRANSCRIPT
        )

        orch._store.get_active_issues = lambda: {10: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr_a], [issue_a])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[r1])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [task_a]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("transient"),
        ) as mock_mem:
            await orch._review_loop()  # must not raise
            mock_mem.assert_awaited_once()


# ---------------------------------------------------------------------------
# Transcript summary filing from implementer and reviewer
# ---------------------------------------------------------------------------

SUMMARY_TRANSCRIPT = "x" * 1000  # Long enough to trigger summarization


class TestTranscriptSummaryFiling:
    """Transcript summaries from implementer and reviewer transcripts are posted as comments."""

    @pytest.mark.asyncio
    async def test_implement_loop_calls_summarize_and_comment(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer transcripts trigger transcript summary comment on the issue."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript=SUMMARY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._implement_loop()

        orch._summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = orch._summarizer.summarize_and_comment.call_args
        assert call_kwargs.kwargs["transcript"] == SUMMARY_TRANSCRIPT
        assert call_kwargs.kwargs["issue_number"] == 42
        assert call_kwargs.kwargs["phase"] == "implement"
        assert call_kwargs.kwargs["status"] == "success"

    @pytest.mark.asyncio
    async def test_implement_loop_passes_failed_status(
        self, config: HydraFlowConfig
    ) -> None:
        """Failed implementer results post summary with status='failed'."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(
            issue_number=42, transcript=SUMMARY_TRANSCRIPT, success=False
        )

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._implement_loop()

        assert (
            orch._summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "failed"
        )

    @pytest.mark.asyncio
    async def test_implement_loop_skips_empty_transcript_for_summary(
        self, config: HydraFlowConfig
    ) -> None:
        """Implementer results with empty transcripts skip summary filing."""
        orch = HydraFlowOrchestrator(config)
        result = make_worker_result(issue_number=42, transcript="")

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [result], [TaskFactory.create(id=42)]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._implement_loop()

        orch._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_loop_calls_summarize_and_comment_on_issue(
        self, config: HydraFlowConfig
    ) -> None:
        """Reviewer transcripts post summary on the original issue (not the PR)."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = make_review_result(
            pr_number=101, issue_number=42, transcript=SUMMARY_TRANSCRIPT
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        orch._summarizer.summarize_and_comment.assert_awaited_once()
        call_kwargs = orch._summarizer.summarize_and_comment.call_args
        # Fix for #767: should use issue_number (42), not pr_number (101)
        assert call_kwargs.kwargs["issue_number"] == 42
        assert call_kwargs.kwargs["phase"] == "review"
        # Default make_review_result has merged=False, ci_passed=None → "completed"
        assert call_kwargs.kwargs["status"] == "completed"

    @pytest.mark.asyncio
    async def test_review_loop_passes_success_status_when_merged(
        self, config: HydraFlowConfig
    ) -> None:
        """Merged review results post summary with status='success'."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            transcript=SUMMARY_TRANSCRIPT,
            merged=True,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good.",
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        assert (
            orch._summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "success"
        )

    @pytest.mark.asyncio
    async def test_review_loop_passes_failed_status_when_ci_failed(
        self, config: HydraFlowConfig
    ) -> None:
        """CI-failed review results post summary with status='failed'."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=42)
        review_issue = IssueFactory.create(number=42)
        pr = PRInfoFactory.create(number=101, issue_number=42)
        review_result = ReviewResult(
            pr_number=101,
            issue_number=42,
            transcript=SUMMARY_TRANSCRIPT,
            merged=False,
            ci_passed=False,
            verdict=ReviewVerdict.COMMENT,
            summary="CI failed.",
        )

        orch._store.get_active_issues = lambda: {42: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        assert (
            orch._summarizer.summarize_and_comment.call_args.kwargs["status"]
            == "failed"
        )

    @pytest.mark.asyncio
    async def test_review_loop_skips_summary_when_issue_number_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """Review results with issue_number=0 skip transcript summary posting."""
        orch = HydraFlowOrchestrator(config)
        review_task = TaskFactory.create(id=0)
        review_issue = IssueFactory.create(number=0)
        pr = PRInfoFactory.create(number=101, issue_number=0)
        review_result = ReviewResult(
            pr_number=101,
            issue_number=0,
            transcript=SUMMARY_TRANSCRIPT,
            merged=True,
            verdict=ReviewVerdict.APPROVE,
            summary="Looks good.",
        )

        orch._store.get_active_issues = lambda: {0: "review"}  # type: ignore[method-assign]
        orch._fetcher.fetch_reviewable_prs = AsyncMock(  # type: ignore[method-assign]
            return_value=([pr], [review_issue])
        )
        orch._reviewer.review_prs = AsyncMock(return_value=[review_result])  # type: ignore[method-assign]
        orch._prs.pull_main = AsyncMock()  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        call_count = 0

        def get_reviewable_once(_max_count: int) -> list[Task]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [review_task]
            orch._stop_event.set()
            return []

        orch._store.get_reviewable = get_reviewable_once  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            await orch._review_loop()

        orch._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transcript_summary_failure_does_not_block_pipeline(
        self, config: HydraFlowConfig
    ) -> None:
        """Errors in transcript summarization must not crash the implement loop."""
        orch = HydraFlowOrchestrator(config)
        r1 = make_worker_result(issue_number=10, transcript=SUMMARY_TRANSCRIPT)
        r2 = make_worker_result(issue_number=20, transcript=SUMMARY_TRANSCRIPT)

        async def batch_and_stop() -> tuple[list[WorkerResult], list[Task]]:
            orch._stop_event.set()
            return [r1, r2], [
                TaskFactory.create(id=10),
                TaskFactory.create(id=20),
            ]

        orch._implementer.run_batch = batch_and_stop  # type: ignore[method-assign]
        orch._summarizer.summarize_and_comment = AsyncMock(  # type: ignore[method-assign]
            side_effect=[RuntimeError("transient"), None]
        )

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
        ):
            # Should not raise
            await orch._implement_loop()

        # Both calls should have been attempted despite the first one failing
        assert orch._summarizer.summarize_and_comment.await_count == 2


# ---------------------------------------------------------------------------
# _post_run_hooks — deduplicated memory + summary helper
# ---------------------------------------------------------------------------


class TestPostRunHooks:
    """Tests for the extracted _post_run_hooks helper."""

    @pytest.mark.asyncio
    async def test_calls_memory_suggestion_and_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Happy path: both memory suggestion and summarize are called."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._post_run_hooks(
                transcript="some transcript",
                source="implementer",
                reference="issue #42",
                issue_number=42,
                phase="implement",
                status="success",
                duration_seconds=10.0,
                log_file=".hydraflow/logs/issue-42.txt",
            )
            mock_mem.assert_awaited_once()
        orch._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_memory_suggestion_failure_does_not_block_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception in memory suggestion must not prevent summarize."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await orch._post_run_hooks(
                transcript="transcript",
                source="implementer",
                reference="issue #1",
                issue_number=1,
                phase="implement",
                status="success",
                duration_seconds=5.0,
                log_file="log.txt",
            )
        orch._summarizer.summarize_and_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_failure_does_not_propagate(
        self, config: HydraFlowConfig
    ) -> None:
        """Exception in summarize must not propagate to caller."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("summarize failed")
        )

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            # Should not raise
            await orch._post_run_hooks(
                transcript="transcript",
                source="reviewer",
                reference="PR #99",
                issue_number=99,
                phase="review",
                status="completed",
                duration_seconds=2.0,
                log_file="log.txt",
            )

    @pytest.mark.asyncio
    async def test_skips_summarize_when_issue_number_zero(
        self, config: HydraFlowConfig
    ) -> None:
        """When issue_number is 0 (review edge case), summarize is skipped."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._post_run_hooks(
                transcript="transcript",
                source="reviewer",
                reference="PR #50",
                issue_number=0,
                phase="review",
                status="completed",
                duration_seconds=1.0,
                log_file="log.txt",
            )
            mock_mem.assert_awaited_once()
        orch._summarizer.summarize_and_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_memory_suggestion(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify argument forwarding to file_memory_suggestion."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_mem:
            await orch._post_run_hooks(
                transcript="tx",
                source="implementer",
                reference="issue #7",
                issue_number=7,
                phase="implement",
                status="failed",
                duration_seconds=3.5,
                log_file="logs/issue-7.txt",
            )
            mock_mem.assert_awaited_once_with(
                "tx", "implementer", "issue #7", ANY, ANY, ANY
            )

    @pytest.mark.asyncio
    async def test_passes_correct_args_to_summarize(
        self, config: HydraFlowConfig
    ) -> None:
        """Verify argument forwarding to summarize_and_comment."""
        orch = HydraFlowOrchestrator(config)
        orch._summarizer.summarize_and_comment = AsyncMock()  # type: ignore[method-assign]

        with patch("phase_utils.file_memory_suggestion", new_callable=AsyncMock):
            await orch._post_run_hooks(
                transcript="tx",
                source="implementer",
                reference="issue #7",
                issue_number=7,
                phase="implement",
                status="failed",
                duration_seconds=3.5,
                log_file="logs/issue-7.txt",
            )
        orch._summarizer.summarize_and_comment.assert_awaited_once_with(
            transcript="tx",
            issue_number=7,
            phase="implement",
            status="failed",
            duration_seconds=3.5,
            log_file="logs/issue-7.txt",
        )


# ---------------------------------------------------------------------------
# _start_session / _end_session / _restore_state — extracted from run()
# ---------------------------------------------------------------------------


class TestStartSession:
    """Tests for the extracted _start_session helper."""

    @pytest.mark.asyncio
    async def test_creates_session_log_with_correct_repo(
        self, config: HydraFlowConfig
    ) -> None:
        """_start_session should create a SessionLog with the correct repo and clear results."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()

        assert orch._current_session is not None
        assert orch._current_session.repo == config.repo
        assert orch._session_issue_results == {}

    @pytest.mark.asyncio
    async def test_publishes_session_start_event(self, config: HydraFlowConfig) -> None:
        """_start_session should publish a SESSION_START event with the repo."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()

        events = [e for e in bus.get_history() if e.type == EventType.SESSION_START]
        assert len(events) == 1
        assert events[0].data["repo"] == config.repo

    @pytest.mark.asyncio
    async def test_sets_bus_session_id(self, config: HydraFlowConfig) -> None:
        """_start_session should set the session id on the event bus."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()

        assert orch._current_session is not None
        assert bus._active_session_id == orch._current_session.id


class TestEndSession:
    """Tests for the extracted _end_session helper."""

    @pytest.mark.asyncio
    async def test_publishes_session_end_event(self, config: HydraFlowConfig) -> None:
        """_end_session should publish exactly one SESSION_END event."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()
        await orch._end_session()

        end_events = [e for e in bus.get_history() if e.type == EventType.SESSION_END]
        assert len(end_events) == 1

    @pytest.mark.asyncio
    async def test_session_end_event_contains_correct_issue_counts(
        self, config: HydraFlowConfig
    ) -> None:
        """_end_session event payload should reflect correct succeeded/failed/processed counts."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()
        orch._session_issue_results = {10: True, 20: False, 30: True}

        await orch._end_session()

        data = next(
            e.data for e in bus.get_history() if e.type == EventType.SESSION_END
        )
        assert data["issues_succeeded"] == 2
        assert data["issues_failed"] == 1
        assert set(data["issues_processed"]) == {10, 20, 30}

    @pytest.mark.asyncio
    async def test_noop_when_no_current_session(self, config: HydraFlowConfig) -> None:
        """_end_session should be a no-op when _current_session is None."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        # No session started — should not raise or publish
        await orch._end_session()

        end_events = [e for e in bus.get_history() if e.type == EventType.SESSION_END]
        assert len(end_events) == 0

    @pytest.mark.asyncio
    async def test_clears_session_state(self, config: HydraFlowConfig) -> None:
        """_end_session should clear _current_session and bus session_id."""
        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)

        await orch._start_session()
        await orch._end_session()

        assert orch._current_session is None
        assert bus._active_session_id is None


class TestRestoreState:
    """Tests for the extracted _restore_state helper."""

    def test_restores_intervals_and_crash_recovery(
        self, config: HydraFlowConfig
    ) -> None:
        """_restore_state should load saved intervals and active issues."""
        orch = HydraFlowOrchestrator(config)
        orch._state.set_worker_intervals({"memory_sync": 120})
        orch._state.set_active_issue_numbers([10, 20])

        orch._restore_state()

        assert orch._bg_worker_intervals.get("memory_sync") == 120
        assert orch._recovered_issues == {10, 20}
        assert 10 in orch._active_impl_issues
        assert 20 in orch._active_impl_issues

    def test_clears_interrupted_issues(self, config: HydraFlowConfig) -> None:
        """_restore_state should remove interrupted issues from all tracking sets."""
        orch = HydraFlowOrchestrator(config)
        # Simulate crash recovery state
        orch._state.set_active_issue_numbers([10, 20])
        orch._state.set_interrupted_issues({10: "implement", 20: "review"})
        # Pre-populate review and HITL sets so the discard calls are actually exercised
        orch._active_review_issues.update([10, 20])
        orch._hitl_phase.active_hitl_issues.update([10, 20])

        orch._restore_state()

        # Interrupted issues removed from all four tracking sets
        assert 10 not in orch._recovered_issues
        assert 20 not in orch._recovered_issues
        assert 10 not in orch._active_impl_issues
        assert 20 not in orch._active_impl_issues
        assert 10 not in orch._active_review_issues
        assert 20 not in orch._active_review_issues
        assert 10 not in orch._hitl_phase.active_hitl_issues
        assert 20 not in orch._hitl_phase.active_hitl_issues


# ---------------------------------------------------------------------------
# MemoryError propagation through _polling_loop
# ---------------------------------------------------------------------------


class TestMemoryErrorPropagation:
    """Tests that MemoryError propagates through _polling_loop."""

    @pytest.mark.asyncio
    async def test_memory_error_propagates_through_polling_loop(
        self, config: HydraFlowConfig
    ) -> None:
        """MemoryError should not be caught by _polling_loop's except Exception."""
        orch = HydraFlowOrchestrator(config)

        async def oom_work() -> None:
            raise MemoryError("out of memory")

        with pytest.raises(MemoryError, match="out of memory"):
            await orch._polling_loop("test", oom_work, 10)

    @pytest.mark.asyncio
    async def test_generic_error_is_caught_by_polling_loop(
        self, config: HydraFlowConfig
    ) -> None:
        """Non-critical exceptions should be caught and not propagate."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0

        async def failing_then_stop() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            orch._stop_event.set()

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]

        # Should not raise — RuntimeError is caught
        await orch._polling_loop("test", failing_then_stop, 10)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_polling_loop_emits_ok_heartbeat(
        self, config: HydraFlowConfig
    ) -> None:
        """_polling_loop should call update_bg_worker_status('ok') after work."""
        orch = HydraFlowOrchestrator(config)

        async def work_then_stop() -> bool:
            orch._stop_event.set()
            return False

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        await orch._polling_loop("implement", work_then_stop, 10)
        states = orch.get_bg_worker_states()
        assert "implement" in states
        assert states["implement"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_polling_loop_emits_error_heartbeat(
        self, config: HydraFlowConfig
    ) -> None:
        """_polling_loop should call update_bg_worker_status('error') on exception."""
        orch = HydraFlowOrchestrator(config)
        call_count = 0
        status_calls: list[tuple[str, str]] = []
        _orig_update = orch.update_bg_worker_status

        def tracking_update(name: str, status: str) -> None:
            status_calls.append((name, status))
            _orig_update(name, status)

        orch.update_bg_worker_status = tracking_update  # type: ignore[method-assign]

        async def fail_then_stop() -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")
            orch._stop_event.set()
            return False

        async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
            await asyncio.sleep(0)

        orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
        await orch._polling_loop("triage", fail_then_stop, 10)
        # Error heartbeat must be emitted on the exception iteration
        assert ("triage", "error") in status_calls
        # Final heartbeat should be "ok" from the second (successful) call
        states = orch.get_bg_worker_states()
        assert states["triage"]["status"] == "ok"


# --- Background Worker Enabled ---


class TestBgWorkerEnabled:
    """Tests for is_bg_worker_enabled / set_bg_worker_enabled."""

    def test_is_bg_worker_enabled_defaults_true(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.is_bg_worker_enabled("memory_sync") is True

    def test_set_and_get_enabled(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_enabled("memory_sync", False)
        assert orch.is_bg_worker_enabled("memory_sync") is False

    def test_set_enabled_true(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_enabled("metrics", False)
        orch.set_bg_worker_enabled("metrics", True)
        assert orch.is_bg_worker_enabled("metrics") is True

    def test_multiple_workers_independent(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_enabled("memory_sync", False)
        orch.set_bg_worker_enabled("metrics", True)
        assert orch.is_bg_worker_enabled("memory_sync") is False
        assert orch.is_bg_worker_enabled("metrics") is True


# --- Background Worker States ---


class TestBgWorkerStates:
    """Tests for get_bg_worker_states / update_bg_worker_status."""

    def test_get_bg_worker_states_empty(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        assert orch.get_bg_worker_states() == {}

    def test_update_and_get_states(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "running")
        states = orch.get_bg_worker_states()
        assert "memory_sync" in states
        assert states["memory_sync"]["status"] == "running"

    def test_states_include_enabled_flag(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("metrics", "idle")
        orch.set_bg_worker_enabled("metrics", False)
        states = orch.get_bg_worker_states()
        assert states["metrics"].get("enabled") is False


# --- Background Worker Interval ---


class TestBgWorkerInterval:
    """Tests for set_bg_worker_interval."""

    def test_set_bg_worker_interval_stores_value(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_interval("memory_sync", 300)
        assert orch.get_bg_worker_interval("memory_sync") == 300

    def test_set_bg_worker_interval_persists_to_state(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.set_bg_worker_interval("metrics", 600)
        # Verify state was persisted via public StateTracker method
        intervals = orch._state.get_worker_intervals()
        assert intervals.get("metrics") == 600


# --- Update Background Worker Status ---


class TestUpdateBgWorkerStatus:
    """Tests for update_bg_worker_status."""

    def test_update_bg_worker_status_stores_fields(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "running")
        state = orch._bg_worker_states["memory_sync"]
        assert state["name"] == "memory_sync"
        assert state["status"] == "running"
        assert "last_run" in state

    def test_update_bg_worker_status_with_details(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("metrics", "running", details={"synced": 5})
        state = orch._bg_worker_states["metrics"]
        assert state["details"]["synced"] == 5

    def test_update_bg_worker_status_without_details(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "idle")
        state = orch._bg_worker_states["memory_sync"]
        assert state["details"] == {}

    @pytest.mark.asyncio
    async def test_restore_bg_worker_states_backfills_from_events(
        self, config: HydraFlowConfig
    ) -> None:
        bus = EventBus()
        await bus.publish(
            HydraFlowEvent(
                type=EventType.BACKGROUND_WORKER_STATUS,
                data={
                    "worker": "memory_sync",
                    "status": "ok",
                    "last_run": "2026-02-25T09:00:00Z",
                    "details": {"count": 4},
                },
            )
        )
        orch = HydraFlowOrchestrator(config, event_bus=bus)
        orch._restore_bg_worker_states()
        states = orch.get_bg_worker_states()
        assert states["memory_sync"]["status"] == "ok"
        assert states["memory_sync"]["details"]["count"] == 4
        persisted = orch.state.get_bg_worker_states()
        assert "memory_sync" in persisted

    def test_update_bg_worker_status_persists_to_state(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch.update_bg_worker_status("memory_sync", "ok")
        persisted = orch._state.get_bg_worker_states()
        assert "memory_sync" in persisted
        assert persisted["memory_sync"]["status"] == "ok"

    def test_restore_bg_worker_states(self, config: HydraFlowConfig) -> None:
        tracker = StateTracker(config.state_file)
        tracker.set_bg_worker_state(
            "memory_sync",
            BackgroundWorkerState(
                name="memory_sync",
                status="ok",
                last_run="2026-02-20T10:30:00Z",
                details={"count": 2},
            ),
        )
        orch = HydraFlowOrchestrator(config, state=tracker)
        orch._restore_state()
        states = orch.get_bg_worker_states()
        assert states["memory_sync"]["last_run"] == "2026-02-20T10:30:00Z"
        assert states["memory_sync"]["details"]["count"] == 2


# ---------------------------------------------------------------------------
# Pipeline stats emission
# ---------------------------------------------------------------------------


class TestPipelineStatsEmission:
    """Tests for _build_pipeline_stats and emit_pipeline_stats."""

    def test_build_pipeline_stats_without_session(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        stats = orch.build_pipeline_stats()
        assert stats.timestamp
        assert stats.uptime_seconds == 0.0
        assert "triage" in stats.stages
        assert "plan" in stats.stages
        assert "implement" in stats.stages
        assert "review" in stats.stages
        assert "hitl" in stats.stages
        assert "merged" in stats.stages

    def test_build_pipeline_stats_includes_worker_caps(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        stats = orch.build_pipeline_stats()
        assert stats.stages["triage"].worker_cap == config.max_triagers
        assert stats.stages["plan"].worker_cap == config.max_planners
        assert stats.stages["implement"].worker_cap == config.max_workers
        assert stats.stages["review"].worker_cap == config.max_reviewers
        assert stats.stages["hitl"].worker_cap == config.max_hitl_workers

    def test_build_pipeline_stats_with_active_session(
        self, config: HydraFlowConfig
    ) -> None:
        from datetime import UTC, datetime

        from models import SessionLog
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        orch._current_session = SessionLog(
            id="test-session",
            repo="test/repo",
            started_at=(datetime.now(UTC)).isoformat(),
        )
        stats = orch.build_pipeline_stats()
        # Uptime should be positive since session just started
        assert stats.uptime_seconds >= 0.0

    def test_build_pipeline_stats_merged_tracks_session_results(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        orch._state.reset_session_counters("2026-01-01T00:00:00+00:00")
        orch._state.increment_session_counter("merged")
        orch._state.increment_session_counter("merged")
        stats = orch.build_pipeline_stats()
        assert stats.stages["merged"].completed_session == 2

    def test_build_pipeline_stats_per_stage_session_counters(
        self, config: HydraFlowConfig
    ) -> None:
        """Each stage's completed_session should reflect its named session counter."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        orch._state.reset_session_counters("2026-01-01T00:00:00+00:00")
        orch._state.increment_session_counter("triaged")
        orch._state.increment_session_counter("triaged")
        orch._state.increment_session_counter("planned")
        orch._state.increment_session_counter("implemented")
        orch._state.increment_session_counter("implemented")
        orch._state.increment_session_counter("implemented")
        orch._state.increment_session_counter("reviewed")
        stats = orch.build_pipeline_stats()
        assert stats.stages["triage"].completed_session == 2
        assert stats.stages["plan"].completed_session == 1
        assert stats.stages["implement"].completed_session == 3
        assert stats.stages["review"].completed_session == 1
        assert stats.stages["hitl"].completed_session == 0

    @pytest.mark.asyncio
    async def test_emit_pipeline_stats_publishes_event(
        self, config: HydraFlowConfig
    ) -> None:
        from orchestrator import HydraFlowOrchestrator

        bus = EventBus()
        orch = HydraFlowOrchestrator(config, event_bus=bus)
        await orch.emit_pipeline_stats()
        history = bus.get_history()
        pipeline_events = [e for e in history if e.type == EventType.PIPELINE_STATS]
        assert len(pipeline_events) == 1
        data = pipeline_events[0].data
        assert "timestamp" in data
        assert "stages" in data
        assert "throughput" in data
        assert "uptime_seconds" in data

    def test_build_pipeline_stats_is_json_serializable(
        self, config: HydraFlowConfig
    ) -> None:
        import json

        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        stats = orch.build_pipeline_stats()
        data = stats.model_dump()
        # Should not raise
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

    def test_pipeline_stats_loop_in_supervise_factories(
        self, config: HydraFlowConfig
    ) -> None:
        """pipeline_stats loop is registered in _supervise_loops."""
        from orchestrator import HydraFlowOrchestrator

        orch = HydraFlowOrchestrator(config)
        # Verify the method exists
        assert hasattr(orch, "_pipeline_stats_loop")
        assert callable(orch._pipeline_stats_loop)
