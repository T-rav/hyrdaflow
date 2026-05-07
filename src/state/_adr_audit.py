"""State accessors for AdrTouchpointAuditorLoop (ADR-0056)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class AdrAuditStateMixin:
    """Cursor (last-scanned merged-PR ISO timestamp) + per-finding repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_adr_audit_cursor(self) -> str:
        return self._data.adr_audit_cursor

    def set_adr_audit_cursor(self, cursor: str) -> None:
        self._data.adr_audit_cursor = cursor
        self.save()

    def get_adr_audit_attempts(self, key: str) -> int:
        return int(self._data.adr_audit_attempts.get(key, 0))

    def inc_adr_audit_attempts(self, key: str) -> int:
        current = int(self._data.adr_audit_attempts.get(key, 0)) + 1
        attempts = dict(self._data.adr_audit_attempts)
        attempts[key] = current
        self._data.adr_audit_attempts = attempts
        self.save()
        return current

    def clear_adr_audit_attempts(self, key: str) -> None:
        attempts = dict(self._data.adr_audit_attempts)
        attempts.pop(key, None)
        self._data.adr_audit_attempts = attempts
        self.save()
