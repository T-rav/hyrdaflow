"""Tests for dx/hydraflow/events.py - EventType, HydraFlowEvent, and EventBus."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from events import EventBus, EventLog, EventType, HydraFlowEvent, _log_persist_failure
from tests.conftest import EventFactory

# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------

_EVENT_STRING_CASES: list[tuple[EventType, str]] = [
    (EventType.PHASE_CHANGE, "phase_change"),
    (EventType.WORKER_UPDATE, "worker_update"),
    (EventType.TRANSCRIPT_LINE, "transcript_line"),
    (EventType.PR_CREATED, "pr_created"),
    (EventType.REVIEW_UPDATE, "review_update"),
    (EventType.TRIAGE_UPDATE, "triage_update"),
    (EventType.PLANNER_UPDATE, "planner_update"),
    (EventType.MERGE_UPDATE, "merge_update"),
    (EventType.CI_CHECK, "ci_check"),
    (EventType.HITL_ESCALATION, "hitl_escalation"),
    (EventType.ISSUE_CREATED, "issue_created"),
    (EventType.HITL_UPDATE, "hitl_update"),
    (EventType.ORCHESTRATOR_STATUS, "orchestrator_status"),
    (EventType.ERROR, "error"),
    (EventType.MEMORY_SYNC, "memory_sync"),
    (EventType.METRICS_UPDATE, "metrics_update"),
    (EventType.BACKGROUND_WORKER_STATUS, "background_worker_status"),
    (EventType.QUEUE_UPDATE, "queue_update"),
    (EventType.SYSTEM_ALERT, "system_alert"),
    (EventType.VERIFICATION_JUDGE, "verification_judge"),
    (EventType.TRANSCRIPT_SUMMARY, "transcript_summary"),
    (EventType.SESSION_START, "session_start"),
    (EventType.SESSION_END, "session_end"),
    (EventType.EPIC_UPDATE, "epic_update"),
    (EventType.EPIC_PROGRESS, "epic_progress"),
    (EventType.EPIC_READY, "epic_ready"),
    (EventType.EPIC_RELEASING, "epic_releasing"),
    (EventType.EPIC_RELEASED, "epic_released"),
    (EventType.PIPELINE_STATS, "pipeline_stats"),
    (EventType.VISUAL_GATE, "visual_gate"),
    (EventType.BASELINE_UPDATE, "baseline_update"),
]


class TestEventTypeEnum:
    def test_all_expected_values_exist(self) -> None:
        expected = {
            "PHASE_CHANGE",
            "WORKER_UPDATE",
            "TRANSCRIPT_LINE",
            "PR_CREATED",
            "REVIEW_UPDATE",
            "TRIAGE_UPDATE",
            "PLANNER_UPDATE",
            "MERGE_UPDATE",
            "CI_CHECK",
            "HITL_ESCALATION",
            "ISSUE_CREATED",
            "HITL_UPDATE",
            "ORCHESTRATOR_STATUS",
            "ERROR",
            "MEMORY_SYNC",
            "METRICS_UPDATE",
            "BACKGROUND_WORKER_STATUS",
            "QUEUE_UPDATE",
            "SYSTEM_ALERT",
            "VERIFICATION_JUDGE",
            "TRANSCRIPT_SUMMARY",
            "SESSION_START",
            "SESSION_END",
            "EPIC_UPDATE",
            "EPIC_PROGRESS",
            "EPIC_READY",
            "EPIC_RELEASING",
            "EPIC_RELEASED",
            "PIPELINE_STATS",
            "VISUAL_GATE",
            "BASELINE_UPDATE",
            "CRATE_ACTIVATED",
            "CRATE_COMPLETED",
        }
        actual = {member.name for member in EventType}
        assert expected == actual

    @pytest.mark.parametrize(
        ("member", "expected_value"),
        _EVENT_STRING_CASES,
        ids=[case[0].name for case in _EVENT_STRING_CASES],
    )
    def test_string_values(self, member: EventType, expected_value: str) -> None:
        assert member == expected_value

    def test_is_str_enum(self) -> None:
        """EventType values should be strings (subclass of str)."""
        for member in EventType:
            assert isinstance(member, str)

    def test_enum_comparison_with_string(self) -> None:
        assert EventType.ERROR == "error"
        assert EventType.ERROR == "error"


# ---------------------------------------------------------------------------
# HydraFlowEvent
# ---------------------------------------------------------------------------


class TestHydraFlowEvent:
    def test_creation_with_explicit_values(self) -> None:
        event = EventFactory.create(
            type=EventType.PHASE_CHANGE,
            timestamp="2024-01-01T00:00:00+00:00",
            data={"batch": 1},
        )
        assert event.type == EventType.PHASE_CHANGE
        assert event.timestamp == "2024-01-01T00:00:00+00:00"
        assert event.data == {"batch": 1}

    def test_auto_timestamp_generated_when_omitted(self) -> None:
        event = HydraFlowEvent(type=EventType.ERROR)
        assert event.timestamp is not None
        assert "T" in event.timestamp  # ISO 8601 contains 'T'

    def test_auto_timestamp_is_utc_iso_format(self) -> None:
        event = HydraFlowEvent(type=EventType.ERROR)
        # UTC ISO strings end with '+00:00' or 'Z'
        assert "+" in event.timestamp or event.timestamp.endswith("Z")

    def test_data_defaults_to_empty_dict(self) -> None:
        event = EventFactory.create(type=EventType.PHASE_CHANGE)
        assert event.data == {}

    def test_data_accepts_arbitrary_keys(self) -> None:
        payload = {"issue": 42, "phase": "review", "nested": {"key": "value"}}
        event = EventFactory.create(type=EventType.PHASE_CHANGE, data=payload)
        assert event.data["issue"] == 42
        assert event.data["nested"]["key"] == "value"

    def test_two_events_have_independent_data(self) -> None:
        e1 = EventFactory.create(type=EventType.WORKER_UPDATE, data={"id": 1})
        e2 = EventFactory.create(type=EventType.WORKER_UPDATE, data={"id": 2})
        assert e1.data["id"] == 1
        assert e2.data["id"] == 2


# ---------------------------------------------------------------------------
# HydraFlowEvent ID
# ---------------------------------------------------------------------------


class TestHydraFlowEventId:
    def test_event_id_auto_generated(self) -> None:
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE)
        assert isinstance(event.id, int)

    def test_event_ids_are_unique(self) -> None:
        events = [HydraFlowEvent(type=EventType.PHASE_CHANGE) for _ in range(10)]
        ids = [e.id for e in events]
        assert len(set(ids)) == 10

    def test_event_ids_are_monotonically_increasing(self) -> None:
        events = [HydraFlowEvent(type=EventType.PHASE_CHANGE) for _ in range(5)]
        for i in range(1, len(events)):
            assert events[i].id > events[i - 1].id

    def test_event_id_included_in_serialization(self) -> None:
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"batch": 1})
        dumped = event.model_dump()
        assert "id" in dumped
        assert isinstance(dumped["id"], int)

        json_str = event.model_dump_json()
        assert '"id"' in json_str

    def test_explicit_event_id_preserved(self) -> None:
        event = HydraFlowEvent(id=999, type=EventType.PHASE_CHANGE)
        assert event.id == 999


# ---------------------------------------------------------------------------
# EventBus - publish / subscribe
# ---------------------------------------------------------------------------


class TestEventBusPublishSubscribe:
    @pytest.mark.asyncio
    async def test_subscriber_receives_published_event(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()

        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"batch": 1})
        await bus.publish(event)

        received = queue.get_nowait()
        assert received is event

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive_event(self) -> None:
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()

        event = EventFactory.create(type=EventType.PR_CREATED, data={"pr": 42})
        await bus.publish(event)

        assert q1.get_nowait() is event
        assert q2.get_nowait() is event
        assert q3.get_nowait() is event

    @pytest.mark.asyncio
    async def test_publish_multiple_events_in_order(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()

        e1 = EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "start"})
        e2 = EventFactory.create(type=EventType.PHASE_CHANGE, data={"phase": "end"})
        await bus.publish(e1)
        await bus.publish(e2)

        assert queue.get_nowait() is e1
        assert queue.get_nowait() is e2

    @pytest.mark.asyncio
    async def test_subscribe_returns_asyncio_queue(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        assert isinstance(queue, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_no_subscribers_publish_does_not_raise(self) -> None:
        bus = EventBus()
        event = EventFactory.create(type=EventType.ORCHESTRATOR_STATUS)
        await bus.publish(event)  # should not raise

    @pytest.mark.asyncio
    async def test_set_session_id_auto_injects(self) -> None:
        bus = EventBus()
        bus.set_session_id("sess-42")
        event = HydraFlowEvent(type=EventType.WORKER_UPDATE, data={"issue": 1})
        await bus.publish(event)
        assert event.session_id == "sess-42"

    @pytest.mark.asyncio
    async def test_set_session_id_does_not_override_explicit(self) -> None:
        bus = EventBus()
        bus.set_session_id("sess-42")
        event = HydraFlowEvent(
            type=EventType.SESSION_START,
            session_id="explicit-id",
            data={},
        )
        await bus.publish(event)
        assert event.session_id == "explicit-id"

    @pytest.mark.asyncio
    async def test_set_session_id_none_disables_injection(self) -> None:
        bus = EventBus()
        bus.set_session_id("sess-42")
        bus.set_session_id(None)
        event = HydraFlowEvent(type=EventType.WORKER_UPDATE, data={"issue": 1})
        await bus.publish(event)
        assert event.session_id is None

    @pytest.mark.asyncio
    async def test_subscribe_with_custom_max_queue(self) -> None:
        bus = EventBus()
        queue = bus.subscribe(max_queue=10)
        assert queue.maxsize == 10


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


class TestEventBusUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribed_queue_receives_no_further_events(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        bus.unsubscribe(queue)

        await bus.publish(EventFactory.create(type=EventType.ERROR))

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_only_removes_target_queue(self) -> None:
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.unsubscribe(q1)

        event = EventFactory.create(type=EventType.MERGE_UPDATE)
        await bus.publish(event)

        assert q1.empty()
        assert q2.get_nowait() is event

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_queue_is_noop(self) -> None:
        bus = EventBus()
        orphan: asyncio.Queue[HydraFlowEvent] = asyncio.Queue()
        # Should not raise
        bus.unsubscribe(orphan)

    @pytest.mark.asyncio
    async def test_unsubscribe_same_queue_twice_is_noop(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        bus.unsubscribe(queue)
        bus.unsubscribe(queue)  # second call should not raise


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class TestEventBusHistory:
    @pytest.mark.asyncio
    async def test_get_history_returns_published_events(self) -> None:
        bus = EventBus()
        e1 = EventFactory.create(type=EventType.PHASE_CHANGE)
        e2 = EventFactory.create(type=EventType.ORCHESTRATOR_STATUS)
        await bus.publish(e1)
        await bus.publish(e2)

        history = bus.get_history()
        assert e1 in history
        assert e2 in history

    @pytest.mark.asyncio
    async def test_get_history_preserves_order(self) -> None:
        bus = EventBus()
        events = [
            EventFactory.create(type=EventType.WORKER_UPDATE, data={"n": i})
            for i in range(5)
        ]
        for event in events:
            await bus.publish(event)

        history = bus.get_history()
        assert history == events

    @pytest.mark.asyncio
    async def test_get_history_returns_copy(self) -> None:
        """Mutating the returned list must not affect internal history."""
        bus = EventBus()
        await bus.publish(EventFactory.create(type=EventType.PHASE_CHANGE))

        history = bus.get_history()
        history.clear()

        assert len(bus.get_history()) == 1

    @pytest.mark.asyncio
    async def test_history_accumulates_across_publishes(self) -> None:
        bus = EventBus()
        for i in range(10):
            await bus.publish(
                EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
            )
        assert len(bus.get_history()) == 10

    @pytest.mark.asyncio
    async def test_empty_history_on_new_bus(self) -> None:
        bus = EventBus()
        assert bus.get_history() == []


# ---------------------------------------------------------------------------
# History cap (max_history)
# ---------------------------------------------------------------------------


class TestEventBusHistoryCap:
    @pytest.mark.asyncio
    async def test_history_capped_at_max_history(self) -> None:
        bus = EventBus(max_history=5)
        for i in range(10):
            await bus.publish(
                EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
            )

        history = bus.get_history()
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_history_retains_most_recent_events_when_capped(self) -> None:
        bus = EventBus(max_history=3)
        events = [
            EventFactory.create(type=EventType.WORKER_UPDATE, data={"n": i})
            for i in range(6)
        ]
        for event in events:
            await bus.publish(event)

        history = bus.get_history()
        # Should keep the last 3
        assert history == events[-3:]

    @pytest.mark.asyncio
    async def test_max_history_one_keeps_latest(self) -> None:
        bus = EventBus(max_history=1)
        e1 = EventFactory.create(type=EventType.PHASE_CHANGE)
        e2 = EventFactory.create(type=EventType.ORCHESTRATOR_STATUS)
        await bus.publish(e1)
        await bus.publish(e2)

        history = bus.get_history()
        assert len(history) == 1
        assert history[0] is e2

    @pytest.mark.asyncio
    async def test_history_not_exceeded_by_one(self) -> None:
        limit = 100
        bus = EventBus(max_history=limit)
        for _ in range(limit + 1):
            await bus.publish(EventFactory.create(type=EventType.TRANSCRIPT_LINE))
        assert len(bus.get_history()) == limit


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


class TestEventBusClear:
    @pytest.mark.asyncio
    async def test_clear_removes_history(self) -> None:
        bus = EventBus()
        await bus.publish(EventFactory.create(type=EventType.PHASE_CHANGE))
        bus.clear()
        assert bus.get_history() == []

    @pytest.mark.asyncio
    async def test_clear_removes_subscribers(self) -> None:
        bus = EventBus()
        queue = bus.subscribe()
        bus.clear()

        # After clearing, publishing should not deliver to the old queue
        await bus.publish(EventFactory.create(type=EventType.ORCHESTRATOR_STATUS))
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_clear_on_empty_bus_does_not_raise(self) -> None:
        bus = EventBus()
        bus.clear()  # should not raise

    @pytest.mark.asyncio
    async def test_bus_usable_after_clear(self) -> None:
        bus = EventBus()
        await bus.publish(EventFactory.create(type=EventType.PHASE_CHANGE))
        bus.clear()

        queue = bus.subscribe()
        event = EventFactory.create(type=EventType.ORCHESTRATOR_STATUS)
        await bus.publish(event)

        assert queue.get_nowait() is event
        assert len(bus.get_history()) == 1


# ---------------------------------------------------------------------------
# Slow subscriber (queue full → drop oldest)
# ---------------------------------------------------------------------------


class TestEventBusSlowSubscriber:
    @pytest.mark.asyncio
    async def test_full_queue_does_not_block_publish(self) -> None:
        """Publishing to a full subscriber queue should not raise or block."""
        bus = EventBus()
        queue = bus.subscribe(max_queue=2)

        # Fill the queue
        for i in range(5):
            await bus.publish(
                EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
            )

        # Queue should still have exactly max_queue items
        assert queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_full_queue_drops_oldest_and_keeps_newest(self) -> None:
        """When a subscriber's queue is full, the oldest event is dropped."""
        bus = EventBus()
        queue = bus.subscribe(max_queue=2)

        events = [
            EventFactory.create(type=EventType.WORKER_UPDATE, data={"n": i})
            for i in range(4)
        ]
        for event in events:
            await bus.publish(event)

        # We published 4 events into a queue of size 2.
        # The bus drops the oldest to make room for the newest, so we expect
        # the two most-recently delivered events.
        items = [queue.get_nowait(), queue.get_nowait()]
        assert len(items) == 2
        # The last event published must be present
        assert events[-1] in items

    @pytest.mark.asyncio
    async def test_slow_subscriber_does_not_affect_other_subscribers(self) -> None:
        """A full slow subscriber must not prevent a normal subscriber from receiving."""
        bus = EventBus()
        bus.subscribe(max_queue=1)
        fast_queue = bus.subscribe(max_queue=100)

        # Overflow the slow queue
        events = [
            EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": i})
            for i in range(5)
        ]
        for event in events:
            await bus.publish(event)

        # Fast queue should have received all 5 events
        assert fast_queue.qsize() == 5

    @pytest.mark.asyncio
    async def test_history_unaffected_by_slow_subscriber(self) -> None:
        """Dropped events in a subscriber queue do not affect the history."""
        bus = EventBus()
        bus.subscribe(max_queue=1)  # tiny queue - will drop

        for i in range(10):
            await bus.publish(
                EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
            )

        # History should contain all 10, regardless of subscriber drops
        assert len(bus.get_history()) == 10


