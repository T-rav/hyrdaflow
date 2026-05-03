"""Unit tests for fake_honeycomb.FakeHoneycomb."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from mockworld.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_captures_span(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    assert len(fake.captured_spans) == 1
    assert fake.captured_spans[0].name == "hf.runner.plan"


def test_find_spans_by_name(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    with tracer.start_as_current_span("hf.port.workspace.git"):
        pass
    matches = fake.find_spans(name="hf.runner.plan")
    assert len(matches) == 1


def test_find_spans_by_attrs(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 1234)
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 9999)
    matches = fake.find_spans(attrs={"hf.issue": 1234})
    assert len(matches) == 1


def test_trace_for_issue(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 1234)
    with tracer.start_as_current_span("hf.runner.implement") as s:
        s.set_attribute("hf.issue", 1234)
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 9999)
    spans = fake.trace_for_issue(1234)
    assert len(spans) == 2
    names = {s.name for s in spans}
    assert names == {"hf.runner.plan", "hf.runner.implement"}


def test_assert_attribute_present_passes(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan") as s:
        s.set_attribute("hf.issue", 1234)
    fake.assert_attribute_present("hf.runner.plan", "hf.issue")


def test_assert_attribute_present_fails(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    with pytest.raises(AssertionError, match="hf.issue"):
        fake.assert_attribute_present("hf.runner.plan", "hf.issue")


def test_reset_clears_captured_spans(fake):
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("hf.runner.plan"):
        pass
    fake.reset()
    assert fake.captured_spans == []


def test_shutdown_restores_noop_tracer(fake):
    fake.shutdown()
    # After shutdown, new spans don't get captured by this exporter.
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("post-shutdown"):
        pass
    assert fake.captured_spans == []
