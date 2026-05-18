"""Unit tests for SentryObservabilityAdapter and FakeSentry conformance.

Covers:
- SentryObservabilityAdapter forwards calls to sentry_sdk correctly.
- SentryObservabilityAdapter no-ops gracefully when sentry_sdk absent.
- FakeSentry satisfies ObservabilityPort (Protocol conformance).
- FakeSentry captures calls for assertion.
- Both adapter and fake satisfy isinstance(obj, ObservabilityPort).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mockworld.fakes.fake_sentry import FakeSentry
from observability.sentry_adapter import SentryObservabilityAdapter
from ports import ObservabilityPort

# ---------------------------------------------------------------------------
# Protocol conformance — both adapter and fake must satisfy ObservabilityPort
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_sentry_adapter_is_observability_port(self) -> None:
        adapter = SentryObservabilityAdapter()
        assert isinstance(adapter, ObservabilityPort)

    def test_fake_sentry_is_observability_port(self) -> None:
        fake = FakeSentry()
        assert isinstance(fake, ObservabilityPort)

    def test_fake_sentry_is_fake_adapter(self) -> None:
        fake = FakeSentry()
        assert fake._is_fake_adapter is True

    def test_adapter_is_not_fake(self) -> None:
        adapter = SentryObservabilityAdapter()
        assert adapter._is_fake_adapter is False


# ---------------------------------------------------------------------------
# SentryObservabilityAdapter — forwarding to sentry_sdk
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_sentry():
    """Inject a MagicMock sentry_sdk into sys.modules for the duration of a test."""
    m = MagicMock()
    had = "sentry_sdk" in sys.modules
    original = sys.modules.get("sentry_sdk")
    sys.modules["sentry_sdk"] = m
    m.reset_mock()
    yield m
    if had:
        sys.modules["sentry_sdk"] = original
    else:
        sys.modules.pop("sentry_sdk", None)


class TestSentryAdapterForwarding:
    def test_capture_exception_forwarded(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        exc = ValueError("boom")
        adapter.capture_exception(exc)
        mock_sentry.capture_exception.assert_called_once_with(exc)

    def test_capture_message_forwarded(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.capture_message("hello", level="warning")
        mock_sentry.capture_message.assert_called_once_with("hello", level="warning")

    def test_capture_message_default_level(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.capture_message("hi")
        mock_sentry.capture_message.assert_called_once_with("hi", level="info")

    def test_breadcrumb_forwarded(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.breadcrumb("test.category", "a message", level="info", key="val")
        mock_sentry.add_breadcrumb.assert_called_once()
        kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert kwargs["category"] == "test.category"
        assert kwargs["message"] == "a message"
        assert kwargs["level"] == "info"

    def test_breadcrumb_promotes_level_from_data(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.breadcrumb("cat", "msg", level="warning", extra="x")
        kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert kwargs["level"] == "warning"
        # extra should appear in data
        assert kwargs.get("data") == {"extra": "x"}

    def test_breadcrumb_no_extra_data_passes_none(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.breadcrumb("cat", "msg")
        kwargs = mock_sentry.add_breadcrumb.call_args[1]
        assert kwargs.get("data") is None

    def test_set_measurement_without_unit(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.set_measurement("my.metric", 42.0)
        mock_sentry.set_measurement.assert_called_once_with("my.metric", 42.0)

    def test_set_measurement_with_unit(self, mock_sentry: MagicMock) -> None:
        adapter = SentryObservabilityAdapter()
        adapter.set_measurement("my.metric", 1.5, "millisecond")
        mock_sentry.set_measurement.assert_called_once_with(
            "my.metric", 1.5, "millisecond"
        )


# ---------------------------------------------------------------------------
# SentryObservabilityAdapter — no-op when sentry_sdk absent
# ---------------------------------------------------------------------------


class TestSentryAdapterNoOp:
    def test_capture_exception_noop_when_absent(self) -> None:
        original = sys.modules.pop("sentry_sdk", None)
        try:
            adapter = SentryObservabilityAdapter()
            # Should not raise even if sentry_sdk is missing
            adapter.capture_exception(ValueError("x"))
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_capture_message_noop_when_absent(self) -> None:
        original = sys.modules.pop("sentry_sdk", None)
        try:
            adapter = SentryObservabilityAdapter()
            adapter.capture_message("hi")  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_breadcrumb_noop_when_absent(self) -> None:
        original = sys.modules.pop("sentry_sdk", None)
        try:
            adapter = SentryObservabilityAdapter()
            adapter.breadcrumb("cat", "msg", level="info")  # should not raise
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original

    def test_flush_returns_true_when_absent(self) -> None:
        original = sys.modules.pop("sentry_sdk", None)
        try:
            adapter = SentryObservabilityAdapter()
            result = adapter.flush()
            assert result is True
        finally:
            if original is not None:
                sys.modules["sentry_sdk"] = original


# ---------------------------------------------------------------------------
# FakeSentry — capture and assertion
# ---------------------------------------------------------------------------


class TestFakeSentry:
    def test_capture_exception_records_event(self) -> None:
        fake = FakeSentry()
        exc = RuntimeError("oops")
        fake.capture_exception(exc)
        assert len(fake.events) == 1
        assert fake.events[0]["type"] == "exception"
        assert "oops" in fake.events[0]["error"]

    def test_capture_message_records_event(self) -> None:
        fake = FakeSentry()
        fake.capture_message("something happened", level="warning")
        assert len(fake.events) == 1
        assert fake.events[0]["type"] == "message"
        assert fake.events[0]["message"] == "something happened"
        assert fake.events[0]["level"] == "warning"

    def test_breadcrumb_records(self) -> None:
        fake = FakeSentry()
        fake.breadcrumb("my.cat", "hello", level="info", key="value")
        assert len(fake.breadcrumbs) == 1
        bc = fake.breadcrumbs[0]
        assert bc["category"] == "my.cat"
        assert bc["message"] == "hello"
        assert bc["key"] == "value"

    def test_set_measurement_records(self) -> None:
        fake = FakeSentry()
        fake.set_measurement("memory.score", 0.75)
        assert len(fake.measurements) == 1
        assert fake.measurements[0]["name"] == "memory.score"
        assert fake.measurements[0]["value"] == 0.75

    def test_flush_returns_true(self) -> None:
        fake = FakeSentry()
        assert fake.flush() is True
        assert fake.flush(timeout_ms=5000) is True

    def test_multiple_events_captured(self) -> None:
        fake = FakeSentry()
        fake.capture_exception(ValueError("a"))
        fake.capture_message("b")
        fake.breadcrumb("c", "d")
        assert len(fake.events) == 2
        assert len(fake.breadcrumbs) == 1
