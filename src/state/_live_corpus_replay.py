"""State accessors for LiveCorpusReplayLoop (#8786 Phase 3).

Per-signature attempt counters for the 3-attempt escalation chain. A drift
signature persists across loop ticks until either:

- The fake catches up (clean tick clears all counters).
- The counter hits the threshold and an escalation issue is filed via
  the ``hitl-escalation`` label — the auto-agent preflight loop picks
  that up and runs its own 3-attempt cycle before human-required fires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class LiveCorpusReplayStateMixin:
    """Per-drift-signature attempt counters."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_live_corpus_drift_attempts(self, signature: str) -> int:
        return int(self._data.live_corpus_drift_attempts.get(signature, 0))

    def inc_live_corpus_drift_attempts(self, signature: str) -> int:
        current = int(self._data.live_corpus_drift_attempts.get(signature, 0)) + 1
        attempts = dict(self._data.live_corpus_drift_attempts)
        attempts[signature] = current
        self._data.live_corpus_drift_attempts = attempts
        self.save()
        return current

    def clear_live_corpus_drift_attempts(self) -> None:
        """Clear ALL counters — called on a clean tick (no drift detected)."""
        if self._data.live_corpus_drift_attempts:
            self._data.live_corpus_drift_attempts = {}
            self.save()
