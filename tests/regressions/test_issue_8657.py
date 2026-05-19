"""Regression test for issue #8657.

Bug: ``subprocess_util._get_gh_semaphore()`` is a check-then-set TOCTOU
pattern that can construct two ``asyncio.Semaphore`` objects when two
threads race past the ``if _gh_semaphore is None`` guard before either
store happens.  The second STORE silently replaces the first; any caller
that captured the first reference now holds a semaphore disconnected
from the global, breaking the global concurrency limit invariant.

Sibling: issue #7838 (``EpicManager._release_locks``) and issue #7839 /
PR #8665 (``workspace._FETCH_LOCKS`` / ``_WORKTREE_LOCKS``) — same
anti-pattern, fixed the same way (atomic operation that cannot be
fooled by ``__contains__`` / TOCTOU).

Expected behaviour after fix:
    ``_get_gh_semaphore()`` guards the None-check + construct + assign
    sequence with the existing module-level ``_rate_limit_lock``
    (``threading.Lock``).  Two threads that race the lazy init still
    construct exactly one ``Semaphore`` between them.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC))

import subprocess_util  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_semaphore_global() -> Generator[None, None, None]:
    """Isolate the semaphore global from other tests in the suite."""
    original = subprocess_util._gh_semaphore
    subprocess_util._gh_semaphore = None
    yield
    subprocess_util._gh_semaphore = original


class TestSemaphoreLazyInitTOCTOU:
    """Issue #8657 — ``_get_gh_semaphore()`` must guard the lazy init so two
    concurrent first-callers construct exactly one ``Semaphore`` between them.
    """

    def test_two_threads_racing_lazy_init_construct_one_semaphore(self) -> None:
        """Without the fix, both threads pass the ``is None`` check and both
        construct a fresh ``Semaphore``; the second STORE silently overwrites
        the first.

        Strategy: slow down the constructor so the second thread observes
        ``_gh_semaphore is None`` while the first thread is mid-construct.
        With the lock-guarded fix, the second thread blocks on the lock
        until the first finishes and stores, then short-circuits to the
        existing global without constructing.
        """
        constructions: list[object] = []
        construction_started = threading.Event()
        real_semaphore_cls = subprocess_util.asyncio.Semaphore

        def slow_constructor(*args: object, **kwargs: object) -> object:
            construction_started.set()
            # Hold the would-be race window open long enough for the second
            # thread to reach the None check.
            time.sleep(0.05)
            sem = real_semaphore_cls(*args, **kwargs)  # type: ignore[arg-type]
            constructions.append(sem)
            return sem

        def call_first() -> None:
            subprocess_util._get_gh_semaphore()

        def call_second() -> None:
            # Wait until the first thread is mid-construction (inside the
            # racy window) before our own _get_gh_semaphore call. This
            # forces both threads to observe ``is None`` simultaneously
            # without the fix; with the fix, this thread blocks on the
            # lock until the first thread's store completes.
            assert construction_started.wait(timeout=2.0)
            subprocess_util._get_gh_semaphore()

        with patch("subprocess_util.asyncio.Semaphore", side_effect=slow_constructor):
            t1 = threading.Thread(target=call_first)
            t2 = threading.Thread(target=call_second)
            t1.start()
            t2.start()
            t1.join(timeout=3.0)
            t2.join(timeout=3.0)

        assert not t1.is_alive() and not t2.is_alive(), (
            "Threads did not finish — the lazy-init lock should not deadlock."
        )
        assert len(constructions) == 1, (
            f"_get_gh_semaphore must lock-guard the None-check + construct + "
            f"assign sequence — got {len(constructions)} concurrent Semaphore "
            "constructions when both threads observed _gh_semaphore is None."
        )