# ---------------------------------------------------------------------------
# Subscription context manager
# ---------------------------------------------------------------------------


class TestEventBusSubscription:
    async def test_subscription_yields_queue_that_receives_events(self) -> None:
        bus = EventBus()
        async with bus.subscription() as queue:
            event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"batch": 1})
            await bus.publish(event)
            received = queue.get_nowait()
            assert received is event

    async def test_subscription_unsubscribes_on_exit(self) -> None:
        bus = EventBus()
        async with bus.subscription() as queue:
            pass  # immediately exit

        # After exiting, queue should no longer receive events
        await bus.publish(EventFactory.create(type=EventType.ERROR))
        assert queue.empty()
        assert len(bus._subscribers) == 0

    async def test_subscription_unsubscribes_on_exception(self) -> None:
        bus = EventBus()
        with __import__("contextlib").suppress(RuntimeError):
            async with bus.subscription():
                raise RuntimeError("boom")

        # Cleanup must have happened despite the exception
        assert len(bus._subscribers) == 0

    async def test_subscription_respects_max_queue(self) -> None:
        bus = EventBus()
        async with bus.subscription(max_queue=42) as queue:
            assert queue.maxsize == 42

    async def test_multiple_concurrent_subscriptions(self) -> None:
        bus = EventBus()
        async with bus.subscription() as q1:
            async with bus.subscription() as q2:
                event1 = EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": 1})
                await bus.publish(event1)
                assert q1.get_nowait() is event1
                assert q2.get_nowait() is event1

            # q2's context has exited; only q1 remains
            event2 = EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": 2})
            await bus.publish(event2)
            assert q1.get_nowait() is event2
            assert q2.empty()


