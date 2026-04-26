"""State mixin for AutoAgentPreflightLoop (spec §3.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class AutoAgentStateMixin:
    """Per-issue attempt counter + per-day spend tracker."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_auto_agent_attempts(self, issue: int) -> int:
        return int(self._data.auto_agent_attempts.get(str(issue), 0))

    def bump_auto_agent_attempts(self, issue: int) -> int:
        key = str(issue)
        current = int(self._data.auto_agent_attempts.get(key, 0))
        attempts = dict(self._data.auto_agent_attempts)
        attempts[key] = current + 1
        self._data.auto_agent_attempts = attempts
        self.save()
        return current + 1

    def clear_auto_agent_attempts(self, issue: int) -> None:
        key = str(issue)
        attempts = dict(self._data.auto_agent_attempts)
        attempts.pop(key, None)
        self._data.auto_agent_attempts = attempts
        self.save()

    def get_auto_agent_daily_spend(self, date_iso: str) -> float:
        return float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))

    def add_auto_agent_daily_spend(self, date_iso: str, usd: float) -> float:
        current = float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))
        new_total = current + usd
        spend = dict(self._data.auto_agent_daily_spend)
        spend[date_iso] = new_total
        # Prune entries older than ~90 days to bound state size — the dashboard
        # only reads the rolling 7d window from this cache, and the JSONL audit
        # remains the source of truth for older queries (spec §6.3).
        if len(spend) > 90:
            keep_keys = sorted(spend.keys())[-90:]
            spend = {k: spend[k] for k in keep_keys}
        self._data.auto_agent_daily_spend = spend
        self.save()
        return new_total
