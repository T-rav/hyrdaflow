"""State mixin for SandboxFailureFixerLoop.

Tracks per-PR auto-fix attempts so the loop can cap retries and escalate
to ``sandbox-hitl`` when the auto-agent fails to land a fix in
``auto_agent_max_attempts`` runs. Keys are stringified PR numbers (matches
the JSON-friendly storage convention used by the other attempt counters).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class SandboxFailureFixerStateMixin:
    """Per-PR auto-fix attempt counter for SandboxFailureFixerLoop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_sandbox_failure_fixer_attempts(self, pr_number: int) -> int:
        """Return the current attempt count for *pr_number* (0 if absent)."""
        return int(self._data.sandbox_failure_fixer_attempts.get(str(pr_number), 0))

    def bump_sandbox_failure_fixer_attempts(self, pr_number: int) -> int:
        """Increment and persist the attempt counter; return the new total."""
        key = str(pr_number)
        current = int(self._data.sandbox_failure_fixer_attempts.get(key, 0))
        attempts = dict(self._data.sandbox_failure_fixer_attempts)
        attempts[key] = current + 1
        self._data.sandbox_failure_fixer_attempts = attempts
        self.save()
        return current + 1

    def clear_sandbox_failure_fixer_attempts(self, pr_number: int) -> None:
        """Drop the counter for *pr_number* (e.g. after PR closure)."""
        key = str(pr_number)
        attempts = dict(self._data.sandbox_failure_fixer_attempts)
        if attempts.pop(key, None) is not None:
            self._data.sandbox_failure_fixer_attempts = attempts
            self.save()
