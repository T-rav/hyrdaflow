"""EventuallyConsistent — simulates read-after-write staleness.

Strategy: snapshot state before a watched write; serve the snapshot for the
next N watched reads, then flip to current state.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any


class EventuallyConsistent:
    def __init__(
        self,
        wrapped: Any,
        *,
        delay_reads: int,
        watch_writes: list[str],
        watch_reads: list[str],
    ) -> None:
        self._wrapped = wrapped
        self._delay_reads = delay_reads
        self._watch_writes = set(watch_writes)
        self._watch_reads = set(watch_reads)
        self._pending_reads = 0
        self._snapshot: Any = None

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._wrapped, name)

        if name in self._watch_writes and callable(attr):
            if asyncio.iscoroutinefunction(attr):

                async def _async_write_wrapper(*args: Any, **kwargs: Any) -> Any:
                    # Snapshot BEFORE applying the write.
                    self._snapshot = copy.deepcopy(self._wrapped)
                    self._pending_reads = self._delay_reads
                    return await attr(*args, **kwargs)

                return _async_write_wrapper

            def _write_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Snapshot BEFORE applying the write.
                self._snapshot = copy.deepcopy(self._wrapped)
                self._pending_reads = self._delay_reads
                return attr(*args, **kwargs)

            return _write_wrapper

        if name in self._watch_reads and callable(attr):

            def _read_wrapper(*args: Any, **kwargs: Any) -> Any:
                if self._pending_reads > 0 and self._snapshot is not None:
                    self._pending_reads -= 1
                    stale_attr = getattr(self._snapshot, name)
                    return stale_attr(*args, **kwargs)
                return attr(*args, **kwargs)

            return _read_wrapper

        return attr
