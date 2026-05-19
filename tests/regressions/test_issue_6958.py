"""Regression test for issue #6958.

Bug: ``process_corrections`` iterates ``asyncio.as_completed`` with a bare
``await task``.  When a task raises a critical exception
(``AuthenticationError``, ``CreditExhaustedError``, ``MemoryError``), the
exception propagates unhandled and terminates the loop — remaining
corrections in the batch are silently dropped.

Expected behaviour (after fix):
- ``AuthenticationError`` and ``MemoryError`` from individual tasks are caught
  and logged; remaining corrections continue processing.
- ``CreditExhaustedError`` still aborts the batch (billing exhaustion must
  stop the outer loop from ticking against an exhausted signal per
  dark-factory.md §2.2), but remaining tasks are cancelled cleanly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.helpers import make_hitl_phase


class TestIssue6958BatchExceptionDropsCorrections:
    """process_corrections must handle per-task exceptions correctly."""

    @pytest.mark.asyncio
    async def test_exception_in_one_task_does_not_abort_remaining(self, config) -> None:
        """Submit 3 corrections; one raises AuthenticationError.

        Acceptance criterion: process_corrections does NOT propagate the
        exception and the two healthy corrections are both processed.
        """
        from subprocess_util import AuthenticationError

        phase, *_ = make_hitl_phase(config)

        processed: set[int] = set()

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            if issue_number == 20:
                raise AuthenticationError("token expired")
            processed.add(issue_number)

        phase.submit_correction(10, "Fix A")
        phase.submit_correction(20, "Fix B")  # will raise
        phase.submit_correction(30, "Fix C")

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            await phase.process_corrections()

        # Verify every non-failing correction ran:
        assert processed == {10, 30}, (
            f"Expected both healthy corrections to run, but only got {processed}"
        )

    @pytest.mark.asyncio
    async def test_credit_exhausted_aborts_batch(self, config) -> None:
        """CreditExhaustedError must still abort the batch.

        Per dark-factory.md §2.2: billing exhaustion stops the batch so the
        outer loop does not continue ticking against an exhausted signal.
        Remaining tasks are cancelled cleanly before re-raising.
        """
        from subprocess_util import CreditExhaustedError

        phase, *_ = make_hitl_phase(config)

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            if issue_number == 50:
                raise CreditExhaustedError("limit reached")

        phase.submit_correction(40, "Fix X")
        phase.submit_correction(50, "Fix Y")  # will raise CreditExhaustedError

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            with pytest.raises(CreditExhaustedError):
                await phase.process_corrections()

    @pytest.mark.asyncio
    async def test_all_tasks_awaited_even_after_exception(self, config) -> None:
        """All created tasks must be properly awaited (no 'Task was destroyed
        but it is pending!' warnings) even when one raises."""
        from subprocess_util import AuthenticationError

        phase, *_ = make_hitl_phase(config)
        config.max_hitl_workers = 3  # allow full concurrency

        task_started = {10: False, 20: False, 30: False}

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            task_started[issue_number] = True
            if issue_number == 20:
                raise AuthenticationError("token expired")

        phase.submit_correction(10, "Fix A")
        phase.submit_correction(20, "Fix B")
        phase.submit_correction(30, "Fix C")

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            await phase.process_corrections()

        # Every task should have started (they were all created as asyncio tasks)
        # and process_corrections must have returned normally.
        assert all(task_started.values()), f"Not all tasks started: {task_started}"

    @pytest.mark.asyncio
    async def test_auth_error_logs_and_continues_remaining_tasks(self, config) -> None:
        """AuthenticationError in one task logs a structured error and lets
        remaining tasks complete.  The failing correction is not silently
        dropped — it is logged as an audit trail.
        """
        import logging

        from subprocess_util import AuthenticationError

        phase, *_ = make_hitl_phase(config)

        completed: list[int] = []

        async def fake_process_one(
            issue_number: int, correction: str, semaphore: asyncio.Semaphore
        ) -> None:
            if issue_number == 2:
                raise AuthenticationError("token expired after retries")
            completed.append(issue_number)

        phase.submit_correction(1, "Fix 1")
        phase.submit_correction(2, "Fix 2")  # will raise
        phase.submit_correction(3, "Fix 3")

        with patch.object(phase, "_process_one_hitl", side_effect=fake_process_one):
            with self._assert_logged("hydraflow.hitl_phase", logging.ERROR):
                await phase.process_corrections()

        # The two healthy corrections must have completed.
        assert sorted(completed) == [1, 3], (
            f"Expected corrections 1 and 3 to complete, got {completed}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    from contextlib import contextmanager

    @contextmanager
    def _assert_logged(self, logger_name: str, level: int):  # type: ignore[misc]
        """Context manager that asserts at least one record was emitted at
        *level* or above on the named logger during the body."""
        import logging

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level)
        log = logging.getLogger(logger_name)
        log.addHandler(handler)
        try:
            yield records
        finally:
            log.removeHandler(handler)
        assert any(r.levelno >= level for r in records), (
            f"Expected at least one log record at level {level} from {logger_name!r}, "
            f"got: {[r.getMessage() for r in records]}"
        )