# ---------------------------------------------------------------------------
# EventLog._rotate_sync delegates to atomic_write
# ---------------------------------------------------------------------------


class TestRotateSyncUsesAtomicWrite:
    def test_rotate_sync_calls_atomic_write(self, tmp_path: Path) -> None:
        """_rotate_sync should delegate file writing to atomic_write."""
        log_path = tmp_path / "events.jsonl"
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"batch": 1})
        # Write enough data to exceed max_size_bytes
        log_path.write_text((event.model_dump_json() + "\n") * 100)

        event_log = EventLog(log_path)
        with patch("events.atomic_write") as mock_aw:
            event_log._rotate_sync(max_size_bytes=10, max_age_days=365)

        mock_aw.assert_called_once()
        call_args = mock_aw.call_args[0]
        assert call_args[0] == log_path

    def test_rotate_sync_passes_joined_content(self, tmp_path: Path) -> None:
        """_rotate_sync should pass newline-joined kept lines to atomic_write."""
        log_path = tmp_path / "events.jsonl"
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"batch": 1})
        log_path.write_text((event.model_dump_json() + "\n") * 5)

        event_log = EventLog(log_path)
        with patch("events.atomic_write") as mock_aw:
            event_log._rotate_sync(max_size_bytes=10, max_age_days=365)

        call_args = mock_aw.call_args[0]
        content = call_args[1]
        # Content should end with newline and contain valid JSON lines
        assert content.endswith("\n")
        lines = [line for line in content.split("\n") if line.strip()]
        assert len(lines) == 5


