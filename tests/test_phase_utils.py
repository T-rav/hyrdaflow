"""Tests for phase_utils.py — shared phase utilities."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from adr_utils import next_adr_number
from events import EventType
from exception_classify import LIKELY_BUG_EXCEPTIONS
from harness_insights import FailureCategory, HarnessInsightStore
from models import PipelineStage
from phase_utils import (
    MemorySuggester,
    PipelineEscalator,
    escalate_to_hitl,
    is_likely_bug,
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
    @pytest.mark.asyncio
    async def test_records_state(self) -> None:
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
    @pytest.mark.asyncio
    async def test_delegates_to_file_memory_suggestion(self) -> None:
        config = MagicMock()

        with patch(
            "phase_utils.file_memory_suggestion", new_callable=AsyncMock
        ) as mock_fms:
            await safe_file_memory_suggestion(
                "transcript text",
                "planner",
                "issue #42",
                config,
            )

            mock_fms.assert_awaited_once_with(
                "transcript text",
                "planner",
                "issue #42",
                config,
            )

    @pytest.mark.asyncio
    async def test_swallows_exception(self) -> None:
        config = MagicMock()

        with patch(
            "phase_utils.file_memory_suggestion",
            new_callable=AsyncMock,
            side_effect=RuntimeError("API error"),
        ) as mock_suggest:
            # Should not raise
            await safe_file_memory_suggestion(
                "transcript", "planner", "issue #42", config
            )
        mock_suggest.assert_awaited_once()  # confirms RuntimeError was caught and swallowed

    @pytest.mark.asyncio
    async def test_logs_error_on_exception(self) -> None:
        config = MagicMock()

        with (
            patch(
                "phase_utils.file_memory_suggestion",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API error"),
            ),
            patch("phase_utils.logger") as mock_logger,
        ):
            await safe_file_memory_suggestion(
                "transcript", "planner", "issue #42", config
            )

            mock_logger.exception.assert_called_once()
            assert "issue #42" in mock_logger.exception.call_args.args[1]


# ---------------------------------------------------------------------------
# store_lifecycle
# ---------------------------------------------------------------------------


class TestStoreLifecycle:
    @pytest.mark.asyncio
    async def test_marks_active_and_complete(self) -> None:
        store = MagicMock()

        async with store_lifecycle(store, 42, "plan"):
            store.mark_active.assert_called_once_with(42, "plan")
            store.mark_complete.assert_not_called()

        store.mark_complete.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_marks_complete_on_exception(self) -> None:
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
    def test_appends_failure_record_to_store(self, tmp_path: Path) -> None:
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
        result = record_harness_failure(
            None,
            42,
            FailureCategory.PLAN_VALIDATION,
            "Some error",
            stage=PipelineStage.PLAN,
        )
        assert result is None  # noop when store is None

    def test_catches_exception_from_store(self) -> None:
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
    @pytest.mark.asyncio
    async def test_publishes_review_update_event(self) -> None:
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
    @pytest.fixture(autouse=True)
    def _clear_assigned(self) -> Generator[None, None, None]:
        """Reset the module-level assigned set before and after each test."""
        import adr_utils

        adr_utils._assigned_adr_numbers.clear()
        yield
        adr_utils._assigned_adr_numbers.clear()

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

    def test_concurrent_calls_return_unique_numbers(self, tmp_path: Path) -> None:
        """Simulate concurrent workers — each call must return a distinct number."""
        (tmp_path / "0002-existing.md").touch()
        results = [next_adr_number(tmp_path) for _ in range(5)]
        assert results == [3, 4, 5, 6, 7]

    def test_scans_primary_adr_dir(self, tmp_path: Path) -> None:
        """The primary repo dir should be checked even if the local dir differs."""
        local = tmp_path / "worktree" / "docs" / "adr"
        local.mkdir(parents=True)
        (local / "0001-local.md").touch()

        primary = tmp_path / "primary" / "docs" / "adr"
        primary.mkdir(parents=True)
        (primary / "0010-primary.md").touch()

        result = next_adr_number(local, primary_adr_dir=primary)
        assert result == 11

    def test_assigned_set_tracks_numbers(self, tmp_path: Path) -> None:
        """Returned numbers must be recorded in the module-level set."""
        import adr_utils

        next_adr_number(tmp_path)
        next_adr_number(tmp_path)
        assert adr_utils._assigned_adr_numbers == {1, 2}

    def test_assigned_numbers_override_disk(self, tmp_path: Path) -> None:
        """Previously assigned numbers beat what's on disk."""
        import adr_utils

        adr_utils._assigned_adr_numbers.add(20)
        result = next_adr_number(tmp_path)
        assert result == 21


