"""Durable JSONL queue for retrospective analysis work items.

Producers (PostMergeHandler, ReviewPhase) append items.
The RetrospectiveLoop consumer loads, processes, and acknowledges them.
Unacknowledged items survive crashes for replay on next cycle.
"""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger("hydraflow.retrospective_queue")

_DEFAULT_MAX_ENTRIES = 500


class QueueKind(StrEnum):
    """Type of retrospective work item."""

    RETRO_PATTERNS = "retro_patterns"
    REVIEW_PATTERNS = "review_patterns"
    VERIFY_PROPOSALS = "verify_proposals"


class QueueItem(BaseModel):
    """Single work item in the retrospective queue."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: QueueKind
    issue_number: int | None = None
    pr_number: int | None = None


class RetrospectiveQueue:
    """JSONL-backed durable queue.  Append is crash-safe (fsync).

    Items persist until explicitly acknowledged after processing.
    """

    def __init__(self, path: Path, *, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._path = path
        self._max_entries = max_entries

    def append(self, item: QueueItem) -> None:
        """Append a work item (sync, crash-safe)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._path.open("a") as f:
                f.write(item.model_dump_json() + "\n")
                f.flush()
            self._trim()
        except OSError:
            logger.warning("Could not write to queue at %s", self._path, exc_info=True)

    def load(self) -> list[QueueItem]:
        """Load all pending items.  Skips corrupt lines."""
        if not self._path.is_file():
            return []
        items: list[QueueItem] = []
        for line in self._path.read_text().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                items.append(QueueItem.model_validate_json(stripped))
            except Exception:
                logger.debug(
                    "Skipping corrupt queue line: %s",
                    stripped[:80],
                    exc_info=True,
                )
        return items

    def acknowledge(self, item_ids: list[str]) -> None:
        """Remove processed items by ID.  Rewrites the file atomically."""
        if not item_ids:
            return
        ids_set = set(item_ids)
        remaining = [i for i in self.load() if i.id not in ids_set]
        self._rewrite(remaining)

    def _trim(self) -> None:
        """Drop oldest entries if queue exceeds max_entries."""
        items = self.load()
        if len(items) > self._max_entries:
            self._rewrite(items[-self._max_entries :])

    def _rewrite(self, items: list[QueueItem]) -> None:
        """Atomically rewrite the queue file."""
        tmp = self._path.with_suffix(".tmp")
        try:
            with tmp.open("w") as f:
                for item in items:
                    f.write(item.model_dump_json() + "\n")
                f.flush()
            tmp.replace(self._path)
        except OSError:
            logger.warning("Could not rewrite queue at %s", self._path, exc_info=True)