# ---------------------------------------------------------------------------
# Narrowed exception handling (issue #879)
# ---------------------------------------------------------------------------


class TestRotateSyncCorruptLines:
    """Verify _rotate_sync drops corrupt lines with debug logging."""

    def test_rotate_sync_skips_corrupt_lines_with_logging(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt lines during rotation should be dropped with debug logging."""
        import logging

        log_path = tmp_path / "events.jsonl"
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"batch": 1})
        valid_line = event.model_dump_json()
        # Write a mix of valid and corrupt lines (enough to exceed size threshold)
        lines = [valid_line, "corrupt garbage", valid_line, "also bad"]
        log_path.write_text("\n".join(lines) + "\n")

        event_log = EventLog(log_path)
        with caplog.at_level(logging.DEBUG, logger="hydraflow.events"):
            event_log._rotate_sync(max_size_bytes=10, max_age_days=365)

        assert "Dropping corrupt event line during rotation" in caplog.text
        # Verify corrupt lines have exc_info
        debug_records = [
            r for r in caplog.records if "Dropping corrupt" in r.getMessage()
        ]
        assert len(debug_records) >= 1
        assert debug_records[0].exc_info is not None

    def test_rotate_sync_skips_bad_timestamp_with_logging(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Lines with a bad timestamp string (ValueError) should also be dropped."""
        import json
        import logging

        log_path = tmp_path / "events.jsonl"
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"batch": 1})
        valid_line = event.model_dump_json()
        # Build a line that passes Pydantic validation but has an invalid timestamp
        bad_ts_data = json.loads(valid_line)
        bad_ts_data["timestamp"] = "not-a-datetime"
        bad_ts_line = json.dumps(bad_ts_data)
        lines = [valid_line, bad_ts_line, valid_line]
        log_path.write_text("\n".join(lines) + "\n")

        event_log = EventLog(log_path)
        with caplog.at_level(logging.DEBUG, logger="hydraflow.events"):
            event_log._rotate_sync(max_size_bytes=10, max_age_days=365)

        assert "Dropping corrupt event line during rotation" in caplog.text