# ---------------------------------------------------------------------------
# Exception classification (#2065)
# ---------------------------------------------------------------------------


class TestIsLikelyBug:
    @pytest.mark.parametrize(
        "exc",
        [
            TypeError("bad type"),
            KeyError("missing"),
            AttributeError("no attr"),
            ValueError("bad value"),
            IndexError("out of range"),
            NotImplementedError("todo"),
        ],
    )
    def test_bug_exceptions_detected(self, exc: BaseException) -> None:
        assert is_likely_bug(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("transient"),
            OSError("disk full"),
            TimeoutError("timed out"),
            ConnectionError("lost"),
            PermissionError("access denied"),
        ],
    )
    def test_transient_exceptions_not_bugs(self, exc: BaseException) -> None:
        assert is_likely_bug(exc) is False

    def test_likely_bug_exceptions_tuple_is_nonempty(self) -> None:
        assert len(LIKELY_BUG_EXCEPTIONS) >= 5

    def test_subclass_of_likely_bug_is_detected(self) -> None:
        """Subclasses of bug exception types should also be caught."""

        class CustomKeyError(KeyError):
            pass

        assert is_likely_bug(CustomKeyError("sub")) is True


# ---------------------------------------------------------------------------
# MemorySuggester
# ---------------------------------------------------------------------------


class TestMemorySuggester:
    @pytest.mark.asyncio
    async def test_delegates_to_safe_file_memory_suggestion(self) -> None:
        config = MagicMock()

        suggest = MemorySuggester(config)

        with patch(
            "phase_utils.safe_file_memory_suggestion", new_callable=AsyncMock
        ) as mock_sfms:
            await suggest("transcript text", "planner", "issue #42")

            mock_sfms.assert_awaited_once_with(
                "transcript text",
                "planner",
                "issue #42",
                config,
            )

    @pytest.mark.asyncio
    async def test_multiple_calls_reuse_bound_args(self) -> None:
        """Successive calls should reuse the same bound config."""
        config = MagicMock()

        suggest = MemorySuggester(config)

        with patch(
            "phase_utils.safe_file_memory_suggestion", new_callable=AsyncMock
        ) as mock_sfms:
            await suggest("t1", "src1", "ref1")
            await suggest("t2", "src2", "ref2")

            assert mock_sfms.await_count == 2
            # Both calls use the same bound config
            assert mock_sfms.call_args_list[0].args[3:] == (config,)
            assert mock_sfms.call_args_list[1].args[3:] == (config,)


# ---------------------------------------------------------------------------
# PipelineEscalator
# ---------------------------------------------------------------------------


