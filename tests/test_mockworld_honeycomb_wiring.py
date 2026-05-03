"""Smoke tests for MockWorld → FakeHoneycomb wiring."""

from __future__ import annotations

from pathlib import Path

from opentelemetry import trace

from tests.scenarios.fakes.mock_world import MockWorld


def test_mockworld_exposes_honeycomb_property(tmp_path: Path):
    world = MockWorld(tmp_path)
    try:
        assert hasattr(world, "honeycomb")
        from mockworld.fakes.fake_honeycomb import FakeHoneycomb

        assert isinstance(world.honeycomb, FakeHoneycomb)
    finally:
        world.honeycomb.shutdown()


def test_mockworld_honeycomb_captures_spans(tmp_path: Path):
    world = MockWorld(tmp_path)
    try:
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("hf.runner.plan") as s:
            s.set_attribute("hf.issue", 1234)
        assert len(world.honeycomb.captured_spans) == 1
    finally:
        world.honeycomb.shutdown()


def test_mockworld_teardown_restores_noop_tracer(tmp_path: Path):
    world = MockWorld(tmp_path)
    world.honeycomb.shutdown()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("post-shutdown"):
        pass
    # The shutdown() method clears _TRACER_PROVIDER + the fake's exporter
    assert world.honeycomb.captured_spans == []
