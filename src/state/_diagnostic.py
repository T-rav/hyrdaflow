"""Diagnostic self-healing state — escalation context, attempts, severity."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import AttemptRecord, EscalationContext, Severity, StateData

logger = logging.getLogger("hydraflow.state")


class DiagnosticStateMixin:
    """State methods for the diagnostic self-healing loop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    # --- escalation context ---

    def set_escalation_context(
        self, issue_number: int, context: EscalationContext
    ) -> None:
        """Persist escalation context for *issue_number*."""
        self._data.escalation_contexts[self._key(issue_number)] = context.model_dump()
        self.save()

    def get_escalation_context(self, issue_number: int) -> EscalationContext | None:
        """Return escalation context for *issue_number*, or ``None`` if absent."""
        from models import EscalationContext as EC  # noqa: PLC0415

        raw = self._data.escalation_contexts.get(self._key(issue_number))
        if raw is None:
            return None
        return EC.model_validate(raw)

    # --- diagnostic attempts ---

    def add_diagnostic_attempt(self, issue_number: int, record: AttemptRecord) -> None:
        """Append a diagnostic fix attempt record for *issue_number*."""
        key = self._key(issue_number)
        attempts = self._data.diagnostic_attempts.get(key, [])
        attempts.append(record.model_dump())
        self._data.diagnostic_attempts[key] = attempts
        self.save()

    def get_diagnostic_attempts(self, issue_number: int) -> list[AttemptRecord]:
        """Return all diagnostic attempt records for *issue_number*."""
        from models import AttemptRecord as AR  # noqa: PLC0415

        raw_list = self._data.diagnostic_attempts.get(self._key(issue_number), [])
        return [AR.model_validate(r) for r in raw_list]

    # --- severity classification ---

    def set_diagnosis_severity(self, issue_number: int, severity: Severity) -> None:
        """Persist the diagnosed severity level for *issue_number*."""
        self._data.diagnosis_severities[self._key(issue_number)] = severity.value
        self.save()

    def get_diagnosis_severity(self, issue_number: int) -> Severity | None:
        """Return the diagnosed severity for *issue_number*, or ``None`` if unset."""
        from models import Severity as S  # noqa: PLC0415

        raw = self._data.diagnosis_severities.get(self._key(issue_number))
        if raw is None:
            return None
        return S(raw)

    # --- bulk clear ---

    def clear_diagnostic_state(self, issue_number: int) -> None:
        """Clear all diagnostic tracking state for *issue_number* and persist once."""
        key = self._key(issue_number)
        self._data.escalation_contexts.pop(key, None)
        self._data.diagnostic_attempts.pop(key, None)
        self._data.diagnosis_severities.pop(key, None)
        self.save()
