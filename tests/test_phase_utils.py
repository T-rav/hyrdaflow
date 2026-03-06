"""Tests for phase_utils.py — shared phase utilities."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventType
from harness_insights import FailureCategory, HarnessInsightStore
from models import PipelineStage
from phase_utils import (
    escalate_to_hitl,
    next_adr_number,
    publish_review_status,
    record_harness_failure,
    run_concurrent_batch,
    run_refilling_pool,
    safe_file_memory_suggestion,
    store_lifecycle,
)

# ---------------------------------------------------------------------------
# run_concurrent_batch
# ---------------------------------------------------------------------------


class TestRunConcurrentBatch:
    """Tests for run_concurrent_batch."""

    @pytest.mark.asyncio
    async def test_returns_all_results(self) -> None:
        """All items should produce results."""
        stop = asyncio.Event()

        async def worker(idx: int, item: int) -> int:
            return item * 2

        results = await run_concurrent_batch([1, 2, 3], worker, stop)

        assert sorted(results) == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self) -> None:
        """Empty input should return empty list."""
        stop = asyncio.Event()

        async def worker(idx: int, item: int) -> int:
            return item

        results = await run_concurrent_batch([], worker, stop)

        assert results == []

    @pytest.mark.asyncio
    async def test_stop_event_cancels_remaining(self) -> None:
        """Setting stop_event after first completion cancels rest."""
        stop = asyncio.Event()
        completed = []

        async def worker(idx: int, item: int) -> int:
            if item == 1:
                # First item completes immediately
                completed.append(item)
                stop.set()
                return item
            # Other items sleep so they're still pending when stop fires
            await asyncio.sleep(10)
            completed.append(item)
            return item

        results = await run_concurrent_batch([1, 2, 3], worker, stop)

        # Only the first item should have completed
        assert len(results) < 3
        assert 1 in results

    @pytest.mark.asyncio
    async def test_external_cancel_cleans_up(self) -> None:
        """Cancelling the outer coroutine should cancel all pending tasks."""
        stop = asyncio.Event()
        started = asyncio.Event()

        async def worker(idx: int, item: int) -> int:
            started.set()
            await asyncio.sleep(100)
            return item

        task = asyncio.create_task(run_concurrent_batch([1, 2, 3], worker, stop))

        # Wait for at least one worker to start
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_preserves_worker_exceptions(self) -> None:
        """Worker exceptions should propagate."""
        stop = asyncio.Event()

        async def worker(idx: int, item: int) -> int:
            raise ValueError(f"bad item {item}")

        with pytest.raises(ValueError, match="bad item"):
            await run_concurrent_batch([1], worker, stop)


# ---------------------------------------------------------------------------
# run_refilling_pool
# ---------------------------------------------------------------------------


class TestRunRefillingPool:
    """Tests for run_refilling_pool — slot-filling worker pool."""

    @pytest.mark.asyncio
    async def test_processes_all_items(self) -> None:
        """All supplied items should be processed."""
        items = list(range(5))
        stop = asyncio.Event()

        def supply() -> list[int]:
            if items:
                return [items.pop(0)]
            return []

        async def worker(_idx: int, item: int) -> int:
            return item * 2

        results = await run_refilling_pool(supply, worker, 3, stop)
        assert sorted(results) == [0, 2, 4, 6, 8]

    @pytest.mark.asyncio
    async def test_empty_supply_returns_empty(self) -> None:
        """Empty supply should return no results."""
        stop = asyncio.Event()

        results = await run_refilling_pool(lambda: [], lambda i, x: x, 3, stop)
        assert results == []

    @pytest.mark.asyncio
    async def test_refills_slots_immediately(self) -> None:
        """Slots should be refilled as soon as a worker completes."""
        items = list(range(6))
        max_concurrent = 2
        stop = asyncio.Event()
        concurrent_count = 0
        max_observed_concurrent = 0

        def supply() -> list[int]:
            if items:
                return [items.pop(0)]
            return []

        async def worker(_idx: int, item: int) -> int:
            nonlocal concurrent_count, max_observed_concurrent
            concurrent_count += 1
            max_observed_concurrent = max(max_observed_concurrent, concurrent_count)
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            return item

        await run_refilling_pool(supply, worker, max_concurrent, stop)
        assert max_observed_concurrent <= max_concurrent

    @pytest.mark.asyncio
    async def test_new_items_picked_up_while_workers_busy(self) -> None:
        """Items added to supply mid-flight should be picked up as slots free."""
        available: list[int] = [1, 2]
        stop = asyncio.Event()
        processed: list[int] = []
        calls = 0

        def supply() -> list[int]:
            nonlocal calls
            calls += 1
            # After first two are dispatched, add more on refill
            if calls == 3:
                available.extend([3, 4])
            if available:
                return [available.pop(0)]
            return []

        async def worker(_idx: int, item: int) -> int:
            await asyncio.sleep(0.01)
            processed.append(item)
            return item

        results = await run_refilling_pool(supply, worker, 2, stop)
        assert sorted(results) == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_stop_event_cancels_pool(self) -> None:
        """Setting stop_event should end the pool."""
        items = list(range(10))
        stop = asyncio.Event()

        def supply() -> list[int]:
            if items:
                return [items.pop(0)]
            return []

        async def worker(_idx: int, item: int) -> int:
            if item == 2:
                stop.set()
            await asyncio.sleep(0.01)
            return item

        results = await run_refilling_pool(supply, worker, 2, stop)
        # Should have processed some but not all 10
        assert len(results) < 10

    @pytest.mark.asyncio
    async def test_worker_exception_logged_not_fatal(self) -> None:
        """Non-fatal worker exceptions are logged; other workers continue."""
        items = [1, 2, 3]
        stop = asyncio.Event()

        def supply() -> list[int]:
            if items:
                return [items.pop(0)]
            return []

        async def worker(_idx: int, item: int) -> int:
            if item == 2:
                raise ValueError("bad")
            return item

        results = await run_refilling_pool(supply, worker, 1, stop)
        assert sorted(results) == [1, 3]

    @pytest.mark.asyncio
    async def test_fatal_errors_propagate(self) -> None:
        """AuthenticationError and similar should propagate immediately."""
        from subprocess_util import AuthenticationError

        items = [1, 2]
        stop = asyncio.Event()

        def supply() -> list[int]:
            if items:
                return [items.pop(0)]
            return []

        async def worker(_idx: int, item: int) -> int:
            if item == 1:
                raise AuthenticationError("auth failed")
            return item

        with pytest.raises(AuthenticationError):
            await run_refilling_pool(supply, worker, 2, stop)

    @pytest.mark.asyncio
    async def test_external_cancel_cleans_up_pending(self) -> None:
        """Cancelling the pool coroutine should cancel all pending workers."""
        stop = asyncio.Event()
        started = asyncio.Event()

        def supply() -> list[int]:
            return [1]

        async def worker(_idx: int, _item: int) -> int:
            started.set()
            await asyncio.sleep(100)
            return 1

        task = asyncio.create_task(run_refilling_pool(supply, worker, 2, stop))
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# escalate_to_hitl
# ---------------------------------------------------------------------------


class TestEscalateToHitl:
    """Tests for escalate_to_hitl."""

    @pytest.mark.asyncio
    async def test_records_state(self) -> None:
        """Should call set_hitl_origin, set_hitl_cause, record_hitl_escalation."""
        state = MagicMock()
        prs = AsyncMock()

        await escalate_to_hitl(
            state,
            prs,
            issue_number=42,
            cause="Plan failed",
            origin_label="hydraflow-plan",
            hitl_label="hydraflow-hitl",
        )

        state.set_hitl_origin.assert_called_once_with(42, "hydraflow-plan")
        state.set_hitl_cause.assert_called_once_with(42, "Plan failed")
        state.record_hitl_escalation.assert_called_once()

    @pytest.mark.asyncio
    async def test_swaps_labels(self) -> None:
        """Should call swap_pipeline_labels with the HITL label."""
        state = MagicMock()
        prs = AsyncMock()

        await escalate_to_hitl(
            state,
            prs,
            issue_number=42,
            cause="Failed",
            origin_label="hydraflow-ready",
            hitl_label="hydraflow-hitl",
        )

        prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-hitl")


# ---------------------------------------------------------------------------
# safe_file_memory_suggestion
# ---------------------------------------------------------------------------


class TestSafeFileMemorySuggestion:
    """Tests for safe_file_memory_suggestion."""

    @pytest.mark.asyncio
    async def test_delegates_to_file_memory_suggestion(self) -> None:
        """Should call file_memory_suggestion with correct args."""
        config = MagicMock()
        prs = AsyncMock()
        state = MagicMock()

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_fms:
            await safe_file_memory_suggestion(
                "transcript text",
                "planner",
                "issue #42",
                config,
                prs,
                state,
            )

            mock_fms.assert_awaited_once_with(
                "transcript text",
                "planner",
                "issue #42",
                config,
                prs,
                state,
            )

    @pytest.mark.asyncio
    async def test_swallows_exception(self) -> None:
        """Should not raise when file_memory_suggestion fails."""
        config = MagicMock()
        prs = AsyncMock()
        state = MagicMock()

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ):
            # Should not raise
            await safe_file_memory_suggestion(
                "transcript", "planner", "issue #42", config, prs, state
            )

    @pytest.mark.asyncio
    async def test_logs_error_on_exception(self) -> None:
        """Should call logger.exception on failure."""
        config = MagicMock()
        prs = AsyncMock()
        state = MagicMock()

        with (
            patch(
                "phase_utils.file_memory_suggestion",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API error"),
            ),
            patch("phase_utils.logger") as mock_logger,
        ):
            await safe_file_memory_suggestion(
                "transcript", "planner", "issue #42", config, prs, state
            )

            mock_logger.exception.assert_called_once()
            assert "issue #42" in mock_logger.exception.call_args.args[1]


# ---------------------------------------------------------------------------
# store_lifecycle
# ---------------------------------------------------------------------------


class TestStoreLifecycle:
    """Tests for store_lifecycle async context manager."""

    @pytest.mark.asyncio
    async def test_marks_active_and_complete(self) -> None:
        """Should call mark_active on enter and mark_complete on exit."""
        store = MagicMock()

        async with store_lifecycle(store, 42, "plan"):
            store.mark_active.assert_called_once_with(42, "plan")
            store.mark_complete.assert_not_called()

        store.mark_complete.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_marks_complete_on_exception(self) -> None:
        """Should call mark_complete even when body raises."""
        store = MagicMock()

        with pytest.raises(ValueError, match="boom"):
            async with store_lifecycle(store, 42, "implement"):
                raise ValueError("boom")

        store.mark_active.assert_called_once_with(42, "implement")
        store.mark_complete.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# record_harness_failure
# ---------------------------------------------------------------------------


class TestRecordHarnessFailure:
    """Tests for record_harness_failure."""

    def test_appends_failure_record_to_store(self, tmp_path: Path) -> None:
        """Should append a FailureRecord with correct fields to the store."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Missing required sections",
            stage=PipelineStage.PLAN,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].issue_number == 42
        assert records[0].category == FailureCategory.PLAN_VALIDATION
        assert records[0].stage == "plan"
        assert records[0].pr_number == 0

    def test_noop_when_store_is_none(self) -> None:
        """Should not raise when harness_insights is None."""
        record_harness_failure(
            None,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Some error",
            stage=PipelineStage.PLAN,
        )

    def test_catches_exception_from_store(self) -> None:
        """Should catch and log exceptions from the store without propagating."""
        mock_store = MagicMock()
        mock_store.append_failure.side_effect = RuntimeError("disk full")

        with patch("phase_utils.logger") as mock_logger:
            record_harness_failure(
                mock_store,
                42,
                FailureCategory.PLAN_VALIDATION,
                "Some error",
                stage=PipelineStage.PLAN,
            )

            mock_logger.warning.assert_called_once()
            logged_call = mock_logger.warning.call_args
            assert logged_call.args[0].startswith(
                "Failed to record harness failure for issue"
            )
            assert logged_call.args[1] == 42
            assert logged_call.kwargs["exc_info"] is True

    def test_passes_pr_number_to_record(self, tmp_path: Path) -> None:
        """Should set pr_number on the FailureRecord when provided."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            66,
            FailureCategory.REVIEW_REJECTION,
            "Review verdict: request_changes",
            stage=PipelineStage.REVIEW,
            pr_number=200,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert records[0].pr_number == 200
        assert records[0].stage == "review"

    def test_extracts_subcategories(self, tmp_path: Path) -> None:
        """Should extract subcategories from the details string."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        store = HarnessInsightStore(memory_dir)

        record_harness_failure(
            store,
            42,
            FailureCategory.QUALITY_GATE,
            "ruff lint error: missing import",
            stage=PipelineStage.IMPLEMENT,
        )

        records = store.load_recent()
        assert len(records) == 1
        assert "lint_error" in records[0].subcategories


