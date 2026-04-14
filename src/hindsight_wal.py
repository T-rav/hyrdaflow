"""Write-ahead log for Hindsight retain operations.

When a retain fails (Hindsight down, timeout, etc.), the operation is
appended to a local JSONL WAL file.  A background replay loop periodically
drains the WAL, retrying each entry against Hindsight.  Successfully
replayed entries are removed; permanent failures are logged and discarded
after ``max_retries`` attempts.

This ensures no memory is silently lost during Hindsight outages.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from hindsight_types import WALEntry

if TYPE_CHECKING:
    from hindsight import HindsightClient

logger = logging.getLogger("hydraflow.hindsight_wal")

# Re-export for backward compatibility
__all__ = ["HindsightWAL", "WALEntry", "run_wal_replay_loop"]

_DEFAULT_MAX_ENTRIES = 1000
_DEFAULT_REPLAY_INTERVAL = 60  # seconds
_DEFAULT_MAX_RETRIES = 5


class HindsightWAL:
    """JSONL-backed write-ahead log for failed Hindsight retains."""

    def __init__(
        self,
        wal_path: Path,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self._path = wal_path
        self._max_entries = max_entries
        self._max_retries = max_retries
        # Re-entrant lock so internal callers (e.g. append → _trim → load/
        # write_all) don't deadlock on the same lock. Serializes all file
        # operations so concurrent append() and replay() can't duplicate or
        # lose entries.
        self._lock = threading.RLock()

    def append(self, entry: WALEntry) -> None:
        """Append a failed retain to the WAL (sync, crash-safe)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                with self._path.open("a") as f:
                    f.write(entry.model_dump_json() + "\n")
                    f.flush()
                self._trim()
                try:
                    import sentry_sdk as _sentry

                    _sentry.add_breadcrumb(
                        category="hindsight_wal.buffered",
                        message=f"WAL entry buffered for bank={entry.bank}",
                        level="info",
                        data={"bank": entry.bank, "entry_count": self.count},
                    )
                except ImportError:
                    pass
            except OSError:
                logger.warning(
                    "Could not write to WAL at %s", self._path, exc_info=True
                )

    def load(self) -> list[WALEntry]:
        """Load all pending WAL entries."""
        with self._lock:
            if not self._path.is_file():
                return []
            entries: list[WALEntry] = []
            for line in self._path.read_text().splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entries.append(WALEntry.model_validate_json(stripped))
                except (ValueError, KeyError):
                    logger.warning("Skipping corrupt WAL entry: %s", stripped[:80])
            return entries

    def write_all(self, entries: list[WALEntry]) -> None:
        """Rewrite the WAL with the given entries (atomic replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                content = "\n".join(e.model_dump_json() for e in entries)
                if content:
                    content += "\n"
                self._path.write_text(content)
            except OSError:
                logger.warning("Could not rewrite WAL at %s", self._path, exc_info=True)

    def clear(self) -> None:
        """Remove all WAL entries."""
        with self._lock:
            if self._path.is_file():
                self._path.write_text("")

    @property
    def count(self) -> int:
        """Number of pending entries."""
        with self._lock:
            if not self._path.is_file():
                return 0
            return sum(
                1 for line in self._path.read_text().splitlines() if line.strip()
            )

    def _trim(self) -> None:
        """Drop oldest entries if WAL exceeds max_entries."""
        # Caller holds self._lock; load/write_all re-acquire via RLock.
        entries = self.load()
        if len(entries) > self._max_entries:
            dropped = len(entries) - self._max_entries
            entries = entries[dropped:]
            self.write_all(entries)
            logger.warning("WAL trimmed: dropped %d oldest entries", dropped)

    async def replay(self, client: HindsightClient) -> dict[str, int]:
        """Replay all pending entries against Hindsight.

        Returns ``{"replayed": N, "failed": N, "dropped": N}``.

        The lock is held across the entire replay so concurrent append()
        calls serialize behind replay. This trades latency on failing
        appends (rare — only during Hindsight outages) for correctness:
        no duplicate retains, no lost appends from read/write races.
        """
        with self._lock:
            entries = self.load()
            if not entries:
                return {"replayed": 0, "failed": 0, "dropped": 0}

            remaining: list[WALEntry] = []
            replayed = 0
            dropped = 0

            for entry in entries:
                try:
                    await client.retain(
                        entry.bank,
                        entry.content,
                        context=entry.context,
                        metadata=entry.metadata or None,
                    )
                    replayed += 1
                except Exception:
                    entry.retries += 1
                    if entry.retries >= self._max_retries:
                        dropped += 1
                        logger.warning(
                            "WAL entry dropped after %d retries: bank=%s content=%s",
                            entry.retries,
                            entry.bank,
                            entry.content[:60],
                        )
                    else:
                        remaining.append(entry)

            self.write_all(remaining)
            failed = len(remaining)

        if failed > 0:
            try:
                import sentry_sdk as _sentry

                _sentry.add_breadcrumb(
                    category="hindsight_wal.replay_failed",
                    message=f"WAL replay had {failed} remaining failures",
                    level="warning",
                    data={"failed": failed, "replayed": replayed, "dropped": dropped},
                )
            except ImportError:
                pass

        if replayed or dropped:
            logger.info(
                "WAL replay: %d replayed, %d still pending, %d dropped",
                replayed,
                failed,
                dropped,
            )

        return {"replayed": replayed, "failed": failed, "dropped": dropped}


async def run_wal_replay_loop(
    wal: HindsightWAL,
    client: HindsightClient,
    stop_event: asyncio.Event,
    *,
    interval: int = _DEFAULT_REPLAY_INTERVAL,
) -> None:
    """Background loop that replays the WAL periodically.

    Runs until *stop_event* is set.
    """
    while not stop_event.is_set():
        try:
            if wal.count > 0:
                await wal.replay(client)
        except Exception:
            logger.warning("WAL replay loop error", exc_info=True)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
