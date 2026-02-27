"""Tests for the IssueStore centralized data layer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from events import EventBus, EventType
from issue_store import (
    STAGE_FIND,
    STAGE_HITL,
    STAGE_PLAN,
    STAGE_READY,
    STAGE_REVIEW,
    IssueStore,
)
from tests.conftest import IssueFactory, TaskFactory
from tests.helpers import ConfigFactory


def _make_store(
    *,
    fetcher: AsyncMock | None = None,
    event_bus: EventBus | None = None,
) -> IssueStore:
    """Create an IssueStore with standard test config and mocked dependencies."""
    config = ConfigFactory.create()
    if fetcher is None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(return_value=[])
    bus = event_bus or EventBus()
    return IssueStore(config, fetcher, bus)


# ── Routing ──────────────────────────────────────────────────────────


class TestRouting:
    """Issues are routed to the correct queue based on their labels."""

    def test_routes_find_labeled_issues_to_find_queue(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=1, tags=["hydraflow-find"])
        store._route_issues([issue])

        assert store._queue_members[STAGE_FIND] == {1}
        assert len(store._queues[STAGE_FIND]) == 1

    def test_routes_plan_labeled_issues_to_plan_queue(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=2, tags=["hydraflow-plan"])
        store._route_issues([issue])

        assert store._queue_members[STAGE_PLAN] == {2}
        assert len(store._queues[STAGE_PLAN]) == 1

    def test_routes_ready_labeled_issues_to_ready_queue(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(
            id=3, tags=["test-label"]
        )  # ConfigFactory uses "test-label" as ready_label
        store._route_issues([issue])

        assert store._queue_members[STAGE_READY] == {3}

    def test_routes_review_labeled_issues_to_review_queue(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=4, tags=["hydraflow-review"])
        store._route_issues([issue])

        assert store._queue_members[STAGE_REVIEW] == {4}

    def test_routes_hitl_labeled_issues_to_hitl_set(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=5, tags=["hydraflow-hitl"])
        store._route_issues([issue])

        assert 5 in store._hitl_numbers
        # HITL issues should NOT be in regular queues
        for stage in store._queues:
            assert 5 not in store._queue_members[stage]

    def test_unknown_label_issues_ignored(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=6, tags=["some-other-label"])
        store._route_issues([issue])

        for stage in store._queues:
            assert len(store._queues[stage]) == 0
        assert 6 not in store._hitl_numbers

    def test_multi_label_issue_routed_to_most_advanced_stage(self) -> None:
        store = _make_store()
        # Issue has both find and review labels — should go to review (higher priority)
        issue = TaskFactory.create(id=7, tags=["hydraflow-find", "hydraflow-review"])
        store._route_issues([issue])

        assert store._queue_members[STAGE_REVIEW] == {7}
        assert 7 not in store._queue_members[STAGE_FIND]

    def test_multiple_issues_routed_to_different_queues(self) -> None:
        store = _make_store()
        issues = [
            TaskFactory.create(id=10, tags=["hydraflow-find"]),
            TaskFactory.create(id=11, tags=["hydraflow-plan"]),
            TaskFactory.create(id=12, tags=["test-label"]),  # ready
            TaskFactory.create(id=13, tags=["hydraflow-review"]),
        ]
        store._route_issues(issues)

        assert store._queue_members[STAGE_FIND] == {10}
        assert store._queue_members[STAGE_PLAN] == {11}
        assert store._queue_members[STAGE_READY] == {12}
        assert store._queue_members[STAGE_REVIEW] == {13}

    def test_does_not_duplicate_existing_queue_entries(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=20, tags=["hydraflow-find"])
        store._route_issues([issue])
        store._route_issues([issue])  # Route same issue again

        assert len(store._queues[STAGE_FIND]) == 1

    def test_active_issues_not_requeued(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=21, tags=["hydraflow-find"])
        store.mark_active(21, STAGE_FIND)
        store._route_issues([issue])

        assert 21 not in store._queue_members[STAGE_FIND]
        assert len(store._queues[STAGE_FIND]) == 0

    def test_label_change_moves_issue_between_queues(self) -> None:
        store = _make_store()
        # First: issue in plan queue
        issue_plan = TaskFactory.create(id=30, tags=["hydraflow-plan"])
        store._route_issues([issue_plan])
        assert store._queue_members[STAGE_PLAN] == {30}

        # Second: same issue now has ready label
        issue_ready = TaskFactory.create(id=30, tags=["test-label"])
        store._route_issues([issue_ready])

        assert 30 not in store._queue_members[STAGE_PLAN]
        assert store._queue_members[STAGE_READY] == {30}

    def test_closed_issues_removed_from_queues(self) -> None:
        store = _make_store()
        issue1 = TaskFactory.create(id=40, tags=["hydraflow-find"])
        issue2 = TaskFactory.create(id=41, tags=["hydraflow-find"])
        store._route_issues([issue1, issue2])
        assert len(store._queues[STAGE_FIND]) == 2

        # On next refresh, only issue 41 comes back (40 was closed)
        store._route_issues([issue2])
        assert store._queue_members[STAGE_FIND] == {41}
        assert len(store._queues[STAGE_FIND]) == 1

    def test_hitl_active_label_routes_to_hitl(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=50, tags=["hydraflow-hitl-active"])
        store._route_issues([issue])

        assert 50 in store._hitl_numbers

    def test_enqueue_transition_moves_issue_to_next_stage_immediately(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=60, tags=["hydraflow-find"])
        store._route_issues([issue])
        assert 60 in store._queue_members[STAGE_FIND]

        store.enqueue_transition(issue, "plan")

        assert 60 not in store._queue_members[STAGE_FIND]
        assert 60 in store._queue_members[STAGE_PLAN]
        assert 60 not in store._hitl_numbers

    def test_enqueue_transition_routes_to_hitl_set(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=61, tags=["hydraflow-plan"])
        store._route_issues([issue])
        assert 61 in store._queue_members[STAGE_PLAN]

        store.enqueue_transition(issue, "hitl")

        assert 61 not in store._queue_members[STAGE_PLAN]
        assert 61 in store._hitl_numbers

    def test_enqueue_transition_does_not_duplicate_existing_target_entry(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=62, tags=["hydraflow-plan"])
        store._route_issues([issue])
        store.enqueue_transition(issue, "plan")
        store.enqueue_transition(issue, "plan")

        assert len([t for t in store._queues[STAGE_PLAN] if t.id == 62]) == 1


# ── Queue Accessors ──────────────────────────────────────────────────


class TestQueueAccessors:
    """Queue accessor methods return correct issues."""

    def test_get_triageable_returns_find_queue_issues(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=1, tags=["hydraflow-find"])])

        result = store.get_triageable(10)
        assert len(result) == 1
        assert result[0].id == 1

    def test_get_plannable_returns_plan_queue_issues(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=2, tags=["hydraflow-plan"])])

        result = store.get_plannable(10)
        assert len(result) == 1
        assert result[0].id == 2

    def test_get_implementable_returns_ready_queue_issues(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=3, tags=["test-label"])])

        result = store.get_implementable(10)
        assert len(result) == 1
        assert result[0].id == 3

    def test_get_reviewable_returns_review_queue_issues(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=4, tags=["hydraflow-review"])])

        result = store.get_reviewable(10)
        assert len(result) == 1
        assert result[0].id == 4

    def test_get_implementable_excludes_active_issues(self) -> None:
        store = _make_store()
        store._route_issues(
            [
                TaskFactory.create(id=10, tags=["test-label"]),
                TaskFactory.create(id=11, tags=["test-label"]),
            ]
        )
        store.mark_active(10, STAGE_READY)

        result = store.get_implementable(10)
        assert len(result) == 1
        assert result[0].id == 11

    def test_get_implementable_respects_limit(self) -> None:
        store = _make_store()
        store._route_issues(
            [TaskFactory.create(id=i, tags=["test-label"]) for i in range(1, 6)]
        )

        result = store.get_implementable(2)
        assert len(result) == 2

    def test_get_plannable_returns_empty_when_queue_empty(self) -> None:
        store = _make_store()
        result = store.get_plannable(10)
        assert result == []

    def test_take_removes_issues_from_queue(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=1, tags=["hydraflow-find"])])
        result = store.get_triageable(10)
        assert len(result) == 1

        # Second take should return empty
        result2 = store.get_triageable(10)
        assert result2 == []

    def test_get_hitl_issues_returns_hitl_set(self) -> None:
        store = _make_store()
        store._route_issues(
            [
                TaskFactory.create(id=50, tags=["hydraflow-hitl"]),
                TaskFactory.create(id=51, tags=["hydraflow-hitl"]),
            ]
        )

        hitl = store.get_hitl_issues()
        assert hitl == {50, 51}

    def test_fifo_ordering_preserved(self) -> None:
        store = _make_store()
        store._route_issues(
            [
                TaskFactory.create(id=1, tags=["hydraflow-find"]),
                TaskFactory.create(id=2, tags=["hydraflow-find"]),
                TaskFactory.create(id=3, tags=["hydraflow-find"]),
            ]
        )

        result = store.get_triageable(10)
        assert [i.id for i in result] == [1, 2, 3]


# ── Active Tracking ──────────────────────────────────────────────────


class TestActiveTracking:
    """Active issue tracking works correctly."""

    def test_mark_active_tracks_issue(self) -> None:
        store = _make_store()
        store.mark_active(42, STAGE_READY)

        assert store.is_active(42)
        assert store._active[42] == STAGE_READY

    def test_mark_complete_clears_active(self) -> None:
        store = _make_store()
        store.mark_active(42, STAGE_READY)
        store.mark_complete(42)

        assert not store.is_active(42)

    def test_mark_complete_increments_processed_count(self) -> None:
        store = _make_store()
        store.mark_active(42, STAGE_READY)
        store.mark_complete(42)

        assert store._processed_count[STAGE_READY] == 1

    def test_mark_complete_unknown_issue_is_safe(self) -> None:
        store = _make_store()
        store.mark_complete(999)  # Should not raise

    def test_is_active_returns_false_for_unknown_issue(self) -> None:
        store = _make_store()
        assert not store.is_active(999)

    def test_get_active_issues_returns_copy(self) -> None:
        store = _make_store()
        store.mark_active(1, STAGE_FIND)
        store.mark_active(2, STAGE_PLAN)

        active = store.get_active_issues()
        assert active == {1: STAGE_FIND, 2: STAGE_PLAN}
        # Modifying the copy doesn't affect the store
        active[3] = STAGE_READY
        assert 3 not in store._active

    def test_clear_active_clears_all(self) -> None:
        store = _make_store()
        store.mark_active(1, STAGE_FIND)
        store.mark_active(2, STAGE_PLAN)
        store.clear_active()

        assert store._active == {}


# ── Refresh ──────────────────────────────────────────────────────────


class TestRefresh:
    """Refresh fetches issues and routes them into queues."""

    @pytest.mark.asyncio
    async def test_refresh_populates_queues_from_github(self) -> None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(
            return_value=[
                TaskFactory.create(id=1, tags=["hydraflow-find"]),
                TaskFactory.create(id=2, tags=["hydraflow-plan"]),
            ]
        )
        store = _make_store(fetcher=fetcher)

        await store.refresh()

        assert store._queue_members[STAGE_FIND] == {1}
        assert store._queue_members[STAGE_PLAN] == {2}

    @pytest.mark.asyncio
    async def test_refresh_handles_fetcher_error_gracefully(self) -> None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(side_effect=RuntimeError("gh CLI failed"))
        store = _make_store(fetcher=fetcher)

        await store.refresh()  # Should not raise

        # Queues remain empty
        for stage in store._queues:
            assert len(store._queues[stage]) == 0

    @pytest.mark.asyncio
    async def test_refresh_detects_label_change_and_moves_issue(self) -> None:
        fetcher = AsyncMock()
        store = _make_store(fetcher=fetcher)

        # First poll: issue in plan queue
        fetcher.fetch_all = AsyncMock(
            return_value=[TaskFactory.create(id=10, tags=["hydraflow-plan"])]
        )
        await store.refresh()
        assert store._queue_members[STAGE_PLAN] == {10}

        # Second poll: issue now in ready queue
        fetcher.fetch_all = AsyncMock(
            return_value=[TaskFactory.create(id=10, tags=["test-label"])]
        )
        await store.refresh()
        assert 10 not in store._queue_members[STAGE_PLAN]
        assert store._queue_members[STAGE_READY] == {10}

    @pytest.mark.asyncio
    async def test_refresh_does_not_duplicate_existing_entries(self) -> None:
        fetcher = AsyncMock()
        store = _make_store(fetcher=fetcher)

        issues = [TaskFactory.create(id=1, tags=["hydraflow-find"])]
        fetcher.fetch_all = AsyncMock(return_value=issues)

        await store.refresh()
        await store.refresh()

        assert len(store._queues[STAGE_FIND]) == 1

    @pytest.mark.asyncio
    async def test_refresh_removes_closed_issues_from_queues(self) -> None:
        fetcher = AsyncMock()
        store = _make_store(fetcher=fetcher)

        # First poll: two issues
        fetcher.fetch_all = AsyncMock(
            return_value=[
                TaskFactory.create(id=1, tags=["hydraflow-find"]),
                TaskFactory.create(id=2, tags=["hydraflow-find"]),
            ]
        )
        await store.refresh()
        assert len(store._queues[STAGE_FIND]) == 2

        # Second poll: only issue 2 remains (issue 1 was closed)
        fetcher.fetch_all = AsyncMock(
            return_value=[TaskFactory.create(id=2, tags=["hydraflow-find"])]
        )
        await store.refresh()
        assert store._queue_members[STAGE_FIND] == {2}
        assert len(store._queues[STAGE_FIND]) == 1

    @pytest.mark.asyncio
    async def test_refresh_preserves_active_issues(self) -> None:
        fetcher = AsyncMock()
        store = _make_store(fetcher=fetcher)

        fetcher.fetch_all = AsyncMock(
            return_value=[TaskFactory.create(id=1, tags=["hydraflow-find"])]
        )
        await store.refresh()
        store.get_triageable(1)  # Take from queue
        store.mark_active(1, STAGE_FIND)

        # Refresh again — issue 1 should NOT be re-queued
        await store.refresh()
        assert len(store._queues[STAGE_FIND]) == 0
        assert store.is_active(1)

    @pytest.mark.asyncio
    async def test_refresh_updates_last_poll_timestamp(self) -> None:
        store = _make_store()
        assert store._last_poll_ts is None

        await store.refresh()
        assert store._last_poll_ts is not None

    @pytest.mark.asyncio
    async def test_refresh_deduplicates_incoming_duplicate_issue_ids(self) -> None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(
            return_value=[
                TaskFactory.create(id=70, tags=["hydraflow-find"]),
                TaskFactory.create(id=70, tags=["hydraflow-find"]),
            ]
        )
        store = _make_store(fetcher=fetcher)

        await store.refresh()

        assert len(store._queues[STAGE_FIND]) == 1
        stats = store.get_queue_stats()
        assert stats.dedup_stats["incoming_tasks"] == 1


# ── Stats ────────────────────────────────────────────────────────────


class TestStats:
    """Queue stats computation is correct."""

    def test_get_queue_stats_returns_correct_depths(self) -> None:
        store = _make_store()
        store._route_issues(
            [
                TaskFactory.create(id=1, tags=["hydraflow-find"]),
                TaskFactory.create(id=2, tags=["hydraflow-find"]),
                TaskFactory.create(id=3, tags=["hydraflow-plan"]),
            ]
        )

        stats = store.get_queue_stats()
        assert stats.queue_depth[STAGE_FIND] == 2
        assert stats.queue_depth[STAGE_PLAN] == 1
        assert stats.queue_depth[STAGE_READY] == 0
        assert stats.queue_depth[STAGE_REVIEW] == 0

    def test_get_queue_stats_returns_active_counts(self) -> None:
        store = _make_store()
        store.mark_active(1, STAGE_READY)
        store.mark_active(2, STAGE_READY)
        store.mark_active(3, STAGE_REVIEW)

        stats = store.get_queue_stats()
        assert stats.active_count[STAGE_READY] == 2
        assert stats.active_count[STAGE_REVIEW] == 1
        assert stats.active_count[STAGE_FIND] == 0

    def test_stats_increment_on_completion(self) -> None:
        store = _make_store()
        store.mark_active(1, STAGE_READY)
        store.mark_complete(1)
        store.mark_active(2, STAGE_READY)
        store.mark_complete(2)

        stats = store.get_queue_stats()
        assert stats.total_processed[STAGE_READY] == 2

    def test_stats_last_poll_timestamp_is_none_initially(self) -> None:
        store = _make_store()
        stats = store.get_queue_stats()
        assert stats.last_poll_timestamp is None

    @pytest.mark.asyncio
    async def test_stats_last_poll_timestamp_updated_after_refresh(self) -> None:
        store = _make_store()
        await store.refresh()
        stats = store.get_queue_stats()
        assert stats.last_poll_timestamp is not None

    def test_hitl_depth_in_stats(self) -> None:
        store = _make_store()
        store._route_issues(
            [
                TaskFactory.create(id=50, tags=["hydraflow-hitl"]),
                TaskFactory.create(id=51, tags=["hydraflow-hitl"]),
            ]
        )
        stats = store.get_queue_stats()
        assert stats.queue_depth[STAGE_HITL] == 2

    def test_get_queue_stats_deduplicates_queue_depth_from_ids(self) -> None:
        store = _make_store()
        duplicate = TaskFactory.create(id=80, tags=["hydraflow-find"])
        store._queues[STAGE_FIND].append(duplicate)
        store._queues[STAGE_FIND].append(duplicate)
        store._queue_members[STAGE_FIND].add(80)

        stats = store.get_queue_stats()
        assert stats.queue_depth[STAGE_FIND] == 1


# ── Event Publishing ─────────────────────────────────────────────────


class TestEventPublishing:
    """QUEUE_UPDATE events are published after refresh."""

    @pytest.mark.asyncio
    async def test_queue_update_event_published_after_refresh(self, event_bus) -> None:
        store = _make_store(event_bus=event_bus)

        await store.refresh()

        events = event_bus.get_history()
        queue_events = [e for e in events if e.type == EventType.QUEUE_UPDATE]
        assert len(queue_events) == 1

    @pytest.mark.asyncio
    async def test_queue_update_event_contains_depth_data(self, event_bus) -> None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(
            return_value=[TaskFactory.create(id=1, tags=["hydraflow-find"])]
        )
        store = _make_store(fetcher=fetcher, event_bus=event_bus)

        await store.refresh()

        events = event_bus.get_history()
        queue_event = [e for e in events if e.type == EventType.QUEUE_UPDATE][0]
        assert queue_event.data["queue_depth"]["find"] == 1

    @pytest.mark.asyncio
    async def test_enqueue_transition_publishes_queue_update_in_realtime(
        self, event_bus
    ) -> None:
        store = _make_store(event_bus=event_bus)
        issue = TaskFactory.create(id=101, tags=["hydraflow-find"])
        store._route_issues([issue])

        before = len(
            [e for e in event_bus.get_history() if e.type == EventType.QUEUE_UPDATE]
        )
        store.enqueue_transition(issue, "plan")
        await asyncio.sleep(0)

        after_events = [
            e for e in event_bus.get_history() if e.type == EventType.QUEUE_UPDATE
        ]
        assert len(after_events) >= before + 1
        assert after_events[-1].data["queue_depth"]["plan"] == 1


# ── Lifecycle ────────────────────────────────────────────────────────


class TestLifecycle:
    """Start and stop of the background polling loop."""

    @pytest.mark.asyncio
    async def test_start_runs_initial_refresh(self) -> None:
        fetcher = AsyncMock()
        fetcher.fetch_all = AsyncMock(
            return_value=[TaskFactory.create(id=1, tags=["hydraflow-find"])]
        )
        store = _make_store(fetcher=fetcher)
        stop = asyncio.Event()
        stop.set()  # Stop immediately after initial refresh

        await store.start(stop)

        assert store._queue_members[STAGE_FIND] == {1}
        fetcher.fetch_all.assert_called()

    @pytest.mark.asyncio
    async def test_start_stops_when_event_set(self) -> None:
        store = _make_store()
        stop = asyncio.Event()

        # Set stop after a short delay
        async def _set_stop() -> None:
            await asyncio.sleep(0)
            stop.set()

        task = asyncio.create_task(_set_stop())
        # Use a very short poll interval to make the test fast
        store._config = ConfigFactory.create(data_poll_interval=10)
        await asyncio.wait_for(store.start(stop), timeout=2.0)
        await task


# ── Fetch All HydraFlow Issues ───────────────────────────────────────────


class TestFetchAllHydraFlowIssues:
    """Tests for IssueFetcher.fetch_all_hydraflow_issues."""

    @pytest.mark.asyncio
    async def test_fetch_all_hydraflow_issues_calls_fetch_by_labels(self) -> None:
        from issue_fetcher import IssueFetcher

        config = ConfigFactory.create()
        fetcher = IssueFetcher(config)

        with patch.object(
            fetcher,
            "fetch_issues_by_labels",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_fetch:
            result = await fetcher.fetch_all_hydraflow_issues()

            mock_fetch.assert_called_once()
            call_args = mock_fetch.call_args
            labels = call_args[0][0]
            # Should include all pipeline labels
            assert "hydraflow-find" in labels
            assert "hydraflow-plan" in labels
            assert "test-label" in labels  # ready_label from ConfigFactory
            assert "hydraflow-review" in labels
            assert "hydraflow-hitl" in labels
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_all_hydraflow_issues_deduplicates(
        self,
    ) -> None:
        from issue_fetcher import IssueFetcher

        config = ConfigFactory.create()
        fetcher = IssueFetcher(config)

        issue = IssueFactory.create(number=42, labels=["hydraflow-find"])

        with patch.object(
            fetcher,
            "fetch_issues_by_labels",
            new_callable=AsyncMock,
            return_value=[issue],
        ):
            result = await fetcher.fetch_all_hydraflow_issues()
            assert len(result) == 1
            assert result[0].number == 42


# ── Pipeline Snapshot ───────────────────────────────────────────────


class TestPipelineSnapshot:
    """Tests for get_pipeline_snapshot()."""

    def test_empty_store_returns_empty_stages(self) -> None:
        store = _make_store()
        snapshot = store.get_pipeline_snapshot()

        for stage in [STAGE_FIND, STAGE_PLAN, STAGE_READY, STAGE_REVIEW]:
            assert snapshot[stage] == []
        assert snapshot[STAGE_HITL] == []

    def test_queued_issues_appear_in_snapshot(self) -> None:
        store = _make_store()
        store._route_issues(
            [
                TaskFactory.create(id=1, tags=["hydraflow-find"]),
                TaskFactory.create(id=2, tags=["hydraflow-plan"]),
            ]
        )

        snapshot = store.get_pipeline_snapshot()
        assert len(snapshot[STAGE_FIND]) == 1
        assert snapshot[STAGE_FIND][0]["issue_number"] == 1
        assert snapshot[STAGE_FIND][0]["status"] == "queued"
        assert len(snapshot[STAGE_PLAN]) == 1
        assert snapshot[STAGE_PLAN][0]["issue_number"] == 2

    def test_active_issues_appear_with_active_status(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=10, tags=["hydraflow-find"])])
        store.get_triageable(1)  # Remove from queue
        store.mark_active(10, STAGE_FIND)

        snapshot = store.get_pipeline_snapshot()
        find_issues = snapshot[STAGE_FIND]
        assert len(find_issues) == 1
        assert find_issues[0]["issue_number"] == 10
        assert find_issues[0]["status"] == "active"

    def test_hitl_issues_appear_in_snapshot(self) -> None:
        store = _make_store()
        store._route_issues([TaskFactory.create(id=50, tags=["hydraflow-hitl"])])

        snapshot = store.get_pipeline_snapshot()
        assert len(snapshot[STAGE_HITL]) == 1
        assert snapshot[STAGE_HITL][0]["issue_number"] == 50
        assert snapshot[STAGE_HITL][0]["status"] == "hitl"

    def test_cached_details_used_for_active_issues(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(
            id=42,
            title="Fix the frobnicator",
            tags=["test-label"],
            source_url="https://github.com/org/repo/issues/42",
        )
        store._route_issues([issue])
        store.get_implementable(1)
        store.mark_active(42, STAGE_READY)

        snapshot = store.get_pipeline_snapshot()
        ready_issues = snapshot[STAGE_READY]
        assert len(ready_issues) == 1
        assert ready_issues[0]["title"] == "Fix the frobnicator"
        assert ready_issues[0]["url"] == "https://github.com/org/repo/issues/42"

    def test_issue_cache_populated_on_route(self) -> None:
        store = _make_store()
        issue = TaskFactory.create(id=99, title="Cache test", tags=["hydraflow-find"])
        store._route_issues([issue])

        assert 99 in store._issue_cache
        assert store._issue_cache[99].title == "Cache test"

    def test_active_issue_without_cache_uses_fallback(self) -> None:
        store = _make_store()
        # Mark active without routing (no cache entry)
        store.mark_active(999, STAGE_PLAN)

        snapshot = store.get_pipeline_snapshot()
        plan_issues = snapshot[STAGE_PLAN]
        assert len(plan_issues) == 1
        assert plan_issues[0]["title"] == "Issue #999"
        assert plan_issues[0]["url"] == ""