# ---------------------------------------------------------------------------
# publish_review_status
# ---------------------------------------------------------------------------


class TestPublishReviewStatus:
    """Tests for publish_review_status."""

    @pytest.mark.asyncio
    async def test_publishes_review_update_event(self) -> None:
        """Should publish a REVIEW_UPDATE event via the bus."""
        from tests.conftest import PRInfoFactory

        bus = AsyncMock()
        pr = PRInfoFactory.create(number=101, issue_number=42)

        await publish_review_status(bus, pr, worker_id=3, status="start")

        bus.publish.assert_awaited_once()
        event = bus.publish.call_args[0][0]
        assert event.type == EventType.REVIEW_UPDATE
        assert event.data == {
            "pr": 101,
            "issue": 42,
            "worker": 3,
            "status": "start",
            "role": "reviewer",
        }

    @pytest.mark.asyncio
    async def test_includes_correct_data_fields(self) -> None:
        """Should include all five data keys with correct values."""
        from tests.conftest import PRInfoFactory

        bus = AsyncMock()
        pr = PRInfoFactory.create(number=200, issue_number=66)

        await publish_review_status(bus, pr, worker_id=7, status="ci_fix")

        event = bus.publish.call_args[0][0]
        data = event.data
        assert data["pr"] == 200
        assert data["issue"] == 66
        assert data["worker"] == 7
        assert data["status"] == "ci_fix"
        assert data["role"] == "reviewer"

    @pytest.mark.asyncio
    async def test_role_is_always_reviewer(self) -> None:
        """Role should always be 'reviewer' regardless of status."""
        from tests.conftest import PRInfoFactory

        bus = AsyncMock()
        pr = PRInfoFactory.create()

        await publish_review_status(bus, pr, worker_id=0, status="done")

        event = bus.publish.call_args[0][0]
        assert event.data["role"] == "reviewer"


# ---------------------------------------------------------------------------
# next_adr_number
# ---------------------------------------------------------------------------


class TestNextAdrNumber:
    def test_returns_one_for_empty_dir(self, tmp_path: Path) -> None:
        assert next_adr_number(tmp_path) == 1

    def test_returns_one_for_missing_dir(self, tmp_path: Path) -> None:
        assert next_adr_number(tmp_path / "nonexistent") == 1

    def test_increments_past_highest(self, tmp_path: Path) -> None:
        (tmp_path / "0001-first.md").touch()
        (tmp_path / "0003-third.md").touch()
        assert next_adr_number(tmp_path) == 4

    def test_ignores_non_adr_files(self, tmp_path: Path) -> None:
        (tmp_path / "0005-fifth.md").touch()
        (tmp_path / "README.md").touch()
        (tmp_path / "template.md").touch()
        assert next_adr_number(tmp_path) == 6
