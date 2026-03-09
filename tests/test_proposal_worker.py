"""Tests for proposal_worker.py — event-driven pattern detection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventBus, EventType, HydraFlowEvent
from proposal_worker import ProposalWorker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker(
    *,
    state: MagicMock | None = None,
    prs: AsyncMock | None = None,
    stop_event: asyncio.Event | None = None,
) -> ProposalWorker:
    bus = EventBus()
    if state is None:
        state = MagicMock()
    if prs is None:
        prs = AsyncMock()
    if stop_event is None:
        stop_event = asyncio.Event()
    return ProposalWorker(
        bus=bus,
        state=state,
        prs=prs,
        stop_event=stop_event,
    )


# ---------------------------------------------------------------------------
# Signal filtering
# ---------------------------------------------------------------------------


class TestSignalFiltering:
    @pytest.mark.asyncio
    async def test_only_signal_types_accumulated(self) -> None:
        """Non-signal events are ignored."""
        _make_worker()  # ensure construction works
        queue: asyncio.Queue[HydraFlowEvent] = asyncio.Queue()

        # Push a non-signal event
        await queue.put(HydraFlowEvent(type=EventType.PHASE_CHANGE, data={}))
        # Push a signal event
        await queue.put(
            HydraFlowEvent(type=EventType.HARNESS_FAILURE_RECORDED, data={})
        )

        # Manually run one iteration step
        pending: set[EventType] = set()
        while not queue.empty():
            event = queue.get_nowait()
            from proposal_worker import _SIGNAL_TYPES

            if event.type in _SIGNAL_TYPES:
                pending.add(event.type)

        assert EventType.HARNESS_FAILURE_RECORDED in pending
        assert EventType.PHASE_CHANGE not in pending

    def test_signal_types_are_correct(self) -> None:
        from proposal_worker import _SIGNAL_TYPES

        assert EventType.REVIEW_INSIGHT_RECORDED in _SIGNAL_TYPES
        assert EventType.HARNESS_FAILURE_RECORDED in _SIGNAL_TYPES
        assert EventType.RETROSPECTIVE_RECORDED in _SIGNAL_TYPES
        assert len(_SIGNAL_TYPES) == 3


# ---------------------------------------------------------------------------
# _process_signals dispatch
# ---------------------------------------------------------------------------


class TestProcessSignals:
    @pytest.mark.asyncio
    async def test_review_signal_calls_check_review_patterns(self) -> None:
        worker = _make_worker()
        worker._check_review_patterns = AsyncMock()
        await worker._process_signals({EventType.REVIEW_INSIGHT_RECORDED})
        worker._check_review_patterns.assert_called_once()

    @pytest.mark.asyncio
    async def test_harness_signal_calls_check_harness_patterns(self) -> None:
        worker = _make_worker()
        worker._check_harness_patterns = AsyncMock()
        await worker._process_signals({EventType.HARNESS_FAILURE_RECORDED})
        worker._check_harness_patterns.assert_called_once()

    @pytest.mark.asyncio
    async def test_retro_signal_calls_check_retro_patterns(self) -> None:
        worker = _make_worker()
        worker._check_retro_patterns = AsyncMock()
        await worker._process_signals({EventType.RETROSPECTIVE_RECORDED})
        worker._check_retro_patterns.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_in_handler_does_not_crash(self) -> None:
        worker = _make_worker()
        worker._check_review_patterns = AsyncMock(side_effect=RuntimeError("boom"))
        worker._check_harness_patterns = AsyncMock()
        await worker._process_signals(
            {EventType.REVIEW_INSIGHT_RECORDED, EventType.HARNESS_FAILURE_RECORDED}
        )
        # Harness check should still run despite review check failing
        worker._check_harness_patterns.assert_called_once()


# ---------------------------------------------------------------------------
# _check_harness_patterns
# ---------------------------------------------------------------------------


class TestCheckHarnessPatterns:
    @pytest.mark.asyncio
    async def test_skips_when_no_load_method(self) -> None:
        state = MagicMock(spec=[])  # no load_recent_harness_failures
        worker = _make_worker(state=state)
        await worker._check_harness_patterns()  # should not raise

    @pytest.mark.asyncio
    async def test_skips_when_no_records(self) -> None:
        state = MagicMock()
        state.load_recent_harness_failures.return_value = []
        state.get_proposed_categories.return_value = set()
        worker = _make_worker(state=state)
        await worker._check_harness_patterns()
        # No proposal should be filed
        worker._prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_files_proposal_for_recurring_pattern(self) -> None:
        state = MagicMock()
        state.load_recent_harness_failures.return_value = [
            {
                "issue_number": i,
                "category": "ci_failure",
                "subcategories": [],
                "details": "CI failed",
                "stage": "",
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
            for i in range(5)
        ]
        state.get_proposed_categories.return_value = set()
        prs = AsyncMock()
        worker = _make_worker(state=state, prs=prs)
        await worker._check_harness_patterns()
        prs.create_issue.assert_called_once()
        title = prs.create_issue.call_args[0][0]
        assert "[Harness Insight]" in title


# ---------------------------------------------------------------------------
# _check_retro_patterns
# ---------------------------------------------------------------------------


class TestCheckRetroPatterns:
    @pytest.mark.asyncio
    async def test_skips_when_no_load_method(self) -> None:
        state = MagicMock(spec=[])
        worker = _make_worker(state=state)
        await worker._check_retro_patterns()

    @pytest.mark.asyncio
    async def test_skips_when_below_threshold(self) -> None:
        state = MagicMock()
        state.load_recent_retrospectives.return_value = [
            {"issue_number": 1, "quality_fix_rounds": 0}
        ]
        worker = _make_worker(state=state)
        worker._retro_threshold = 5
        await worker._check_retro_patterns()
        worker._prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_files_proposal_for_high_quality_fix_rate(self) -> None:
        state = MagicMock()
        # All entries have quality fix rounds > 0
        state.load_recent_retrospectives.return_value = [
            {
                "issue_number": i,
                "pr_number": i + 100,
                "timestamp": "2024-01-01T00:00:00+00:00",
                "quality_fix_rounds": 2,
                "ci_fix_rounds": 0,
                "plan_accuracy_pct": 90,
            }
            for i in range(10)
        ]
        state.get_proposed_categories.return_value = set()
        prs = AsyncMock()
        worker = _make_worker(state=state, prs=prs)
        worker._retro_threshold = 5
        await worker._check_retro_patterns()
        prs.create_issue.assert_called_once()
        title = prs.create_issue.call_args[0][0]
        assert "[Retro]" in title
        assert "quality-fix" in title.lower()


# ---------------------------------------------------------------------------
# _check_review_patterns
# ---------------------------------------------------------------------------


class TestCheckReviewPatterns:
    @pytest.mark.asyncio
    async def test_skips_when_no_load_method(self) -> None:
        state = MagicMock(spec=[])
        worker = _make_worker(state=state)
        await worker._check_review_patterns()

    @pytest.mark.asyncio
    async def test_skips_when_no_records(self) -> None:
        state = MagicMock()
        state.load_recent_review_records.return_value = []
        worker = _make_worker(state=state)
        await worker._check_review_patterns()
        worker._prs.create_issue.assert_not_called()


# ---------------------------------------------------------------------------
# run() lifecycle
# ---------------------------------------------------------------------------


class TestRunLifecycle:
    @pytest.mark.asyncio
    async def test_run_subscribes_and_unsubscribes(self) -> None:
        stop = asyncio.Event()
        worker = _make_worker(stop_event=stop)

        # Stop immediately
        stop.set()
        await worker.run()

        # After run completes, the worker should have unsubscribed
        assert len(worker._bus._subscribers) == 0


# ---------------------------------------------------------------------------
# _file_proposal
# ---------------------------------------------------------------------------


class TestFileProposal:
    @pytest.mark.asyncio
    async def test_files_issue_and_marks_proposed(self) -> None:
        state = MagicMock()
        prs = AsyncMock()
        worker = _make_worker(state=state, prs=prs)

        await worker._file_proposal("title", "body", "harness", "ci_failure")

        prs.create_issue.assert_called_once()
        state.mark_category_proposed.assert_called_once_with("harness", "ci_failure")

    @pytest.mark.asyncio
    async def test_tolerates_create_issue_failure(self) -> None:
        state = MagicMock()
        prs = AsyncMock()
        prs.create_issue.side_effect = RuntimeError("API down")
        worker = _make_worker(state=state, prs=prs)

        await worker._file_proposal("title", "body", "harness", "ci_failure")
        # Should not raise, and should not mark as proposed
        state.mark_category_proposed.assert_not_called()