class TestPipelineEscalator:
    def _make_escalator(
        self,
        *,
        state: MagicMock | None = None,
        prs: AsyncMock | None = None,
        store: MagicMock | None = None,
        harness_insights: MagicMock | None = None,
        origin_label: str = "hydraflow-plan",
        hitl_label: str = "hydraflow-hitl",
        diagnose_label: str = "hydraflow-diagnose",
        stage: PipelineStage = PipelineStage.PLAN,
    ) -> PipelineEscalator:
        return PipelineEscalator(
            state=state or MagicMock(),
            prs=prs or AsyncMock(),
            store=store or MagicMock(),
            harness_insights=harness_insights,
            origin_label=origin_label,
            hitl_label=hitl_label,
            diagnose_label=diagnose_label,
            stage=stage,
        )

    @pytest.mark.asyncio
    async def test_calls_escalate_to_diagnostic(self) -> None:
        state = MagicMock()
        prs = AsyncMock()
        escalator = self._make_escalator(state=state, prs=prs)
        issue = MagicMock(id=42)

        await escalator(
            issue,
            cause="Plan failed",
            details="validation errors",
            category=FailureCategory.PLAN_VALIDATION,
        )

        state.set_escalation_context.assert_called_once()
        state.set_hitl_origin.assert_called_once_with(42, "hydraflow-plan")
        state.set_hitl_cause.assert_called_once_with(42, "Plan failed")
        state.record_hitl_escalation.assert_called_once()
        prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-diagnose")

    @pytest.mark.asyncio
    async def test_enqueues_transition(self) -> None:
        store = MagicMock()
        issue = MagicMock(id=10)
        escalator = self._make_escalator(store=store)

        await escalator(
            issue,
            cause="cap exceeded",
            details="details",
            category=FailureCategory.HITL_ESCALATION,
        )

        store.enqueue_transition.assert_called_once_with(issue, "diagnose")

    @pytest.mark.asyncio
    async def test_records_harness_failure(self) -> None:
        harness = MagicMock()
        escalator = self._make_escalator(
            harness_insights=harness, stage=PipelineStage.IMPLEMENT
        )
        issue = MagicMock(id=7)

        await escalator(
            issue,
            cause="zero diff",
            details="No changes produced",
            category=FailureCategory.HITL_ESCALATION,
        )

        harness.append_failure.assert_called_once()
        record = harness.append_failure.call_args.args[0]
        assert record.issue_number == 7
        assert record.category == FailureCategory.HITL_ESCALATION
        assert record.stage == PipelineStage.IMPLEMENT
        assert "No changes produced" in record.details

    @pytest.mark.asyncio
    async def test_none_harness_insights_does_not_raise(self) -> None:
        escalator = self._make_escalator(harness_insights=None)
        issue = MagicMock(id=1)

        # Should not raise — harness_insights=None is a safe noop
        await escalator(
            issue,
            cause="test",
            details="test details",
            category=FailureCategory.PLAN_VALIDATION,
        )
        # harness_insights is None so no recording attempt should be made
        assert escalator._harness_insights is None

    @pytest.mark.asyncio
    async def test_uses_configured_labels_and_stage(self) -> None:
        state = MagicMock()
        prs = AsyncMock()
        harness = MagicMock()
        escalator = PipelineEscalator(
            state=state,
            prs=prs,
            store=MagicMock(),
            harness_insights=harness,
            origin_label="hydraflow-ready",
            hitl_label="hydraflow-hitl",
            stage=PipelineStage.IMPLEMENT,
        )
        issue = MagicMock(id=99)

        await escalator(
            issue,
            cause="cap exceeded",
            details="attempt cap",
            category=FailureCategory.HITL_ESCALATION,
        )

        state.set_hitl_origin.assert_called_once_with(99, "hydraflow-ready")
        record = harness.append_failure.call_args.args[0]
        assert record.stage == PipelineStage.IMPLEMENT


# ---------------------------------------------------------------------------
# _fill_pending_slots (private helper)
# ---------------------------------------------------------------------------


class TestFillPendingSlots:
    @pytest.mark.asyncio
    async def test_empty_supply_leaves_pending_empty(self) -> None:
        """Empty supply_fn leaves pending unchanged and counter unchanged."""
        from phase_utils import _fill_pending_slots

        async def noop(i: int, x: int) -> int:
            return x

        pending: dict = {}
        counter = _fill_pending_slots(lambda: [], noop, pending, 3, 5)
        assert counter == 5
        assert not pending

    @pytest.mark.asyncio
    async def test_creates_tasks_for_available_items(self) -> None:
        """Tasks are created for each item returned by supply_fn (supply exhausts)."""
        from phase_utils import _fill_pending_slots

        async def noop(i: int, x: int) -> int:
            return x

        items = [10, 20]

        def supply_once() -> list[int]:
            result, items[:] = list(items), []
            return result

        pending: dict = {}
        counter = _fill_pending_slots(supply_once, noop, pending, 5, 0)
        assert len(pending) == 2
        assert counter == 2
        for t in pending:
            t.cancel()

    @pytest.mark.asyncio
    async def test_respects_max_concurrent_limit(self) -> None:
        """Does not create more tasks than max_concurrent allows."""
        from phase_utils import _fill_pending_slots

        async def noop(i: int, x: int) -> int:
            return x

        pending: dict = {}
        counter = _fill_pending_slots(lambda: [1, 2, 3, 4, 5], noop, pending, 2, 0)
        assert len(pending) == 2
        assert counter == 2
        for t in pending:
            t.cancel()

    @pytest.mark.asyncio
    async def test_increments_worker_id_counter(self) -> None:
        """Counter increments by the number of tasks created."""
        from phase_utils import _fill_pending_slots

        async def noop(i: int, x: int) -> int:
            return i

        items = [1, 2, 3]

        def supply_once() -> list[int]:
            result, items[:] = list(items), []
            return result

        pending: dict = {}
        counter = _fill_pending_slots(supply_once, noop, pending, 5, 10)
        assert counter == 13  # started at 10, created 3 tasks
        for t in pending:
            t.cancel()

    @pytest.mark.asyncio
    async def test_does_not_exceed_available_slots_in_partial_pending(self) -> None:
        """If pending already has tasks, only fills remaining slots."""
        from phase_utils import _fill_pending_slots

        async def noop(i: int, x: int) -> int:
            return x

        existing_task = asyncio.create_task(noop(0, 0))
        pending: dict = {existing_task: 0}
        counter = _fill_pending_slots(lambda: [10, 20, 30], noop, pending, 2, 1)
        assert len(pending) == 2  # 1 existing + 1 new
        assert counter == 2
        for t in list(pending):
            t.cancel()


