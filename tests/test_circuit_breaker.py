"""Tests for the circuit breaker module."""

from __future__ import annotations

from unittest.mock import patch

from circuit_breaker import CircuitBreaker


class TestClosedToOpen:
    """CLOSED -> OPEN after max_failures consecutive failures."""

    def test_opens_after_max_failures(self) -> None:
        cb = CircuitBreaker("test", max_failures=3, reset_timeout=60.0)
        assert cb.state == CircuitBreaker.CLOSED

        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED

        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

    def test_stays_closed_below_max_failures(self) -> None:
        cb = CircuitBreaker("test", max_failures=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker("test", max_failures=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED


class TestOpenToHalfOpen:
    """OPEN -> HALF_OPEN after reset_timeout elapses."""

    def test_transitions_after_timeout(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, reset_timeout=10.0)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        # Simulate time passing beyond reset_timeout
        with patch(
            "circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 10.0
        ):
            assert cb.state == CircuitBreaker.HALF_OPEN

    def test_stays_open_before_timeout(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, reset_timeout=10.0)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        with patch(
            "circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 5.0
        ):
            assert cb.state == CircuitBreaker.OPEN


class TestHalfOpenTransitions:
    """HALF_OPEN -> CLOSED on success, HALF_OPEN -> OPEN on failure."""

    def _make_half_open(self) -> CircuitBreaker:
        cb = CircuitBreaker("test", max_failures=2, reset_timeout=1.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        # Force into HALF_OPEN
        cb._state = CircuitBreaker.HALF_OPEN
        return cb

    def test_success_closes_circuit(self) -> None:
        cb = self._make_half_open()
        cb.record_success()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb._failure_count == 0

    def test_failure_reopens_circuit(self) -> None:
        cb = self._make_half_open()
        # Reset failure count to simulate fresh half-open probe
        cb._failure_count = 0
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN


class TestAllowRequest:
    """allow_request() returns correctly per state."""

    def test_allows_when_closed(self) -> None:
        cb = CircuitBreaker("test", max_failures=5)
        assert cb.allow_request() is True

    def test_blocks_when_open(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, reset_timeout=60.0)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.allow_request() is False

    def test_allows_when_half_open(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, reset_timeout=1.0)
        cb.record_failure()
        cb._state = CircuitBreaker.HALF_OPEN
        assert cb.allow_request() is True

    def test_allows_after_timeout_triggers_half_open(self) -> None:
        cb = CircuitBreaker("test", max_failures=1, reset_timeout=5.0)
        cb.record_failure()
        assert cb.allow_request() is False

        with patch(
            "circuit_breaker.time.monotonic", return_value=cb._last_failure_time + 5.0
        ):
            assert cb.allow_request() is True
            assert cb.state == CircuitBreaker.HALF_OPEN


class TestReset:
    """reset() returns the breaker to CLOSED with zero failures."""

    def test_reset_from_open(self) -> None:
        cb = CircuitBreaker("test", max_failures=1)
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        cb.reset()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb._failure_count == 0

    def test_reset_from_half_open(self) -> None:
        cb = CircuitBreaker("test", max_failures=1)
        cb.record_failure()
        cb._state = CircuitBreaker.HALF_OPEN
        cb.reset()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb._failure_count == 0

    def test_reset_is_idempotent(self) -> None:
        cb = CircuitBreaker("test", max_failures=5)
        cb.reset()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb._failure_count == 0


class TestDefaults:
    """Verify default parameter values."""

    def test_default_max_failures(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.max_failures == 5

    def test_default_reset_timeout(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.reset_timeout == 60.0

    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.state == CircuitBreaker.CLOSED
        assert cb._failure_count == 0
