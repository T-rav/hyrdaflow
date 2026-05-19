"""Regression tests for issue #7839.

``workspace.py`` lazily populates ``_FETCH_LOCKS`` and ``_WORKTREE_LOCKS`` via a
check-then-set pattern::

    lock = _FETCH_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _FETCH_LOCKS[key] = lock

Two concurrent callers racing through this window each create a separate
``asyncio.Lock``, so neither contends with the other — the per-repo
serialisation guarantee is broken.

Fix: replace check-then-set with ``dict.setdefault`` which is atomic in CPython
because it holds the GIL across the lookup+insert.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import workspace
from tests.helpers import ConfigFactory


class _RacyDict(dict):
    """Dict subclass that forces a context switch after ``get()`` returns None.

    Both threads arrive at the barrier before either stores a new lock,
    deterministically triggering the TOCTOU window.
    """

    def __init__(self, barrier: threading.Barrier, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._barrier = barrier

    def get(self, key, default=None):
        result = super().get(key, default)
        if result is None:
            self._barrier.wait(timeout=5)
        return result


class TestIssue7839FetchLockTOCTOU:
    """_repo_fetch_lock() must return the same Lock for concurrent callers."""

    def test_concurrent_callers_get_same_fetch_lock(self, tmp_path: Path) -> None:
        """Two threads calling _repo_fetch_lock() for the same repo key must
        receive the identical asyncio.Lock instance."""
        barrier = threading.Barrier(2, timeout=5)
        racy_dict: _RacyDict = _RacyDict(barrier)

        config = ConfigFactory.create(repo_root=tmp_path)
        results: list[asyncio.Lock | None] = [None, None]
        errors: list[Exception | None] = [None, None]

        def worker(index: int) -> None:
            try:
                mgr = workspace.WorkspaceManager(config)
                results[index] = mgr._repo_fetch_lock()
            except Exception as exc:
                errors[index] = exc

        with patch.object(workspace, "_FETCH_LOCKS", racy_dict):
            t1 = threading.Thread(target=worker, args=(0,))
            t2 = threading.Thread(target=worker, args=(1,))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

        for i, err in enumerate(errors):
            if err is not None:
                raise AssertionError(f"worker {i} raised: {err}") from err

        assert results[0] is not None, "worker 0 did not return a lock"
        assert results[1] is not None, "worker 1 did not return a lock"

        assert results[0] is results[1], (
            f"Two callers got different Lock objects for the same repo key — "
            f"TOCTOU race in _repo_fetch_lock() (issue #7839). "
            f"Lock 0: {id(results[0]):#x}, Lock 1: {id(results[1]):#x}"
        )


class TestIssue7839WorkspaceLockTOCTOU:
    """_repo_workspace_lock() must return the same Lock for concurrent callers."""

    def test_concurrent_callers_get_same_workspace_lock(self, tmp_path: Path) -> None:
        """Two threads calling _repo_workspace_lock() for the same repo slug
        must receive the identical asyncio.Lock instance."""
        barrier = threading.Barrier(2, timeout=5)
        racy_dict: _RacyDict = _RacyDict(barrier)

        config = ConfigFactory.create(repo_root=tmp_path)
        results: list[asyncio.Lock | None] = [None, None]
        errors: list[Exception | None] = [None, None]

        def worker(index: int) -> None:
            try:
                mgr = workspace.WorkspaceManager(config)
                results[index] = mgr._repo_workspace_lock()
            except Exception as exc:
                errors[index] = exc

        with patch.object(workspace, "_WORKTREE_LOCKS", racy_dict):
            t1 = threading.Thread(target=worker, args=(0,))
            t2 = threading.Thread(target=worker, args=(1,))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

        for i, err in enumerate(errors):
            if err is not None:
                raise AssertionError(f"worker {i} raised: {err}") from err

        assert results[0] is not None, "worker 0 did not return a lock"
        assert results[1] is not None, "worker 1 did not return a lock"

        assert results[0] is results[1], (
            f"Two callers got different Lock objects for the same repo slug — "
            f"TOCTOU race in _repo_workspace_lock() (issue #7839). "
            f"Lock 0: {id(results[0]):#x}, Lock 1: {id(results[1]):#x}"
        )