class TestLoadSyncCorruptLines:
    """Verify EventLog._load_sync skips corrupt lines with warning+exc_info."""

    def test_load_sync_skips_corrupt_lines_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Corrupt lines during load should be skipped with warning+exc_info."""
        import logging

        log_path = tmp_path / "events.jsonl"
        event = HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"batch": 1})
        valid_line = event.model_dump_json()
        lines = [valid_line, "corrupt garbage", valid_line]
        log_path.write_text("\n".join(lines) + "\n")

        event_log = EventLog(log_path)
        with caplog.at_level(logging.WARNING, logger="hydraflow.events"):
            result = event_log._load_sync()

        assert len(result) == 2
        assert "Skipping corrupt event log line" in caplog.text
        warning_records = [
            r
            for r in caplog.records
            if "Skipping corrupt event log line" in r.getMessage()
        ]
        assert len(warning_records) >= 1
        assert warning_records[0].exc_info is not None


# ---------------------------------------------------------------------------
# Persist event error handling (issue #1030)
# ---------------------------------------------------------------------------


class TestPersistEventErrorHandling:
    """Verify fire-and-forget persist tasks handle errors gracefully."""

    @pytest.mark.asyncio
    async def test_persist_event_catches_runtime_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-OSError exceptions in _persist_event are caught and logged."""
        event_log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=event_log)

        with (
            patch.object(
                event_log, "append", side_effect=RuntimeError("thread pool exhausted")
            ),
            caplog.at_level(logging.WARNING, logger="hydraflow.events"),
        ):
            event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": 1})
            await bus.publish(event)
            await bus.flush_persists()

        records = [
            r
            for r in caplog.records
            if "Failed to persist event to disk" in r.getMessage()
        ]
        assert len(records) == 1
        assert records[0].exc_info is not None

    @pytest.mark.asyncio
    async def test_persist_event_catches_os_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError exceptions are still caught and logged with exc_info (regression test)."""
        event_log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=event_log)

        with (
            patch.object(event_log, "append", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.events"),
        ):
            event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": 1})
            await bus.publish(event)
            await bus.flush_persists()

        records = [
            r
            for r in caplog.records
            if "Failed to persist event to disk" in r.getMessage()
        ]
        assert len(records) == 1
        assert records[0].exc_info is not None

    @pytest.mark.asyncio
    async def test_publish_delivers_event_to_subscriber_despite_persist_failure(
        self, tmp_path: Path
    ) -> None:
        """Subscribers receive events even when persistence fails."""
        event_log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=event_log)
        queue = bus.subscribe()

        with patch.object(event_log, "append", side_effect=RuntimeError("boom")):
            event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
            await bus.publish(event)
            await bus.flush_persists()

        assert queue.get_nowait() is event

    @pytest.mark.asyncio
    async def test_publish_updates_history_despite_persist_failure(
        self, tmp_path: Path
    ) -> None:
        """In-memory history is updated even when persistence fails."""
        event_log = EventLog(tmp_path / "events.jsonl")
        bus = EventBus(event_log=event_log)

        with patch.object(event_log, "append", side_effect=RuntimeError("boom")):
            event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
            await bus.publish(event)
            await bus.flush_persists()

        assert event in bus.get_history()

    @pytest.mark.asyncio
    async def test_log_persist_failure_callback_skips_cancelled_task(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Done callback should not log for cancelled tasks."""
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        future.cancel()

        with caplog.at_level(logging.WARNING, logger="hydraflow.events"):
            _log_persist_failure(future)

        assert "Event persist task failed" not in caplog.text

    @pytest.mark.asyncio
    async def test_log_persist_failure_callback_logs_exception(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Done callback should log warning when task has an exception."""
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        future.set_exception(ValueError("bad serialization"))

        with caplog.at_level(logging.WARNING, logger="hydraflow.events"):
            _log_persist_failure(future)

        records = [
            r for r in caplog.records if "Event persist task failed" in r.getMessage()
        ]
        assert len(records) == 1
        assert records[0].exc_info is not None

    @pytest.mark.asyncio
    async def test_log_persist_failure_callback_silent_on_success(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Done callback should not log when task completed successfully."""
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        future.set_result(None)

        with caplog.at_level(logging.WARNING, logger="hydraflow.events"):
            _log_persist_failure(future)

        assert "Event persist task failed" not in caplog.text


# ---------------------------------------------------------------------------
# _append_sync OSError handling (issue #1038)
# ---------------------------------------------------------------------------


class TestAppendSyncOSError:
    """Verify EventLog._append_sync catches OSError gracefully."""

    def test_append_sync_logs_warning_on_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When the event log file can't be written, log warning and don't raise."""
        event_log = EventLog(tmp_path / "events.jsonl")
        # Write once to ensure the file exists
        event_log._append_sync("first line")

        with (
            patch("builtins.open", side_effect=OSError("disk full")),
            caplog.at_level(logging.WARNING, logger="hydraflow.events"),
        ):
            event_log._append_sync("should fail")  # should not raise

        assert "Could not append to event log" in caplog.text

    def test_append_sync_handles_mkdir_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When mkdir fails with OSError, log warning and don't raise."""
        event_log = EventLog(tmp_path / "subdir" / "events.jsonl")

        with (
            patch.object(Path, "mkdir", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.events"),
        ):
            event_log._append_sync("should fail")  # should not raise

        assert "Could not append to event log" in caplog.text


# ---------------------------------------------------------------------------
# _load_sync OSError handling (issue #1038)
# ---------------------------------------------------------------------------


class TestLoadSyncOSError:
    """Verify EventLog._load_sync catches OSError gracefully."""

    def test_load_sync_returns_empty_on_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When event log file can't be opened, return empty list with warning."""
        event_log = EventLog(tmp_path / "events.jsonl")
        # Create the file so exists() passes but open() fails
        event_log._append_sync('{"type": "test"}')

        with (
            patch("builtins.open", side_effect=OSError("permission denied")),
            caplog.at_level(logging.WARNING, logger="hydraflow.events"),
        ):
            result = event_log._load_sync()  # should not raise

        assert result == []
        assert "Could not read event log" in caplog.text


# --- _Counter.advance ---


class TestCounterAdvance:
    """Tests for _Counter.advance."""

    def test_advance_sets_minimum(self) -> None:
        from events import _Counter

        counter = _Counter()
        counter.advance(100)
        assert next(counter) == 100

    def test_advance_to_higher_value(self) -> None:
        from events import _Counter

        counter = _Counter()
        # Consume a few values
        next(counter)
        next(counter)
        counter.advance(50)
        assert next(counter) == 50

    def test_advance_replaces_iterator(self) -> None:
        from events import _Counter

        counter = _Counter()
        counter.advance(10)
        first = next(counter)
        second = next(counter)
        assert first == 10
        assert second == 11


# --- EventLog.append ---


class TestEventLogAppend:
    """Tests for EventLog.append."""

    @pytest.mark.asyncio
    async def test_append_writes_jsonl_line(self, tmp_path: Path) -> None:
        event_log = EventLog(tmp_path / "events.jsonl")
        event = EventFactory.create()
        await event_log.append(event)

        content = (tmp_path / "events.jsonl").read_text()
        assert content.strip()  # Not empty
        assert content.count("\n") == 1

    @pytest.mark.asyncio
    async def test_append_multiple_events(self, tmp_path: Path) -> None:
        event_log = EventLog(tmp_path / "events.jsonl")
        e1 = EventFactory.create(data={"n": 1})
        e2 = EventFactory.create(data={"n": 2})
        await event_log.append(e1)
        await event_log.append(e2)

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_append_creates_parent_dir(self, tmp_path: Path) -> None:
        event_log = EventLog(tmp_path / "deep" / "nested" / "events.jsonl")
        event = EventFactory.create()
        await event_log.append(event)

        assert (tmp_path / "deep" / "nested" / "events.jsonl").exists()
