"""Unit tests for src/telemetry/subprocess_bridge.py."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from src.telemetry.subprocess_bridge import bridge_event_to_span


@pytest.fixture
def captured_spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    trace._TRACER_PROVIDER = None  # noqa: SLF001


def test_bridges_tool_call_event(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(
            span,
            {
                "type": "tool_use",
                "tool": "Edit",
                "duration_ms": 234,
                "name": "edit-1",
            },
        )
    s = captured_spans.get_finished_spans()[0]
    assert len(s.events) == 1
    ev = s.events[0]
    assert ev.name == "claude.tool"
    assert ev.attributes["claude.tool"] == "Edit"
    assert ev.attributes["claude.duration_ms"] == 234


def test_skips_unknown_event_type(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(span, {"type": "unknown_thing", "data": "x"})
    s = captured_spans.get_finished_spans()[0]
    assert s.events == ()


def test_handles_malformed_event_safely(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(span, None)  # type: ignore[arg-type]
        bridge_event_to_span(span, {})
        bridge_event_to_span(span, {"type": "tool_use"})  # missing fields
    s = captured_spans.get_finished_spans()[0]
    # Best-effort: malformed events drop, never raise. Last call may add a
    # tool event with default attrs; that's acceptable as long as no exception.
    assert len(s.events) <= 1


def test_drops_disallowed_attribute_keys(captured_spans):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.subprocess.claude") as span:
        bridge_event_to_span(
            span,
            {
                "type": "tool_use",
                "tool": "Read",
                "duration_ms": 12,
                "user_email": "should-be-dropped@example.com",
            },
        )
    s = captured_spans.get_finished_spans()[0]
    ev = s.events[0]
    assert "user_email" not in ev.attributes


def test_no_active_span_is_noop():
    # Calling with span=None must not raise.
    bridge_event_to_span(None, {"type": "tool_use", "tool": "Edit"})  # type: ignore[arg-type]
