"""Repository for troubleshooting patterns."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class TroubleshootingPatternRepository:
    """CRUD on the ``troubleshooting_patterns`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def upsert(self, pattern_key: str, pattern: dict) -> None:
        """Insert or replace a troubleshooting pattern."""
        self.db.execute(
            "REPLACE INTO troubleshooting_patterns "
            "(pattern_key, pattern_json) VALUES (%s, %s)",
            (pattern_key, json.dumps(pattern)),
        )

    def get(self, pattern_key: str) -> dict | None:
        """Return a pattern, or ``None``."""
        row = self.db.fetchone(
            "SELECT pattern_json FROM troubleshooting_patterns "
            "WHERE pattern_key = %s",
            (pattern_key,),
        )
        return json.loads(row[0]) if row else None

    def get_all(self) -> dict[str, dict]:
        """Return all patterns as ``{key: pattern}``."""
        rows = self.db.fetchall(
            "SELECT pattern_key, pattern_json FROM troubleshooting_patterns"
        )
        return {r[0]: json.loads(r[1]) for r in rows}

    def delete(self, pattern_key: str) -> None:
        """Remove a pattern."""
        self.db.execute(
            "DELETE FROM troubleshooting_patterns WHERE pattern_key = %s",
            (pattern_key,),
        )

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent patterns."""
        rows = self.db.fetchall(
            "SELECT id, pattern_key, pattern_json, created_at "
            "FROM troubleshooting_patterns ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "pattern_key": r[1],
                "pattern": json.loads(r[2]) if r[2] else {},
                "created_at": r[3],
            }
            for r in rows
        ]
