"""Unit tests verifying EventBus.publish records a span event on the active span."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from mockworld.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


@pytest.mark.asyncio
async def test_publish_adds_span_event(fake):
    from src.events import EventBus, EventType, HydraFlowEvent

    bus = EventBus()
    tracer = trace.get_tracer("test")

    with tracer.start_as_current_span("hf.runner.plan"):
        await bus.publish(
            HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
        )

    span = fake.captured_spans[0]
    assert any(e.name == "hf.event" for e in span.events)


@pytest.mark.asyncio
async def test_publish_span_event_has_type_attribute(fake):
    from src.events import EventBus, EventType, HydraFlowEvent

    bus = EventBus()
    tracer = trace.get_tracer("test")

    with tracer.start_as_current_span("hf.runner.plan"):
        await bus.publish(
            HydraFlowEvent(type=EventType.PHASE_CHANGE, data={"phase": "plan"})
        )

    span = fake.captured_spans[0]
    hf_events = [e for e in span.events if e.name == "hf.event"]
    assert len(hf_events) == 1
    assert hf_events[0].attributes["hf.event.type"] == "phase_change"


@pytest.mark.asyncio
async def test_publish_no_span_event_when_no_active_span(fake):
    """publish must not raise when there is no active span."""
    from src.events import EventBus, EventType, HydraFlowEvent

    bus = EventBus()
    # No active span — should not raise
    await bus.publish(HydraFlowEvent(type=EventType.WORKER_UPDATE, data={}))
