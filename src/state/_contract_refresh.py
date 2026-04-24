"""State accessors for ContractRefreshLoop (spec §4.2 Task 18).

Single field: ``contract_refresh_attempts`` — per-adapter counter of
consecutive drift ticks. The loop increments once per adapter on every
tick where that adapter drifts; clears when the adapter goes drift-free.
When the counter hits ``config.max_fake_repair_attempts`` the loop files
a ``hitl-escalation`` issue keyed on the adapter name.

Pattern mirrors ``_rc_budget.RCBudgetStateMixin`` and
``_trust_fleet_sanity.TrustFleetSanityStateMixin`` — a thin dict-of-int
with get/inc/clear. Kept in its own mixin so the StateTracker MRO stays
flat and each domain's state is a single-file grep.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class ContractRefreshStateMixin:
    """Per-adapter consecutive-drift-attempt counter."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_contract_refresh_attempts(self, adapter: str) -> int:
        return int(self._data.contract_refresh_attempts.get(adapter, 0))

    def inc_contract_refresh_attempts(self, adapter: str) -> int:
        current = int(self._data.contract_refresh_attempts.get(adapter, 0)) + 1
        attempts = dict(self._data.contract_refresh_attempts)
        attempts[adapter] = current
        self._data.contract_refresh_attempts = attempts
        self.save()
        return current

    def clear_contract_refresh_attempts(self, adapter: str) -> None:
        attempts = dict(self._data.contract_refresh_attempts)
        attempts.pop(adapter, None)
        self._data.contract_refresh_attempts = attempts
        self.save()
