"""In-memory counters for knowledge-system activity.

Lightweight Prometheus-style counters backed by a threading Lock.  Callers
mutate via ``metrics.increment("<name>")``; dashboards read via
``metrics.snapshot()``.  All counters are process-local — aggregation
across workers (if any) is an open question for a future metrics bus.

Reasons for an in-memory module-level singleton (vs. passing an instance):
 - Every knowledge-system hook already runs in-process.
 - The counter set is fixed and small (~6 values).
 - Test isolation uses ``reset()`` at setup, not per-test instances.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

_COUNTER_NAMES = (
    "wiki_entries_ingested",
    "wiki_supersedes",
    "tribal_promotions",
    "adr_drafts_judged",
    "adr_drafts_opened",
    "reflections_bridged",
)


@dataclass
class KnowledgeMetrics:
    """Mutable counter bag for knowledge-system events."""

    _values: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(_COUNTER_NAMES, 0)
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self._values:
            raise KeyError(f"unknown counter: {name!r}")
        with self._lock:
            self._values[name] += amount

    def snapshot(self) -> dict[str, int]:
        """Return a copy of current counter values."""
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        """Zero every counter (used in tests)."""
        with self._lock:
            for k in self._values:
                self._values[k] = 0


metrics = KnowledgeMetrics()
