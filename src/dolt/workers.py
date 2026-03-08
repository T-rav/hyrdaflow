"""Repository for background worker state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class WorkerRepository:
    """CRUD for the ``bg_workers`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def upsert(
        self,
        name: str,
        *,
        state_json: dict | None = None,
        heartbeat_json: dict | None = None,
        enabled: bool = True,
        interval: int | None = None,
    ) -> None:
        """Insert or update a worker record."""
        self.db.execute(
            "REPLACE INTO bg_workers "
            "(name, state_json, heartbeat_json, enabled, interval_seconds) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                name,
                json.dumps(state_json) if state_json else None,
                json.dumps(heartbeat_json) if heartbeat_json else None,
                enabled,
                interval,
            ),
        )

    def get(self, name: str) -> dict[str, Any] | None:
        """Return a worker record as a dict, or ``None``."""
        row = self.db.fetchone(
            "SELECT name, state_json, heartbeat_json, enabled, interval_seconds "
            "FROM bg_workers WHERE name = %s",
            (name,),
        )
        if not row:
            return None
        return {
            "name": row[0],
            "state_json": json.loads(row[1]) if row[1] else None,
            "heartbeat_json": json.loads(row[2]) if row[2] else None,
            "enabled": bool(row[3]),
            "interval": row[4],
        }

    def get_all(self) -> list[dict[str, Any]]:
        """Return all worker records."""
        rows = self.db.fetchall(
            "SELECT name, state_json, heartbeat_json, enabled, interval_seconds "
            "FROM bg_workers"
        )
        return [
            {
                "name": r[0],
                "state_json": json.loads(r[1]) if r[1] else None,
                "heartbeat_json": json.loads(r[2]) if r[2] else None,
                "enabled": bool(r[3]),
                "interval": r[4],
            }
            for r in rows
        ]

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Toggle a worker's enabled flag."""
        self.db.execute(
            "UPDATE bg_workers SET enabled = %s WHERE name = %s",
            (enabled, name),
        )

    def update_heartbeat(self, name: str, heartbeat: dict) -> None:
        """Update the heartbeat JSON for a worker."""
        self.db.execute(
            "UPDATE bg_workers SET heartbeat_json = %s WHERE name = %s",
            (json.dumps(heartbeat), name),
        )

    def delete(self, name: str) -> None:
        """Remove a worker record."""
        self.db.execute("DELETE FROM bg_workers WHERE name = %s", (name,))
