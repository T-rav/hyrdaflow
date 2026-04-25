"""State accessors for StagingBisectLoop (spec §4.3 + §8 prerequisite).

Six fields:

- ``last_green_rc_sha``: HEAD SHA of the most recent RC PR that promoted
  to ``main`` (written by ``StagingPromotionLoop`` on the
  ``status=promoted`` path).
- ``last_rc_red_sha``: HEAD SHA of the most recent RC PR that failed CI
  (written on the ``status=ci_failed`` path). Polled by
  ``StagingBisectLoop`` to trigger a bisect cycle.
- ``rc_cycle_id``: monotonically increasing RC-failure cycle counter,
  bumped whenever ``last_rc_red_sha`` is set. Used to scope the
  ``auto_reverts_in_cycle`` guardrail.
- ``auto_reverts_in_cycle``: count of auto-reverts filed inside the
  current ``rc_cycle_id``. Reset on a successful promotion.
- ``auto_reverts_successful``: lifetime count of auto-reverts that
  produced a subsequent green RC.
- ``flake_reruns_total``: lifetime count of RC-red events dismissed by
  the flake filter (second probe run passed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class StagingBisectStateMixin:
    """State methods for the staging-red attribution bisect loop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- last_green_rc_sha ---

    def get_last_green_rc_sha(self) -> str:
        return self._data.last_green_rc_sha

    def set_last_green_rc_sha(self, sha: str) -> None:
        self._data.last_green_rc_sha = sha
        self.save()

    # --- last_rc_red_sha + rc_cycle_id ---

    def get_last_rc_red_sha(self) -> str:
        return self._data.last_rc_red_sha

    def get_rc_cycle_id(self) -> int:
        return self._data.rc_cycle_id

    def set_last_rc_red_sha_and_bump_cycle(self, sha: str) -> None:
        """Atomic update: set the red SHA and bump the cycle counter.

        These two fields are always written together so ``rc_cycle_id``
        is a reliable scope for ``auto_reverts_in_cycle`` — a second red
        with the same cycle-id means we are still repairing the same
        merge batch.
        """
        self._data.last_rc_red_sha = sha
        self._data.rc_cycle_id += 1
        self._data.auto_reverts_in_cycle = 0
        self.save()

    # --- auto_reverts_in_cycle ---

    def get_auto_reverts_in_cycle(self) -> int:
        return self._data.auto_reverts_in_cycle

    def increment_auto_reverts_in_cycle(self) -> int:
        """Increment and return the new count."""
        self._data.auto_reverts_in_cycle += 1
        self.save()
        return self._data.auto_reverts_in_cycle

    def reset_auto_reverts_in_cycle(self) -> None:
        self._data.auto_reverts_in_cycle = 0
        self.save()

    # --- auto_reverts_successful ---

    def get_auto_reverts_successful(self) -> int:
        return self._data.auto_reverts_successful

    def increment_auto_reverts_successful(self) -> None:
        self._data.auto_reverts_successful += 1
        self.save()

    # --- flake_reruns_total ---

    def get_flake_reruns_total(self) -> int:
        return self._data.flake_reruns_total

    def increment_flake_reruns_total(self) -> None:
        self._data.flake_reruns_total += 1
        self.save()

    # --- retry_lineage_attempts (spec §4.3 lines 645–659) ---

    def get_retry_lineage_attempts(self, lineage_id: str) -> int:
        """Return the number of retries already filed for ``lineage_id``."""
        return self._data.retry_lineage_attempts.get(lineage_id, 0)

    def increment_retry_lineage_attempts(self, lineage_id: str) -> int:
        """Bump the per-lineage retry counter and return the new value."""
        current = self._data.retry_lineage_attempts.get(lineage_id, 0) + 1
        self._data.retry_lineage_attempts[lineage_id] = current
        self.save()
        return current

    def reset_retry_lineage_attempts(self, lineage_id: str) -> None:
        """Drop the lineage from tracking — invoked after a green RC
        that resolves the lineage's underlying defect."""
        self._data.retry_lineage_attempts.pop(lineage_id, None)
        self.save()
