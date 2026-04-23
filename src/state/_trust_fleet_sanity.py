"""State accessors for TrustFleetSanityLoop (spec §12.1).

Three fields:

- ``trust_fleet_sanity_attempts``: ``dict[str, int]`` — per-anomaly-key
  repair-attempt counter. Key format ``f"{kind}:{worker}"``. The
  sanity loop uses a 1-attempt escalation (anomaly IS the escalation),
  but the counter surface is preserved so the close-reconcile can
  reset it and so future policy can raise the bar without a schema
  migration.
- ``trust_fleet_sanity_last_run``: ISO timestamp of the most-recent
  successful tick. Used by the HealthMonitor dead-man-switch.
- ``trust_fleet_sanity_last_seen_counts``: per-worker cumulative
  counter snapshot (``issues_filed_total``) + observation timestamp.
  Fallback source for the issues-per-hour detector when the event log
  is unavailable (e.g. a fresh install with no persisted events yet).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class TrustFleetSanityStateMixin:
    """State for `TrustFleetSanityLoop` (spec §12.1)."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- per-anomaly attempt counters ---

    def get_trust_fleet_sanity_attempts(self, key: str) -> int:
        return int(self._data.trust_fleet_sanity_attempts.get(key, 0))

    def inc_trust_fleet_sanity_attempts(self, key: str) -> int:
        current = int(self._data.trust_fleet_sanity_attempts.get(key, 0)) + 1
        attempts = dict(self._data.trust_fleet_sanity_attempts)
        attempts[key] = current
        self._data.trust_fleet_sanity_attempts = attempts
        self.save()
        return current

    def clear_trust_fleet_sanity_attempts(self, key: str) -> None:
        attempts = dict(self._data.trust_fleet_sanity_attempts)
        attempts.pop(key, None)
        self._data.trust_fleet_sanity_attempts = attempts
        self.save()

    # --- last successful tick (for HealthMonitor dead-man-switch) ---

    def get_trust_fleet_sanity_last_run(self) -> str | None:
        return self._data.trust_fleet_sanity_last_run

    def set_trust_fleet_sanity_last_run(self, iso: str) -> None:
        self._data.trust_fleet_sanity_last_run = iso
        self.save()

    # --- per-worker counter snapshots (fallback for issues-per-hour) ---

    def get_trust_fleet_sanity_last_seen_counts(
        self,
    ) -> dict[str, dict[str, int | str]]:
        return {
            name: dict(entry)
            for name, entry in self._data.trust_fleet_sanity_last_seen_counts.items()
        }

    def set_trust_fleet_sanity_last_seen_count(
        self,
        worker: str,
        *,
        issues_filed_total: int,
        observed_at: str,
    ) -> None:
        snap = dict(self._data.trust_fleet_sanity_last_seen_counts)
        snap[worker] = {
            "issues_filed_total": int(issues_filed_total),
            "observed_at": observed_at,
        }
        self._data.trust_fleet_sanity_last_seen_counts = snap
        self.save()
