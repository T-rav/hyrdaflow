"""State accessors for TriageRetryLoop (ADR-0063 W2).

Two fields:

* ``triage_retry_attempts`` — per-issue counter of how many times
  TriageRetryLoop has re-dispatched a parked issue back to triage.
  Cleared when the issue closes (reconciled in the loop) or hits the
  ``triage_retry_max_attempts`` ceiling and escalates to HITL.
* ``triage_retry_last_attempt`` — ISO-8601 timestamp of the most recent
  retry, used to honour the 24h-between-retries gate independently of
  the tick interval (a slow tick on a 6h cadence loop still respects
  the 24h floor).

Pattern mirrors ``_memory_backlog.MemoryBacklogStateMixin`` and
``_contract_refresh.ContractRefreshStateMixin``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class TriageRetryStateMixin:
    """Per-issue retry counter + last-attempt timestamp for TriageRetryLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_triage_retry_attempts(self, issue_number: int) -> int:
        key = str(issue_number)
        return int(self._data.triage_retry_attempts.get(key, 0))

    def inc_triage_retry_attempts(self, issue_number: int) -> int:
        key = str(issue_number)
        current = int(self._data.triage_retry_attempts.get(key, 0)) + 1
        attempts = dict(self._data.triage_retry_attempts)
        attempts[key] = current
        self._data.triage_retry_attempts = attempts
        self.save()
        return current

    def clear_triage_retry_attempts(self, issue_number: int) -> None:
        key = str(issue_number)
        attempts = dict(self._data.triage_retry_attempts)
        last = dict(self._data.triage_retry_last_attempt)
        attempts.pop(key, None)
        last.pop(key, None)
        self._data.triage_retry_attempts = attempts
        self._data.triage_retry_last_attempt = last
        self.save()

    def get_triage_retry_last_attempt(self, issue_number: int) -> str:
        key = str(issue_number)
        return str(self._data.triage_retry_last_attempt.get(key, ""))

    def set_triage_retry_last_attempt(self, issue_number: int, ts: str) -> None:
        key = str(issue_number)
        last = dict(self._data.triage_retry_last_attempt)
        last[key] = ts
        self._data.triage_retry_last_attempt = last
        self.save()
