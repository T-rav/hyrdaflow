"""Singleton-table repositories for lifetime stats, session counters, and active crate."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class _SingletonMixin:
    """Shared helpers for singleton-row tables."""

    _table: str
    db: DoltConnection

    def _get(self, column: str) -> Any:
        row = self.db.fetchone(f"SELECT {column} FROM {self._table} WHERE id = 1")  # noqa: S608
        return row[0] if row else None

    def _set(self, column: str, value: Any) -> None:
        self.db.execute(
            f"UPDATE {self._table} SET {column} = %s WHERE id = 1",  # noqa: S608
            (value,),
        )

    def get_all(self) -> dict[str, Any]:
        """Return the full singleton row as a dict."""
        cur = self.db.cursor()
        cur.execute(f"SELECT * FROM {self._table} WHERE id = 1")  # noqa: S608
        row = cur.fetchone()
        columns = [desc[0] for desc in cur.description] if cur.description else []
        cur.close()
        if not row:
            return {}
        return dict(zip(columns, row))

    def update(self, **kwargs: Any) -> None:
        """Update multiple columns at once."""
        if not kwargs:
            return
        assignments = ", ".join(f"{k} = %s" for k in kwargs)
        values = tuple(
            json.dumps(v) if isinstance(v, (dict, list)) else v
            for v in kwargs.values()
        )
        self.db.execute(
            f"UPDATE {self._table} SET {assignments} WHERE id = 1",  # noqa: S608
            values,
        )


class LifetimeStatsRepository(_SingletonMixin):
    """Reads/writes the ``lifetime_stats`` singleton table."""

    _table = "lifetime_stats"

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    # Convenience accessors for commonly used fields.
    def get_issues_completed(self) -> int:
        return self._get("issues_completed") or 0

    def set_issues_completed(self, value: int) -> None:
        self._set("issues_completed", value)

    def get_prs_merged(self) -> int:
        return self._get("prs_merged") or 0

    def set_prs_merged(self, value: int) -> None:
        self._set("prs_merged", value)


class SessionCounterRepository(_SingletonMixin):
    """Reads/writes the ``session_counters`` singleton table."""

    _table = "session_counters"

    def __init__(self, db: DoltConnection) -> None:
        self.db = db


class ActiveCrateRepository(_SingletonMixin):
    """Reads/writes the ``active_crate`` singleton table."""

    _table = "active_crate"

    def __init__(self, db: DoltConnection) -> None:
        self.db = db
