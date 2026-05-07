"""Regression test for issue #7838.

Bug: ``EpicManager.release_epic()`` checks whether ``epic_number`` is in
``self._release_locks`` and then creates a new ``asyncio.Lock()`` outside of
any lock — the classic check-then-set (TOCTOU) pattern:

    if epic_number not in self._release_locks:
        self._release_locks[epic_number] = asyncio.Lock()

Two coroutines can both observe the key absent, both create a lock, and one
silently overwrites the other — allowing two concurrent releases of the same
epic to proceed past the per-epic guard simultaneously.

Expected behaviour after fix:
  ``release_epic`` uses ``setdefault`` so two concurrent calls always share
  the same per-epic Lock.  ``setdefault`` uses the internal C-level hash-table
  lookup (not Python ``__contains__``), so it cannot be fooled by the race
  condition modelled in the test below.

This test is RED against the current (buggy) code and GREEN after the fix.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))


def _make_manager(tmp_path: Path):
    """Build an EpicManager with standard mocks for behavioural tests."""
    from unittest.mock import AsyncMock

    from epic import EpicManager
    from events import EventBus
    from state import StateTracker
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
    )
    state = StateTracker(config.state_file)
    bus = EventBus()
    prs = AsyncMock()
    fetcher = AsyncMock()
    return EpicManager(config, state, prs, fetcher, bus)


class TestReleaseLockTOCTOU:
    """Issue #7838 — ``release_epic`` must use an atomic dict operation
    (``setdefault``) to prevent TOCTOU races when initialising per-epic locks.

    The bug: the check-then-set pattern calls Python ``__contains__``, which
    can be forced to return False even when the key is present (modelling the
    TOCTOU window).  Two coroutines then each install a separate Lock and run
    their critical sections concurrently.

    The fix: ``setdefault`` uses the internal C-level hash-table lookup, which
    bypasses ``__contains__``.  It sees the real key on the second call and
    returns the existing Lock, so both coroutines serialise through the same
    lock.
    """

    @pytest.mark.asyncio
    async def test_concurrent_release_installs_one_lock(self, tmp_path: Path) -> None:
        """Two concurrent ``release_epic(N)`` calls must serialise through the
        same per-epic Lock.

        ``AlwaysMissDict`` overrides ``__contains__`` to return ``False`` for
        every key, modelling the TOCTOU window where both coroutines observe the
        key absent.  ``setdefault`` is immune because it never calls
        ``__contains__``; the check-then-set pattern is not.

        RED on buggy code (max concurrent == 2), GREEN after fix (max == 1).
        """

        class AlwaysMissDict(dict):
            """Simulate the TOCTOU race: always reports key absent."""

            def __contains__(self, _key: object) -> bool:  # type: ignore[override]
                return False

        mgr = _make_manager(tmp_path)
        mgr._release_locks = AlwaysMissDict()  # type: ignore[assignment]

        concurrent_count = 0
        max_concurrent = 0

        async def _track_do_release(_n: int) -> dict[str, object]:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0)  # yield so the other coroutine can run
            concurrent_count -= 1
            return {}

        mgr._do_release_epic = _track_do_release  # type: ignore[method-assign]

        await asyncio.gather(
            mgr.release_epic(1),
            mgr.release_epic(1),
        )

        assert max_concurrent == 1, (
            f"Expected max 1 concurrent _do_release_epic call, got {max_concurrent}. "
            "release_epic must use setdefault (not check-then-set) so concurrent "
            "calls always share the same per-epic Lock and serialise correctly."
        )
