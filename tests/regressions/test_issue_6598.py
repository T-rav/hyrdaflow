"""Regression test for issue #6598.

``BaseRunner._execute`` initialises ``last_auth_error`` to ``None`` and
unconditionally executes ``raise last_auth_error`` after its retry loop.
If ``_AUTH_RETRY_MAX`` is 0 the loop body never runs, so the raise becomes
``raise None`` which produces a ``TypeError: exceptions must derive from
BaseException`` instead of a meaningful error.

The test patches ``_AUTH_RETRY_MAX = 0`` and asserts that ``_execute``
raises a proper exception (not ``TypeError``).  It will fail (RED) until
the raise is guarded with a None-check or equivalent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from base_runner import BaseRunner
from events import EventBus
from runner_utils import AuthenticationRetryError

# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class _TestRunner(BaseRunner):
    """Minimal concrete subclass used in tests."""

    _log = logging.getLogger("hydraflow.test_runner")


# ---------------------------------------------------------------------------
# Test — _execute with _AUTH_RETRY_MAX=0 must not raise TypeError
# ---------------------------------------------------------------------------


class TestExecuteZeroRetryMax:
    """When _AUTH_RETRY_MAX is 0 the retry loop never runs.

    ``_execute`` should raise a meaningful error — not ``TypeError``
    from ``raise None``.
    """

    @pytest.mark.asyncio
    async def test_zero_retry_max_raises_meaningful_error_not_typeerror(
        self, config, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """Setting _AUTH_RETRY_MAX=0 causes ``raise None`` → TypeError.

        This test FAILS (RED) until the raise is guarded with a None-check
        or the variable is initialised to a real exception.
        """
        runner = _TestRunner(config, event_bus)

        with patch.object(type(runner), "_AUTH_RETRY_MAX", 0):
            try:
                await runner._execute(
                    ["claude", "-p"],
                    "prompt",
                    tmp_path,
                    {"issue": 99, "source": "test"},
                )
                pytest.fail("_execute should raise when retry loop is exhausted")
            except TypeError:
                pytest.fail(
                    "_execute raised TypeError from 'raise None' instead of a "
                    "meaningful exception — last_auth_error was never assigned "
                    "because the retry loop never ran (_AUTH_RETRY_MAX=0). "
                    "See issue #6598."
                )
            except (AuthenticationRetryError, RuntimeError):
                pass  # correct — a meaningful error was raised