# ---------------------------------------------------------------------------
# _cancel_remaining (private helper)
# ---------------------------------------------------------------------------


class TestCancelRemaining:
    @pytest.mark.asyncio
    async def test_cancels_all_pending_tasks(self) -> None:
        """All tasks in the pending dict are cancelled and awaited."""
        from phase_utils import _cancel_remaining

        async def slow() -> int:
            await asyncio.sleep(100)
            return 1

        tasks: dict[asyncio.Task[int], int] = {
            asyncio.create_task(slow()): 0,
            asyncio.create_task(slow()): 1,
        }
        await _cancel_remaining(tasks)

        for t in tasks:
            assert t.done()

    @pytest.mark.asyncio
    async def test_noop_on_empty_pending(self) -> None:
        """Empty pending dict should not raise."""
        from phase_utils import _cancel_remaining

        await _cancel_remaining({})  # must not raise

    @pytest.mark.asyncio
    async def test_safe_on_already_done_tasks(self) -> None:
        """Calling on already-done tasks does not raise."""
        from phase_utils import _cancel_remaining

        async def quick() -> int:
            return 42

        task = asyncio.create_task(quick())
        await asyncio.sleep(0)  # let it complete
        assert task.done()

        await _cancel_remaining({task: 0})  # must not raise


# ---------------------------------------------------------------------------
# _process_done_tasks (private helper)
# ---------------------------------------------------------------------------


