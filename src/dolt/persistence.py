"""Repositories for events, runs, sessions, context cache, and metrics snapshots."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class EventRepository:
    """Append/query the ``events`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, event_type: str, payload: dict) -> None:
        """Insert a new event."""
        self.db.execute(
            "INSERT INTO events (event_type, payload_json) VALUES (%s, %s)",
            (event_type, json.dumps(payload)),
        )

    def query(
        self, event_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return recent events, optionally filtered by type."""
        if event_type:
            rows = self.db.fetchall(
                "SELECT id, event_type, payload_json, created_at "
                "FROM events WHERE event_type = %s "
                "ORDER BY id DESC LIMIT %s",
                (event_type, limit),
            )
        else:
            rows = self.db.fetchall(
                "SELECT id, event_type, payload_json, created_at "
                "FROM events ORDER BY id DESC LIMIT %s",
                (limit,),
            )
        return [
            {
                "id": r[0],
                "event_type": r[1],
                "payload": json.loads(r[2]) if r[2] else {},
                "created_at": r[3],
            }
            for r in rows
        ]


class RunRepository:
    """CRUD on the ``runs`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def create(self, run_id: str, data: dict) -> None:
        """Insert a new run record."""
        self.db.execute(
            "INSERT INTO runs (run_id, data_json) VALUES (%s, %s)",
            (run_id, json.dumps(data)),
        )

    def get(self, run_id: str) -> dict | None:
        """Return a run record, or ``None``."""
        row = self.db.fetchone(
            "SELECT data_json FROM runs WHERE run_id = %s", (run_id,)
        )
        return json.loads(row[0]) if row else None

    def update(self, run_id: str, data: dict) -> None:
        """Update an existing run record."""
        self.db.execute(
            "UPDATE runs SET data_json = %s WHERE run_id = %s",
            (json.dumps(data), run_id),
        )

    def get_all(self) -> list[dict]:
        """Return all run records."""
        rows = self.db.fetchall("SELECT run_id, data_json FROM runs")
        return [
            {"run_id": r[0], **json.loads(r[1])} for r in rows
        ]

    def delete(self, run_id: str) -> None:
        """Delete a run record."""
        self.db.execute("DELETE FROM runs WHERE run_id = %s", (run_id,))


class SessionRepository:
    """CRUD on the ``sessions`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def create(self, session_id: str, data: dict) -> None:
        """Insert a new session record."""
        self.db.execute(
            "INSERT INTO sessions (session_id, data_json) VALUES (%s, %s)",
            (session_id, json.dumps(data)),
        )

    def get(self, session_id: str) -> dict | None:
        """Return a session record, or ``None``."""
        row = self.db.fetchone(
            "SELECT data_json FROM sessions WHERE session_id = %s", (session_id,)
        )
        return json.loads(row[0]) if row else None

    def update(self, session_id: str, data: dict) -> None:
        """Update an existing session record."""
        self.db.execute(
            "UPDATE sessions SET data_json = %s WHERE session_id = %s",
            (json.dumps(data), session_id),
        )

    def get_all(self) -> list[dict]:
        """Return all session records."""
        rows = self.db.fetchall("SELECT session_id, data_json FROM sessions")
        return [
            {"session_id": r[0], **json.loads(r[1])} for r in rows
        ]

    def delete(self, session_id: str) -> None:
        """Delete a session record."""
        self.db.execute(
            "DELETE FROM sessions WHERE session_id = %s", (session_id,)
        )


class ContextCacheRepository:
    """Key-value cache backed by the ``context_cache`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def get(self, key: str) -> str | None:
        """Return the cached value for *key*, or ``None``."""
        row = self.db.fetchone(
            "SELECT value FROM context_cache WHERE cache_key = %s", (key,)
        )
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        """Set or overwrite *key* with *value*."""
        self.db.execute(
            "REPLACE INTO context_cache (cache_key, value) VALUES (%s, %s)",
            (key, value),
        )

    def delete(self, key: str) -> None:
        """Remove *key* from the cache."""
        self.db.execute(
            "DELETE FROM context_cache WHERE cache_key = %s", (key,)
        )

    def get_all(self) -> dict[str, str]:
        """Return the entire cache as a dict."""
        rows = self.db.fetchall("SELECT cache_key, value FROM context_cache")
        return {r[0]: r[1] for r in rows}


class MetricsSnapshotRepository:
    """Append/query the ``metrics_snapshots`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, snapshot: dict) -> None:
        """Insert a new metrics snapshot."""
        self.db.execute(
            "INSERT INTO metrics_snapshots (snapshot_json) VALUES (%s)",
            (json.dumps(snapshot),),
        )

    def query(self, limit: int = 100) -> list[dict]:
        """Return recent snapshots."""
        rows = self.db.fetchall(
            "SELECT id, snapshot_json, created_at "
            "FROM metrics_snapshots ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "snapshot": json.loads(r[1]) if r[1] else {},
                "created_at": r[2],
            }
            for r in rows
        ]
