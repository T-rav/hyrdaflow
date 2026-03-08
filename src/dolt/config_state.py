"""Singleton repositories for memory, manifest, and metrics state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class _StateSingletonMixin:
    """Shared helpers for state singleton tables."""

    _table: str
    db: DoltConnection

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

    def _get(self, column: str) -> Any:
        row = self.db.fetchone(f"SELECT {column} FROM {self._table} WHERE id = 1")  # noqa: S608
        return row[0] if row else None

    def _set(self, column: str, value: Any) -> None:
        self.db.execute(
            f"UPDATE {self._table} SET {column} = %s WHERE id = 1",  # noqa: S608
            (value,),
        )


class MemoryStateRepository(_StateSingletonMixin):
    """Reads/writes the ``memory_state`` singleton."""

    _table = "memory_state"

    def __init__(self, db: DoltConnection) -> None:
        self.db = db


class ManifestStateRepository(_StateSingletonMixin):
    """Reads/writes the ``manifest_state`` singleton."""

    _table = "manifest_state"

    def __init__(self, db: DoltConnection) -> None:
        self.db = db


class MetricsStateRepository(_StateSingletonMixin):
    """Reads/writes the ``metrics_state`` singleton."""

    _table = "metrics_state"

    def __init__(self, db: DoltConnection) -> None:
        self.db = db
