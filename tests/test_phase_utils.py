"""Tests for phase_utils.py — shared phase utilities."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from phase_utils import (
    escalate_to_hitl,
    run_concurrent_batch,
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
