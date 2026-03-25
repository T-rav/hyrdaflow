"""Simple circuit breaker for protecting against cascading failures."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("hydraflow.circuit_breaker")


class CircuitBreaker:
    """Three-state circuit breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

    Parameters
    ----------
    name: Human-readable name for logging.
    max_failures: Consecutive failures before opening the circuit.
    reset_timeout: Seconds to wait in OPEN state before allowing a probe.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, max_failures: int = 5, reset_timeout: float = 60.0):
        self.name = name
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> str:
        if (
            self._state == self.OPEN
            and time.monotonic() - self._last_failure_time >= self.reset_timeout
        ):
            self._state = self.HALF_OPEN
            logger.info("Circuit breaker '%s' entering HALF_OPEN state", self.name)
        return self._state

    def record_success(self) -> None:
        if self._state in (self.HALF_OPEN, self.CLOSED):
            self._failure_count = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.max_failures:
            self._state = self.OPEN
            logger.warning(
                "Circuit breaker '%s' OPEN after %d consecutive failures",
                self.name,
                self._failure_count,
            )

    def allow_request(self) -> bool:
        current = self.state  # triggers HALF_OPEN transition if timeout elapsed
        return current in (self.CLOSED, self.HALF_OPEN)

    def reset(self) -> None:
        self._state = self.CLOSED
        self._failure_count = 0
