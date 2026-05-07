"""Regression tests for issue #7991.

Bug: subprocess_util global rate-limit state has unsynchronized concurrent
mutations — backoff counter can corrupt.

Root causes:
1. _trigger_rate_limit_cooldown() performs a non-atomic read-modify-write on
   _rate_limit_current_cooldown — no lock around the sequence.
2. _reset_rate_limit_backoff() can overwrite the backoff counter while a
   concurrent trigger is mid-sequence.
3. _wait_for_rate_limit_cooldown() reads _rate_limit_until once before sleeping;
   a concurrent trigger that extends the deadline is invisible to a sleeping
   caller.

Expected behaviour after fix:
- A module-level ``threading.Lock`` (``_rate_limit_lock``) guards all
  read-modify-write operations on ``_rate_limit_current_cooldown`` inside
  ``_trigger_rate_limit_cooldown()`` and ``_reset_rate_limit_backoff()``.
- ``_wait_for_rate_limit_cooldown()`` polls ``_rate_limit_until`` in a short
  loop so callers pick up deadlines extended by concurrent triggers.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import subprocess_util
from subprocess_util import (
    _RATE_LIMIT_COOLDOWN_SECONDS,
    _RATE_LIMIT_MAX_COOLDOWN_SECONDS,
    _reset_rate_limit_backoff,
    _trigger_rate_limit_cooldown,
    _wait_for_rate_limit_cooldown,
)


@pytest.fixture(autouse=True)
def _reset_rate_limit_state() -> Generator[None, None, None]:
    """Isolate all rate-limit module globals from other tests in the suite."""
    subprocess_util._rate_limit_until = None
    subprocess_util._rate_limit_current_cooldown = _RATE_LIMIT_COOLDOWN_SECONDS
    yield
    subprocess_util._rate_limit_until = None
    subprocess_util._rate_limit_current_cooldown = _RATE_LIMIT_COOLDOWN_SECONDS


# ---------------------------------------------------------------------------
# Lock presence — RED until threading.Lock is introduced
# ---------------------------------------------------------------------------


class TestRateLimitLockPresence:
    """A threading.Lock must be present and guard all rate-limit state mutations."""

    def test_rate_limit_lock_attribute_exists(self) -> None:
        assert hasattr(subprocess_util, "_rate_limit_lock"), (
            "subprocess_util must expose '_rate_limit_lock' — "
            "required to guard concurrent mutations of rate-limit globals"
        )

    def test_rate_limit_lock_is_threading_lock(self) -> None:
        lock = subprocess_util._rate_limit_lock
        assert isinstance(lock, type(threading.Lock())), (
            f"_rate_limit_lock must be threading.Lock (not asyncio.Lock), "
            f"so synchronous callers can acquire it without await; got {type(lock)}"
        )


# ---------------------------------------------------------------------------
# _trigger_rate_limit_cooldown — sequential correctness
# ---------------------------------------------------------------------------


class TestTriggerRateLimitCooldown:
    """Exponential-backoff doubling sequence must be correct under serial calls."""

    def test_first_trigger_doubles_base_cooldown(self) -> None:
        _trigger_rate_limit_cooldown()
        assert (
            subprocess_util._rate_limit_current_cooldown
            == _RATE_LIMIT_COOLDOWN_SECONDS * 2
        )

    def test_two_sequential_triggers_quadruple_base_cooldown(self) -> None:
        _trigger_rate_limit_cooldown()
        _trigger_rate_limit_cooldown()
        assert (
            subprocess_util._rate_limit_current_cooldown
            == _RATE_LIMIT_COOLDOWN_SECONDS * 4
        )

    def test_trigger_caps_at_max_cooldown(self) -> None:
        subprocess_util._rate_limit_current_cooldown = _RATE_LIMIT_MAX_COOLDOWN_SECONDS
        _trigger_rate_limit_cooldown()
        assert (
            subprocess_util._rate_limit_current_cooldown
            == _RATE_LIMIT_MAX_COOLDOWN_SECONDS
        )

    def test_trigger_sets_rate_limit_until_to_future(self) -> None:
        before = datetime.now(tz=UTC)
        _trigger_rate_limit_cooldown()
        assert subprocess_util._rate_limit_until is not None
        assert subprocess_util._rate_limit_until > before


# ---------------------------------------------------------------------------
# _reset_rate_limit_backoff — sequential correctness
# ---------------------------------------------------------------------------


class TestResetRateLimitBackoff:
    def test_reset_restores_base_cooldown_after_escalation(self) -> None:
        subprocess_util._rate_limit_current_cooldown = 240
        _reset_rate_limit_backoff()
        assert (
            subprocess_util._rate_limit_current_cooldown == _RATE_LIMIT_COOLDOWN_SECONDS
        )


# ---------------------------------------------------------------------------
# _wait_for_rate_limit_cooldown — must re-read extended deadline (RED until fixed)
# ---------------------------------------------------------------------------


class TestWaitForRateLimitCooldown:
    async def test_returns_immediately_when_no_cooldown_active(self) -> None:
        subprocess_util._rate_limit_until = None
        start = asyncio.get_event_loop().time()
        await _wait_for_rate_limit_cooldown()
        assert asyncio.get_event_loop().time() - start < 0.05

    async def test_returns_immediately_when_cooldown_already_expired(self) -> None:
        subprocess_util._rate_limit_until = datetime.now(tz=UTC) - timedelta(seconds=10)
        start = asyncio.get_event_loop().time()
        await _wait_for_rate_limit_cooldown()
        assert asyncio.get_event_loop().time() - start < 0.05

    async def test_re_reads_deadline_when_extended_during_sleep(self) -> None:
        """_wait_for_rate_limit_cooldown must loop, not sleep once.

        Current (broken) code computes ``remaining`` once and calls
        ``asyncio.sleep(remaining)`` a single time.  If a concurrent trigger
        extends ``_rate_limit_until`` while the caller is sleeping, that new
        deadline is never seen.

        The fix: poll in a short loop so each wake-up re-reads
        ``_rate_limit_until`` and resleeps when the deadline has moved.

        This test simulates the concurrent extension by modifying
        ``_rate_limit_until`` inside a patched ``asyncio.sleep``.  With the
        current broken code, ``sleep`` is called exactly once and the function
        returns — the extended deadline is missed.  With the fix, ``sleep``
        is called at least twice (initial wait + post-extension wait).
        """
        sleep_call_count = 0

        async def controlled_sleep(_seconds: float) -> None:
            nonlocal sleep_call_count
            sleep_call_count += 1
            if sleep_call_count == 1:
                # Simulate a concurrent trigger extending the global deadline.
                subprocess_util._rate_limit_until = datetime.now(tz=UTC) + timedelta(
                    seconds=0.1
                )
            else:
                # Let the polling loop terminate on the next check.
                subprocess_util._rate_limit_until = datetime.now(tz=UTC) - timedelta(
                    seconds=1
                )

        subprocess_util._rate_limit_until = datetime.now(tz=UTC) + timedelta(
            seconds=0.1
        )

        with patch("asyncio.sleep", new=controlled_sleep):
            await _wait_for_rate_limit_cooldown()

        assert sleep_call_count >= 2, (
            f"_wait_for_rate_limit_cooldown only slept {sleep_call_count} time(s) — "
            "must re-read _rate_limit_until in a loop so callers respect "
            "deadlines extended by concurrent triggers (issue #7991)"
        )
