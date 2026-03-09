"""Repository for learnings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class LearningRepository:
    """Append/query the ``learnings`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, learning: dict) -> None:
        """Insert a new learning."""
        self.db.execute(
            "INSERT INTO learnings (data_json) VALUES (%s)",
            (json.dumps(learning),),
        )

    def query(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent learnings."""
        rows = self.db.fetchall(
            "SELECT id, data_json, timestamp "
            "FROM learnings ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "learning": json.loads(r[1]) if r[1] else {},
                "created_at": r[2],
            }
            for r in rows
        ]
