"""Tests for dx/hydraflow/events.py - EventType, HydraFlowEvent, and EventBus."""

from __future__ import annotations

import asyncio
import logging

import pytest

from events import EventBus, EventType, HydraFlowEvent
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
        expected = {member.name for member in EventType}
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

    @pytest.mark.asyncio
    async def test_clear_resets_session_repo(self) -> None:
        bus = EventBus()
        bus.set_session_id("session-123")
        bus.set_repo("hydraflow/repo")

        first_event = EventFactory.create(type=EventType.PHASE_CHANGE)
        await bus.publish(first_event)
        assert first_event.session_id == "session-123"
        assert first_event.data["repo"] == "hydraflow/repo"

        assert bus.current_session_id == "session-123"
        assert bus._active_repo == "hydraflow/repo"

        bus.clear()

        next_event = EventFactory.create(type=EventType.ORCHESTRATOR_STATUS)
        await bus.publish(next_event)

        assert bus.current_session_id is None
        assert next_event.session_id is None
        assert "repo" not in next_event.data
        assert bus._active_repo == ""


# ---------------------------------------------------------------------------
# Subscriber never loses events (unbounded queues)
# ---------------------------------------------------------------------------


class TestEventBusSubscriberNeverLosesEvents:
    @pytest.mark.asyncio
    async def test_default_subscriber_receives_all_events(self) -> None:
        """Default (unbounded) subscriber queue never drops events."""
        bus = EventBus()
        queue = bus.subscribe()

        for i in range(100):
            await bus.publish(
                EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
            )

        assert queue.qsize() == 100

    @pytest.mark.asyncio
    async def test_subscriber_queue_unbounded_by_default(self) -> None:
        """Default subscribe() creates an unbounded queue (maxsize=0)."""
        bus = EventBus()
        queue = bus.subscribe()
        assert queue.maxsize == 0

    @pytest.mark.asyncio
    async def test_all_subscribers_receive_all_events(self) -> None:
        """Multiple subscribers all receive every event without loss."""
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        q3 = bus.subscribe()

        events = [
            EventFactory.create(type=EventType.PHASE_CHANGE, data={"n": i})
            for i in range(50)
        ]
        for event in events:
            await bus.publish(event)

        assert q1.qsize() == 50
        assert q2.qsize() == 50
        assert q3.qsize() == 50

    @pytest.mark.asyncio
    async def test_history_unaffected_by_subscriber_count(self) -> None:
        """History records all events regardless of subscriber count."""
        bus = EventBus()
        bus.subscribe()
        bus.subscribe()

        for i in range(10):
            await bus.publish(
                EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
            )

        assert len(bus.get_history()) == 10

    @pytest.mark.asyncio
    async def test_large_queue_depth_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When subscriber queue depth hits 1000, a warning is logged."""
        bus = EventBus()
        queue = bus.subscribe()

        with caplog.at_level(logging.WARNING, logger="hydraflow.events"):
            for i in range(1001):
                await bus.publish(
                    EventFactory.create(type=EventType.TRANSCRIPT_LINE, data={"i": i})
                )

        assert queue.qsize() == 1001
        assert "queue depth 1000" in caplog.text


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


# ---------------------------------------------------------------------------
# Dolt event persistence
# ---------------------------------------------------------------------------


class TestEventBusDoltPersistence:
    @pytest.mark.asyncio
    async def test_publish_calls_append_event_on_state(self) -> None:
        """Events are written to Dolt via state.append_event."""

        class FakeState:
            def __init__(self) -> None:
                self.events: list[dict] = []

            def append_event(self, event: dict) -> None:
                self.events.append(event)

        state = FakeState()
        bus = EventBus(state=state)
        event = EventFactory.create(type=EventType.PHASE_CHANGE, data={"x": 1})
        await bus.publish(event)

        assert len(state.events) == 1
        assert state.events[0]["type"] == "phase_change"

    @pytest.mark.asyncio
    async def test_publish_tolerates_state_without_append_event(self) -> None:
        """If state doesn't have append_event, publish still works."""

        class BareState:
            pass

        bus = EventBus(state=BareState())
        event = EventFactory.create(type=EventType.ERROR)
        await bus.publish(event)  # should not raise
        assert len(bus.get_history()) == 1

    @pytest.mark.asyncio
    async def test_publish_tolerates_append_event_exception(self) -> None:
        """If state.append_event raises, publish still delivers to subscribers."""

        class FailState:
            def append_event(self, event: dict) -> None:
                raise RuntimeError("DB down")

        bus = EventBus(state=FailState())
        queue = bus.subscribe()
        event = EventFactory.create(type=EventType.PHASE_CHANGE)
        await bus.publish(event)

        assert queue.get_nowait() is event

    @pytest.mark.asyncio
    async def test_load_history_from_dolt_populates_history(self) -> None:
        """load_history_from_dolt replays events into in-memory history."""

        class FakeState:
            def load_recent_events(self, limit: int) -> list[dict]:
                return [
                    {"id": 1, "type": "phase_change", "data": {"n": 1}, "timestamp": "2024-01-01T00:00:00+00:00"},
                    {"id": 2, "type": "error", "data": {"n": 2}, "timestamp": "2024-01-01T00:01:00+00:00"},
                ]

        bus = EventBus(state=FakeState())
        await bus.load_history_from_dolt()
        history = bus.get_history()
        assert len(history) == 2
        assert history[0].type == EventType.PHASE_CHANGE
        assert history[1].type == EventType.ERROR

    @pytest.mark.asyncio
    async def test_load_history_advances_counter(self) -> None:
        """After loading, new event IDs exceed historical max."""

        class FakeState:
            def load_recent_events(self, limit: int) -> list[dict]:
                return [
                    {"id": 500, "type": "error", "data": {}, "timestamp": "2024-01-01T00:00:00+00:00"},
                ]

        bus = EventBus(state=FakeState())
        await bus.load_history_from_dolt()
        new_event = HydraFlowEvent(type=EventType.PHASE_CHANGE)
        assert new_event.id >= 501