class TestProcessDoneTasks:
    @pytest.mark.asyncio
    async def test_appends_successful_result(self) -> None:
        """Result from a completed task is appended to results list."""
        from phase_utils import _process_done_tasks

        async def ok() -> int:
            return 42

        task: asyncio.Task[int] = asyncio.create_task(ok())
        await asyncio.sleep(0)  # let it complete

        pending: dict[asyncio.Task[int], int] = {task: 0}
        results: list[int] = []
        await _process_done_tasks({task}, pending, results)

        assert results == [42]

    @pytest.mark.asyncio
    async def test_removes_done_task_from_pending(self) -> None:
        """Completed tasks are removed from the pending dict."""
        from phase_utils import _process_done_tasks

        async def ok() -> int:
            return 1

        task: asyncio.Task[int] = asyncio.create_task(ok())
        await asyncio.sleep(0)

        pending: dict[asyncio.Task[int], int] = {task: 0}
        results: list[int] = []
        await _process_done_tasks({task}, pending, results)

        assert task not in pending

    @pytest.mark.asyncio
    async def test_nonfatal_exception_is_logged_not_raised(self) -> None:
        """Non-fatal exceptions are logged; results list stays empty; no raise."""
        from phase_utils import _process_done_tasks

        async def bad() -> int:
            raise ValueError("oops")

        task: asyncio.Task[int] = asyncio.create_task(bad())
        await asyncio.sleep(0)

        pending: dict[asyncio.Task[int], int] = {task: 0}
        results: list[int] = []

        with patch("phase_utils.logger") as mock_logger:
            await _process_done_tasks({task}, pending, results)

        assert results == []
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_fatal_auth_error_cancels_pending_and_raises(self) -> None:
        """AuthenticationError cancels remaining pending tasks and re-raises."""
        from phase_utils import _process_done_tasks
        from subprocess_util import AuthenticationError

        async def auth_fail() -> int:
            raise AuthenticationError("bad token")

        async def slow() -> int:
            await asyncio.sleep(100)
            return 1

        failed: asyncio.Task[int] = asyncio.create_task(auth_fail())
        await asyncio.sleep(0)  # let it fail

        remaining: asyncio.Task[int] = asyncio.create_task(slow())
        pending: dict[asyncio.Task[int], int] = {failed: 0, remaining: 1}
        results: list[int] = []

        with pytest.raises(AuthenticationError):
            await _process_done_tasks({failed}, pending, results)

        assert remaining.done()

    @pytest.mark.asyncio
    async def test_fatal_credit_error_cancels_pending_and_raises(self) -> None:
        """CreditExhaustedError cancels remaining pending tasks and re-raises."""
        from phase_utils import _process_done_tasks
        from subprocess_util import CreditExhaustedError

        async def credit_fail() -> int:
            raise CreditExhaustedError("no credits")

        async def slow() -> int:
            await asyncio.sleep(100)
            return 1

        failed: asyncio.Task[int] = asyncio.create_task(credit_fail())
        await asyncio.sleep(0)

        remaining: asyncio.Task[int] = asyncio.create_task(slow())
        pending: dict[asyncio.Task[int], int] = {failed: 0, remaining: 1}
        results: list[int] = []

        with pytest.raises(CreditExhaustedError):
            await _process_done_tasks({failed}, pending, results)

        assert remaining.done()

    @pytest.mark.asyncio
    async def test_memory_error_cancels_pending_and_raises(self) -> None:
        """MemoryError cancels remaining pending tasks and re-raises."""
        from phase_utils import _process_done_tasks

        async def mem_fail() -> int:
            raise MemoryError("OOM")

        async def slow() -> int:
            await asyncio.sleep(100)
            return 1

        failed: asyncio.Task[int] = asyncio.create_task(mem_fail())
        await asyncio.sleep(0)

        remaining: asyncio.Task[int] = asyncio.create_task(slow())
        pending: dict[asyncio.Task[int], int] = {failed: 0, remaining: 1}
        results: list[int] = []

        with pytest.raises(MemoryError):
            await _process_done_tasks({failed}, pending, results)

        assert remaining.done()


# ---------------------------------------------------------------------------
# _collect_batch_results (private helper)
# ---------------------------------------------------------------------------


class TestCollectBatchResults:
    @pytest.mark.asyncio
    async def test_collects_all_results(self) -> None:
        """All task results are returned."""
        from phase_utils import _collect_batch_results

        async def worker() -> int:
            return 42

        tasks = [asyncio.create_task(worker()) for _ in range(3)]
        stop = asyncio.Event()
        results = await _collect_batch_results(tasks, stop)

        assert sorted(results) == [42, 42, 42]

    @pytest.mark.asyncio
    async def test_stops_when_stop_event_fires(self) -> None:
        """Collection halts and remaining tasks are cancelled when stop fires."""
        from phase_utils import _collect_batch_results

        stop = asyncio.Event()

        async def fast() -> int:
            stop.set()
            return 1

        async def slow() -> int:
            await asyncio.sleep(100)
            return 2

        tasks = [asyncio.create_task(fast()), asyncio.create_task(slow())]
        results = await _collect_batch_results(tasks, stop)

        assert 1 in results
        assert len(results) < 2

    @pytest.mark.asyncio
    async def test_propagates_worker_exception(self) -> None:
        """Exceptions from tasks propagate out of _collect_batch_results."""
        from phase_utils import _collect_batch_results

        async def fail() -> int:
            raise ValueError("task failed")

        tasks = [asyncio.create_task(fail())]
        stop = asyncio.Event()

        with pytest.raises(ValueError, match="task failed"):
            await _collect_batch_results(tasks, stop)

    @pytest.mark.asyncio
    async def test_empty_task_list_returns_empty(self) -> None:
        """Empty task list returns empty results list."""
        from phase_utils import _collect_batch_results

        stop = asyncio.Event()
        results = await _collect_batch_results([], stop)

        assert results == []
