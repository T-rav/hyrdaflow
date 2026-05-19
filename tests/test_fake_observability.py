"""Conformance and behavioral tests for FakeObservability.

ADR-0047 requires every Port defined in ports.py to have a named Fake in
mockworld/fakes/.  FakeSentry was updated in PR #8834 to satisfy
ObservabilityPort; FakeObservability is the explicit alias that makes the
ADR-0047 naming convention discoverable by coverage-matrix tooling.

Covers:
- FakeObservability is ObservabilityPort (Protocol conformance).
- FakeObservability IS FakeSentry (alias identity).
- All five Port methods record the expected state.
- flush() always returns True (no real I/O in tests).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mockworld.fakes import FakeObservability, FakeSentry
from mockworld.fakes.fake_sentry import FakeObservability as FakeObservabilityDirect
from ports import ObservabilityPort

# ---------------------------------------------------------------------------
# ADR-0047 naming convention — alias identity
# ---------------------------------------------------------------------------


class TestAliasIdentity:
    def test_fake_observability_is_fake_sentry_class(self) -> None:
        assert FakeObservability is FakeSentry

    def test_direct_import_matches_init_export(self) -> None:
        assert FakeObservability is FakeObservabilityDirect

    def test_instances_share_type(self) -> None:
        assert isinstance(FakeObservability(), FakeSentry)
        assert isinstance(FakeSentry(), FakeObservability)


# ---------------------------------------------------------------------------
# ObservabilityPort Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_isinstance_observability_port(self) -> None:
        fake = FakeObservability()
        assert isinstance(fake, ObservabilityPort)

    def test_is_fake_adapter_sentinel(self) -> None:
        fake = FakeObservability()
        assert fake._is_fake_adapter is True

    def test_has_all_port_methods(self) -> None:
        fake = FakeObservability()
        for method in (
            "capture_exception",
            "capture_message",
            "breadcrumb",
            "set_measurement",
            "flush",
        ):
            assert callable(getattr(fake, method, None)), (
                f"FakeObservability missing ObservabilityPort method: {method}"
            )


# ---------------------------------------------------------------------------
# Behavioral assertions — recording
# ---------------------------------------------------------------------------


class TestCaptureException:
    def test_records_exception_type_and_message(self) -> None:
        fake = FakeObservability()
        fake.capture_exception(ValueError("bad input"))
        assert len(fake.events) == 1
        assert fake.events[0]["type"] == "exception"
        assert "bad input" in fake.events[0]["error"]

    def test_accepts_base_exception(self) -> None:
        fake = FakeObservability()
        fake.capture_exception(KeyboardInterrupt())
        assert fake.events[0]["type"] == "exception"

    def test_multiple_exceptions_accumulate(self) -> None:
        fake = FakeObservability()
        fake.capture_exception(RuntimeError("first"))
        fake.capture_exception(OSError("second"))
        assert len(fake.events) == 2


class TestCaptureMessage:
    def test_records_message_and_default_level(self) -> None:
        fake = FakeObservability()
        fake.capture_message("something happened")
        assert len(fake.events) == 1
        ev = fake.events[0]
        assert ev["type"] == "message"
        assert ev["message"] == "something happened"
        assert ev["level"] == "info"

    def test_records_explicit_level(self) -> None:
        fake = FakeObservability()
        fake.capture_message("danger", level="error")
        assert fake.events[0]["level"] == "error"


class TestBreadcrumb:
    def test_records_category_and_message(self) -> None:
        fake = FakeObservability()
        fake.breadcrumb("loop.tick", "phase started")
        assert len(fake.breadcrumbs) == 1
        bc = fake.breadcrumbs[0]
        assert bc["category"] == "loop.tick"
        assert bc["message"] == "phase started"

    def test_extra_kwargs_stored(self) -> None:
        fake = FakeObservability()
        fake.breadcrumb("loop.tick", "phase started", issue=42, stage="implement")
        bc = fake.breadcrumbs[0]
        assert bc["issue"] == 42
        assert bc["stage"] == "implement"

    def test_multiple_breadcrumbs_accumulate(self) -> None:
        fake = FakeObservability()
        fake.breadcrumb("a", "first")
        fake.breadcrumb("b", "second")
        assert len(fake.breadcrumbs) == 2


class TestSetMeasurement:
    def test_records_name_and_value(self) -> None:
        fake = FakeObservability()
        fake.set_measurement("loop.duration_ms", 123.4)
        assert len(fake.measurements) == 1
        m = fake.measurements[0]
        assert m["name"] == "loop.duration_ms"
        assert m["value"] == 123.4

    def test_records_unit_when_provided(self) -> None:
        fake = FakeObservability()
        fake.set_measurement("latency", 5.0, "millisecond")
        assert fake.measurements[0]["unit"] == "millisecond"

    def test_default_unit_is_empty_string(self) -> None:
        fake = FakeObservability()
        fake.set_measurement("count", 1.0)
        assert fake.measurements[0]["unit"] == ""


class TestFlush:
    def test_flush_returns_true(self) -> None:
        fake = FakeObservability()
        assert fake.flush() is True

    def test_flush_with_timeout_returns_true(self) -> None:
        fake = FakeObservability()
        assert fake.flush(timeout_ms=5000) is True

    def test_flush_does_not_clear_state(self) -> None:
        fake = FakeObservability()
        fake.capture_exception(RuntimeError("x"))
        fake.breadcrumb("cat", "msg")
        fake.flush()
        assert len(fake.events) == 1
        assert len(fake.breadcrumbs) == 1


# ---------------------------------------------------------------------------
# State isolation — each instance is independent
# ---------------------------------------------------------------------------


class TestStateIsolation:
    def test_instances_do_not_share_events(self) -> None:
        a = FakeObservability()
        b = FakeObservability()
        a.capture_exception(ValueError("only in a"))
        assert len(a.events) == 1
        assert len(b.events) == 0

    def test_instances_do_not_share_breadcrumbs(self) -> None:
        a = FakeObservability()
        b = FakeObservability()
        a.breadcrumb("cat", "msg")
        assert len(a.breadcrumbs) == 1
        assert len(b.breadcrumbs) == 0
