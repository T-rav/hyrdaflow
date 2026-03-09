"""Repository for troubleshooting patterns."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class TroubleshootingPatternRepository:
    """CRUD on the ``troubleshooting_patterns`` table.

    Keys are ``language:pattern_name`` strings that map to the composite
    unique key ``(language, pattern_name)`` in the schema.
    """

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    @staticmethod
    def _split_key(key: str) -> tuple[str, str]:
        """Split a ``language:pattern_name`` key into parts."""
        parts = key.split(":", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", parts[0]

    def upsert(self, key: str, pattern: dict) -> None:
        """Insert or replace a troubleshooting pattern."""
        language, pattern_name = self._split_key(key)
        self.db.execute(
            "REPLACE INTO troubleshooting_patterns "
            "(language, pattern_name, data_json, frequency) VALUES (%s, %s, %s, %s)",
            (language, pattern_name, json.dumps(pattern), pattern.get("frequency", 1)),
        )

    def get(self, key: str) -> dict | None:
        """Return a pattern, or ``None``."""
        language, pattern_name = self._split_key(key)
        row = self.db.fetchone(
            "SELECT data_json FROM troubleshooting_patterns "
            "WHERE language = %s AND pattern_name = %s",
            (language, pattern_name),
        )
        return json.loads(row[0]) if row else None

    def get_all(self) -> dict[str, dict]:
        """Return all patterns as ``{key: pattern}``."""
        rows = self.db.fetchall(
            "SELECT language, pattern_name, data_json FROM troubleshooting_patterns"
        )
        return {f"{r[0]}:{r[1]}": json.loads(r[2]) if r[2] else {} for r in rows}

    def delete(self, key: str) -> None:
        """Remove a pattern."""
        language, pattern_name = self._split_key(key)
        self.db.execute(
            "DELETE FROM troubleshooting_patterns "
            "WHERE language = %s AND pattern_name = %s",
            (language, pattern_name),
        )

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent patterns."""
        rows = self.db.fetchall(
            "SELECT id, language, pattern_name, data_json, frequency "
            "FROM troubleshooting_patterns ORDER BY frequency DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "language": r[1],
                "pattern_name": r[2],
                "pattern": json.loads(r[3]) if r[3] else {},
                "frequency": r[4],
            }
            for r in rows
        ]
